"""Fetch open positions from public job-board APIs (Greenhouse, Lever, Ashby).

These are the official, unauthenticated JSON endpoints that companies' own
career pages use, so no scraping of LinkedIn or other sites is involved.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass

import httpx

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Company:
    name: str
    source: str  # greenhouse | lever | ashby
    slug: str


@dataclass(frozen=True)
class Job:
    source: str
    company: str
    job_id: str
    title: str
    locations: tuple[str, ...]
    url: str
    country: str = ""

    @property
    def key(self) -> str:
        return f"{self.source}:{self.company}:{self.job_id}"

    @property
    def location(self) -> str:
        return " / ".join(loc for loc in self.locations if loc) or "—"


async def fetch_greenhouse(client: httpx.AsyncClient, company: Company) -> list[Job]:
    url = f"https://boards-api.greenhouse.io/v1/boards/{company.slug}/jobs"
    response = await client.get(url)
    response.raise_for_status()
    return [
        Job(
            source="greenhouse",
            company=company.name,
            job_id=str(item["id"]),
            title=item.get("title", "").strip(),
            locations=((item.get("location") or {}).get("name", ""),),
            url=item.get("absolute_url", ""),
        )
        for item in response.json().get("jobs", [])
    ]


async def fetch_lever(client: httpx.AsyncClient, company: Company) -> list[Job]:
    url = f"https://api.lever.co/v0/postings/{company.slug}"
    response = await client.get(url, params={"mode": "json"})
    response.raise_for_status()
    jobs = []
    for item in response.json():
        categories = item.get("categories") or {}
        locations = tuple(categories.get("allLocations") or [categories.get("location", "")])
        jobs.append(
            Job(
                source="lever",
                company=company.name,
                job_id=str(item["id"]),
                title=item.get("text", "").strip(),
                locations=locations,
                url=item.get("hostedUrl", ""),
                country=item.get("country") or "",
            )
        )
    return jobs


async def fetch_ashby(client: httpx.AsyncClient, company: Company) -> list[Job]:
    url = f"https://api.ashbyhq.com/posting-api/job-board/{company.slug}"
    response = await client.get(url)
    response.raise_for_status()
    jobs = []
    for item in response.json().get("jobs", []):
        if item.get("isListed") is False:
            continue
        secondary = [s.get("location", "") for s in item.get("secondaryLocations") or []]
        jobs.append(
            Job(
                source="ashby",
                company=company.name,
                job_id=str(item["id"]),
                title=item.get("title", "").strip(),
                locations=(item.get("location", ""), *secondary),
                url=item.get("jobUrl", ""),
            )
        )
    return jobs


FETCHERS: dict[str, Callable[[httpx.AsyncClient, Company], Awaitable[list[Job]]]] = {
    "greenhouse": fetch_greenhouse,
    "lever": fetch_lever,
    "ashby": fetch_ashby,
}


async def fetch_all(
    client: httpx.AsyncClient, companies: Iterable[Company], concurrency: int = 5
) -> tuple[list[Job], dict[str, str]]:
    """Fetch every company's board. Returns (jobs, {company: error}) — one bad
    board never breaks the whole digest."""
    semaphore = asyncio.Semaphore(concurrency)
    errors: dict[str, str] = {}

    async def one(company: Company) -> list[Job]:
        fetcher = FETCHERS.get(company.source)
        if fetcher is None:
            errors[company.name] = f"unknown source '{company.source}'"
            return []
        async with semaphore:
            try:
                return await fetcher(client, company)
            except (httpx.HTTPError, ValueError, KeyError) as exc:
                log.warning("Failed to fetch %s (%s): %r", company.name, company.source, exc)
                errors[company.name] = type(exc).__name__
                return []

    results = await asyncio.gather(*(one(c) for c in companies))
    return [job for batch in results for job in batch], errors

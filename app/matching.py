"""Decide whether a job is relevant: title keywords + location."""

from __future__ import annotations

from collections.abc import Iterable

from .config import SearchConfig
from .sources import Job


def title_matches(title: str, config: SearchConfig) -> bool:
    if not config.keyword_re.search(title):
        return False
    exclude = config.exclude_re
    return not (exclude and exclude.search(title))


def location_matches(job: Job, config: SearchConfig) -> bool:
    if not config.locations and not config.countries:
        return True
    if job.country and job.country.upper() in config.countries:
        return True
    text = " ".join(job.locations).lower()
    return any(loc in text for loc in config.locations)


def filter_jobs(jobs: Iterable[Job], config: SearchConfig) -> list[Job]:
    matched = [j for j in jobs if title_matches(j.title, config) and location_matches(j, config)]
    return sorted(matched, key=lambda j: (j.company.lower(), j.title.lower()))

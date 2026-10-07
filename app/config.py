"""Settings from environment variables plus search preferences from YAML."""

from __future__ import annotations

import datetime as dt
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

from .sources import FETCHERS, Company

# python-telegram-bot numbers days 0=Sunday … 6=Saturday.
DAY_NUMBERS = {"sun": 0, "mon": 1, "tue": 2, "wed": 3, "thu": 4, "fri": 5, "sat": 6}


@dataclass(frozen=True)
class SearchConfig:
    keywords: tuple[str, ...]
    exclude: tuple[str, ...]
    locations: tuple[str, ...]
    countries: tuple[str, ...]
    companies: tuple[Company, ...]
    digest_time: dt.time
    digest_days: tuple[int, ...]
    followup_days: int
    max_jobs_per_digest: int

    @property
    def keyword_re(self) -> re.Pattern[str]:
        return _word_regex(self.keywords)

    @property
    def exclude_re(self) -> re.Pattern[str] | None:
        return _word_regex(self.exclude) if self.exclude else None


def _word_regex(words: tuple[str, ...]) -> re.Pattern[str]:
    alternatives = "|".join(re.escape(w.lower()) for w in words)
    return re.compile(rf"\b(?:{alternatives})\b", re.IGNORECASE)


@dataclass(frozen=True)
class Settings:
    telegram_token: str
    allowed_chat_ids: tuple[int, ...]
    db_path: Path
    search: SearchConfig


def _lower_tuple(values) -> tuple[str, ...]:
    return tuple(str(v).strip().lower() for v in values or [] if str(v).strip())


def load_search_config(path: str | os.PathLike[str]) -> SearchConfig:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}

    companies = []
    for item in data.get("companies") or []:
        company = Company(
            name=str(item["name"]), source=str(item["source"]).lower(), slug=item["slug"]
        )
        if company.source not in FETCHERS:
            raise ValueError(f"{company.name}: unknown source '{company.source}'")
        companies.append(company)

    keywords = _lower_tuple(data.get("keywords"))
    if not keywords:
        raise ValueError("At least one keyword is required")

    tz = ZoneInfo(data.get("timezone", "Asia/Jerusalem"))
    hour, minute = (int(x) for x in str(data.get("digest_time", "09:00")).split(":"))
    days = tuple(DAY_NUMBERS[d.lower()[:3]] for d in data.get("digest_days") or DAY_NUMBERS)

    return SearchConfig(
        keywords=keywords,
        exclude=_lower_tuple(data.get("exclude")),
        locations=_lower_tuple(data.get("locations")),
        countries=tuple(str(c).upper() for c in data.get("countries") or []),
        companies=tuple(companies),
        digest_time=dt.time(hour, minute, tzinfo=tz),
        digest_days=days,
        followup_days=int(data.get("followup_days", 7)),
        max_jobs_per_digest=int(data.get("max_jobs_per_digest", 20)),
    )


def load_settings(env: Mapping[str, str] = os.environ) -> Settings:
    token = env.get("TELEGRAM_TOKEN", "").strip()
    if not token:
        raise RuntimeError("TELEGRAM_TOKEN is not set")
    allowed = tuple(
        int(x) for x in env.get("ALLOWED_CHAT_IDS", "").replace(" ", "").split(",") if x
    )
    return Settings(
        telegram_token=token,
        allowed_chat_ids=allowed,
        db_path=Path(env.get("DB_PATH", "data/jobbot.sqlite3")),
        search=load_search_config(env.get("SEARCH_CONFIG", "config/search.yaml")),
    )

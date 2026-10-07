"""Telegram HTML rendering and parsing of the /applied command."""

from __future__ import annotations

import datetime as dt
import re
from html import escape

from .sources import Job
from .storage import Application, SavedJob

URL_RE = re.compile(r"https?://\S+")


def format_job(job: SavedJob | Job) -> str:
    title = escape(job.title)
    link = f'<a href="{escape(job.url, quote=True)}">{title}</a>' if job.url else f"<b>{title}</b>"
    return f"🏢 <b>{escape(job.company)}</b>\n{link}\n📍 {escape(job.location)}"


def format_application(app: Application, tz: dt.tzinfo) -> str:
    applied = app.applied_at.astimezone(tz).strftime("%d %b")
    due = app.followup_at.astimezone(tz).strftime("%d %b")
    role = f" — {escape(app.role)}" if app.role else ""
    line = f"<b>{escape(app.company)}</b>{role}\napplied {applied} · follow up {due}"
    if app.url:
        line += f' · <a href="{escape(app.url, quote=True)}">link</a>'
    return line


def parse_applied_args(text: str) -> tuple[str, str, str] | None:
    """Parse "/applied Company - Role https://url" into (company, role, url).

    Company and role are separated by " - ", " | " or " / "; role and URL are optional.
    """
    url_match = URL_RE.search(text)
    url = url_match.group(0) if url_match else ""
    rest = URL_RE.sub("", text).strip()
    if not rest:
        return None
    parts = re.split(r"\s+[-|/—]\s+", rest, maxsplit=1)
    company = parts[0].strip()
    role = parts[1].strip() if len(parts) > 1 else ""
    return company, role, url


def chunk_messages(blocks: list[str], limit: int = 4000) -> list[str]:
    """Join blocks with blank lines into messages under Telegram's size limit."""
    messages: list[str] = []
    current = ""
    for block in blocks:
        candidate = f"{current}\n\n{block}" if current else block
        if len(candidate) > limit and current:
            messages.append(current)
            current = block
        else:
            current = candidate
    if current:
        messages.append(current)
    return messages

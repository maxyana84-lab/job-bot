import datetime as dt

from app.formatting import chunk_messages, format_application, format_job, parse_applied_args
from app.storage import Application, SavedJob


def test_parse_applied_args():
    assert parse_applied_args("Wiz - Senior DevOps Engineer https://wiz.io/j/1") == (
        "Wiz",
        "Senior DevOps Engineer",
        "https://wiz.io/j/1",
    )
    assert parse_applied_args("Check Point | SRE") == ("Check Point", "SRE", "")
    assert parse_applied_args("Monday.com") == ("Monday.com", "", "")
    assert parse_applied_args("https://only-a-link.com") is None
    assert parse_applied_args("") is None


def test_format_job_escapes_html():
    job = SavedJob(1, "A&B", "<DevOps>", "Tel Aviv", "https://x?a=1&b=2")
    text = format_job(job)
    assert "A&amp;B" in text and "&lt;DevOps&gt;" in text
    assert 'href="https://x?a=1&amp;b=2"' in text


def test_format_application_uses_timezone():
    utc = dt.UTC
    app = Application(
        1,
        "Wiz",
        "SRE",
        "",
        dt.datetime(2026, 10, 1, 22, tzinfo=utc),
        dt.datetime(2026, 10, 8, 22, tzinfo=utc),
        "active",
    )
    israel = dt.timezone(dt.timedelta(hours=3))
    assert "applied 02 Oct" in format_application(app, israel)


def test_chunk_messages():
    blocks = ["x" * 1500] * 5
    messages = chunk_messages(blocks, limit=4000)
    assert len(messages) == 3
    assert all(len(m) <= 4000 for m in messages)

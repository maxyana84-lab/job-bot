import datetime as dt

from app.sources import Job
from app.storage import Storage, utcnow


def _job(job_id: str) -> Job:
    return Job(
        "greenhouse", "Acme", job_id, f"DevOps {job_id}", ("Tel Aviv",), f"https://x/{job_id}"
    )


def test_only_new_jobs_are_returned():
    db = Storage(":memory:")
    first = db.add_new_jobs([_job("1"), _job("2")])
    assert [j.title for j in first] == ["DevOps 1", "DevOps 2"]
    second = db.add_new_jobs([_job("2"), _job("3")])
    assert [j.title for j in second] == ["DevOps 3"]
    assert db.get_job(first[0].id).url == "https://x/1"
    assert db.stats()["jobs_seen"] == 3


def test_application_followup_lifecycle():
    db = Storage(":memory:")
    application = db.add_application("Wiz", "SRE", "https://wiz/1", followup_days=7)
    assert db.has_application_for_url("https://wiz/1")
    assert not db.has_application_for_url("")

    assert db.due_followups() == []  # not due yet
    in_8_days = utcnow() + dt.timedelta(days=8)
    assert [a.id for a in db.due_followups(in_8_days)] == [application.id]

    db.snooze(application.id, days=7)
    assert db.get_application(application.id).followup_at > utcnow() + dt.timedelta(days=6)

    db.close_application(application.id)
    assert db.active_applications() == []
    assert db.due_followups(in_8_days + dt.timedelta(days=30)) == []
    assert db.stats() == {"jobs_seen": 0, "active": 0, "closed": 1}


def test_persists_to_disk(tmp_path):
    path = tmp_path / "sub" / "jobs.sqlite3"
    db = Storage(path)
    db.add_new_jobs([_job("1")])
    db.close()
    assert Storage(path).add_new_jobs([_job("1")]) == []

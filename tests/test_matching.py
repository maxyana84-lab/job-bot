from pathlib import Path

import pytest

from app.config import load_search_config
from app.matching import filter_jobs, location_matches, title_matches
from app.sources import Job

CONFIG = load_search_config(Path(__file__).parent.parent / "config" / "search.yaml")


@pytest.mark.parametrize(
    "title",
    [
        "Senior DevOps Engineer",
        "Senior DevEx/DevOps Engineer",
        "Site Reliability Engineer, Traffic Infrastructure",
        "Senior Site Reliability Engineer (SRE)",
        "DevSecOps Engineer",
        "Cloud Engineer - AWS",
        "Platform Engineer",
    ],
)
def test_relevant_titles_match(title):
    assert title_matches(title, CONFIG)


@pytest.mark.parametrize(
    "title",
    [
        "Backend Engineer",
        "Account Executive",
        "DevOps Intern",
        "Director, DevOps",
        "Address Verification Specialist",  # contains "sre"-like letters but not the word
    ],
)
def test_irrelevant_titles_dont_match(title):
    assert not title_matches(title, CONFIG)


def _job(locations, country=""):
    return Job("greenhouse", "Acme", "1", "DevOps Engineer", tuple(locations), "https://x", country)


def test_locations():
    assert location_matches(_job(["Tel Aviv-Yafo, Tel Aviv District, Israel"]), CONFIG)
    assert location_matches(_job(["Herzliya"]), CONFIG)
    assert location_matches(_job(["Remote"], country="IL"), CONFIG)
    assert location_matches(_job(["London", "Tel Aviv"]), CONFIG)
    assert not location_matches(_job(["Lisbon, Portugal"]), CONFIG)
    assert not location_matches(_job(["Remote US"]), CONFIG)


def test_filter_jobs_sorts_and_filters():
    jobs = [
        Job("greenhouse", "Zeta", "1", "SRE", ("Tel Aviv",), "u1"),
        Job("greenhouse", "Alpha", "2", "DevOps Engineer", ("Haifa",), "u2"),
        Job("greenhouse", "Alpha", "3", "DevOps Engineer", ("Lisbon",), "u3"),
        Job("greenhouse", "Alpha", "4", "Product Manager", ("Tel Aviv",), "u4"),
    ]
    assert [j.job_id for j in filter_jobs(jobs, CONFIG)] == ["2", "1"]


def test_config_values():
    assert CONFIG.digest_days == (0, 1, 2, 3, 4)  # Sun–Thu
    assert CONFIG.digest_time.hour == 9
    assert len(CONFIG.companies) >= 5

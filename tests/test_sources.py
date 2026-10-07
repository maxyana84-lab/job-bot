import httpx

from app.sources import Company, fetch_all

GREENHOUSE = {
    "jobs": [
        {
            "id": 101,
            "title": "Senior DevOps Engineer",
            "location": {"name": "Tel Aviv-Yafo, Tel Aviv District, Israel"},
            "absolute_url": "https://job-boards.greenhouse.io/acme/jobs/101",
        }
    ]
}
LEVER = [
    {
        "id": "abc-123",
        "text": "Site Reliability Engineer",
        "categories": {"location": "Herzliya", "allLocations": ["Herzliya", "Remote"]},
        "hostedUrl": "https://jobs.lever.co/beta/abc-123",
        "country": "IL",
    }
]
ASHBY = {
    "jobs": [
        {
            "id": "x1",
            "title": "Platform Engineer",
            "location": "Tel Aviv",
            "secondaryLocations": [{"location": "London"}],
            "jobUrl": "https://jobs.ashbyhq.com/gamma/x1",
            "isListed": True,
        },
        {"id": "x2", "title": "Hidden", "location": "Tel Aviv", "isListed": False},
    ]
}


def handler(request: httpx.Request) -> httpx.Response:
    host, path = request.url.host, request.url.path
    if host == "boards-api.greenhouse.io" and path.endswith("/acme/jobs"):
        return httpx.Response(200, json=GREENHOUSE)
    if host == "api.lever.co" and path.endswith("/beta"):
        assert request.url.params["mode"] == "json"
        return httpx.Response(200, json=LEVER)
    if host == "api.ashbyhq.com" and path.endswith("/gamma"):
        return httpx.Response(200, json=ASHBY)
    return httpx.Response(404)


async def test_fetch_all_normalizes_every_source_and_reports_errors():
    companies = [
        Company("Acme", "greenhouse", "acme"),
        Company("Beta", "lever", "beta"),
        Company("Gamma", "ashby", "gamma"),
        Company("Broken", "greenhouse", "missing"),
    ]
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        jobs, errors = await fetch_all(client, companies)

    by_company = {j.company: j for j in jobs}
    assert set(by_company) == {"Acme", "Beta", "Gamma"}  # hidden Ashby job skipped

    acme = by_company["Acme"]
    assert acme.key == "greenhouse:Acme:101"
    assert "Israel" in acme.location

    beta = by_company["Beta"]
    assert beta.locations == ("Herzliya", "Remote") and beta.country == "IL"

    gamma = by_company["Gamma"]
    assert gamma.locations == ("Tel Aviv", "London")
    assert gamma.url.endswith("/x1")

    assert errors == {"Broken": "HTTPStatusError"}

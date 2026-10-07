from pathlib import Path

from app.config import Settings, load_search_config
from app.main import build_application

ROOT = Path(__file__).parent.parent


def test_application_wires_commands_and_daily_digest(tmp_path):
    settings = Settings(
        telegram_token="123:abc",
        allowed_chat_ids=(1,),
        db_path=tmp_path / "db.sqlite3",
        search=load_search_config(ROOT / "config" / "search.yaml"),
    )
    app = build_application(settings)
    commands = {cmd for h in app.handlers[0] if hasattr(h, "commands") for cmd in h.commands}
    assert {"jobs", "all", "applied", "followups", "companies", "stats"} <= commands
    assert [job.name for job in app.job_queue.jobs()] == ["daily_digest"]
    app.bot_data["storage"].close()

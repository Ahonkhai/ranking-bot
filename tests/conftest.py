import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rankbot import db, store  # noqa: E402

CHAT = -1001234567890


@pytest.fixture()
def fresh_db(tmp_path, monkeypatch):
    """A real SQLite file per test — the schema is part of what's under test."""
    path = tmp_path / "test.db"
    db.close()
    monkeypatch.setattr("rankbot.config.DB_PATH", str(path))
    db.connect(str(path))
    store.ensure_chat(CHAT, "Test Group")
    yield path
    db.close()

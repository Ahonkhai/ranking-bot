"""Where the database ends up.

Getting this wrong doesn't raise anything — it silently puts SQLite on the
container filesystem, and the board is empty again after every redeploy.
"""

import os

from rankbot import config, db


def resolve(db_path, legacy, mount, legacy_on_volume=True):
    return config.resolve_storage(db_path, legacy, mount,
                                  exists=lambda p: legacy_on_volume)


def test_without_a_mount_the_paths_are_left_alone():
    assert resolve("data.db", "data.json", None) == ("data.db", "data.json")


def test_a_path_already_on_the_mount_is_kept():
    db_path, legacy = resolve("/data/rankbot.db", "/data/data.json", "/data")
    assert db_path == "/data/rankbot.db"
    assert legacy == "/data/data.json"


def test_a_path_off_the_mount_is_moved_onto_it():
    """The Dockerfile bakes in /data, but the volume's mount path is chosen in
    the dashboard and may be anywhere."""
    db_path, legacy = resolve("/data/rankbot.db", "/data/data.json", "/mnt/store")
    assert db_path == os.path.join("/mnt/store", "rankbot.db")
    assert legacy == os.path.join("/mnt/store", "data.json")


def test_the_legacy_file_is_only_redirected_when_one_is_there():
    """DATA_FILE is read-only input. Pointing it at a copy shipped inside the
    image is a deliberate choice and must not be overridden."""
    _db, legacy = resolve("/data/rankbot.db", "/app/data.json", "/mnt/store",
                          legacy_on_volume=False)
    assert legacy == "/app/data.json"


def test_a_relative_default_is_moved_onto_the_mount():
    db_path, _ = resolve("data.db", "data.json", "/data")
    assert db_path == os.path.join("/data", "rankbot.db")


def test_a_nested_path_under_the_mount_is_respected():
    db_path, _ = resolve("/data/bots/rank.db", "/data/data.json", "/data")
    assert db_path == "/data/bots/rank.db"


def test_a_sibling_directory_is_not_mistaken_for_the_mount():
    """/database must not count as being inside /data."""
    db_path, _ = resolve("/database/rankbot.db", "/database/data.json", "/data")
    assert db_path == os.path.join("/data", "rankbot.db")


# ── the warning ──────────────────────────────────────────────────────────

def test_railway_without_a_volume_warns(monkeypatch):
    monkeypatch.setattr(config, "ON_RAILWAY", True)
    monkeypatch.setattr(config, "VOLUME_MOUNT", None)
    warning = db.storage_warning()
    assert warning and "No Railway Volume" in warning


def test_railway_with_a_volume_is_quiet(monkeypatch):
    monkeypatch.setattr(config, "ON_RAILWAY", True)
    monkeypatch.setattr(config, "VOLUME_MOUNT", "/data")
    assert db.storage_warning() is None


def test_running_locally_does_not_warn(monkeypatch):
    monkeypatch.setattr(config, "ON_RAILWAY", False)
    monkeypatch.setattr(config, "VOLUME_MOUNT", None)
    assert db.storage_warning() is None


def test_the_database_directory_is_created_on_connect(tmp_path, monkeypatch):
    nested = tmp_path / "does" / "not" / "exist" / "rankbot.db"
    db.close()
    monkeypatch.setattr(config, "DB_PATH", str(nested))
    try:
        db.connect(str(nested))
        assert nested.exists()
    finally:
        db.close()

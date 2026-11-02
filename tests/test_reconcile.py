import fcntl
import sqlite3

import pytest

from tools.reconcile import reconcile


def setup(path):
    with sqlite3.connect(path) as conn:
        conn.executescript("CREATE TABLE game_results(game_id INTEGER PRIMARY KEY,announcement_state TEXT,announcement_message_id INTEGER,delivery_error TEXT);"
                           "INSERT INTO game_results VALUES(1,'unknown',NULL,'uncertain');"
                           "CREATE TABLE schedule_occurrences(schedule_id INTEGER,occurrence_at INTEGER,status TEXT);"
                           "INSERT INTO schedule_occurrences VALUES(2,123,'unknown');")


def test_manual_confirmation_does_not_change_statistics(tmp_path):
    path = tmp_path / 'db.sqlite3'
    setup(path)
    reconcile(path, 'confirm-announcement', game_id=1, message_id=42)
    with sqlite3.connect(path) as conn:
        assert conn.execute('SELECT announcement_state,announcement_message_id FROM game_results').fetchone() == ('sent', 42)
    with pytest.raises(ValueError):
        reconcile(path, 'retry-announcement', game_id=1)


def test_reconciliation_requires_stopped_service(tmp_path):
    path = tmp_path / 'db.sqlite3'
    setup(path)
    with open(str(path) + '.lock', 'a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(RuntimeError):
            reconcile(path, 'retry-announcement', game_id=1)


def test_uncertain_schedule_release_is_explicit_and_conditional(tmp_path):
    path = tmp_path / 'db.sqlite3'
    setup(path)
    reconcile(path, 'release-schedule', schedule_id=2, occurrence=123)
    with pytest.raises(ValueError):
        reconcile(path, 'release-schedule', schedule_id=2, occurrence=123)

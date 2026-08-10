"""normalizer.py のDB操作・メインフローテスト"""

import os
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, call, patch

os.environ.setdefault("DB_HOST", "localhost")
os.environ.setdefault("DB_USER", "test")
os.environ.setdefault("DB_PASSWORD", "test")
os.environ.setdefault("DB_NAME", "test")

from normalizer import (
    COLLECTION_KEY,
    MAX_BACKOFF,
    MIN_BACKOFF,
    BACKOFF_STEP,
    cleanup_old_processed,
    fetch_unprocessed,
    mark_processed,
    update_schedule,
)


class TestFetchUnprocessed:
    """fetch_unprocessed のテスト"""

    def test_returns_rows(self):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
        conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        cursor.fetchall.return_value = [
            {"id": 1, "raw_json": '{"type": "x-mitre-tactic"}'},
            {"id": 2, "raw_json": '{"type": "attack-pattern"}'},
        ]
        result = fetch_unprocessed(conn)
        assert len(result) == 2

    def test_returns_empty_list(self):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
        conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        cursor.fetchall.return_value = []
        result = fetch_unprocessed(conn)
        assert result == []


class TestMarkProcessed:
    """mark_processed のテスト"""

    def test_marks_multiple_ids(self):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
        conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        mark_processed(conn, [1, 2, 3])
        cursor.executemany.assert_called_once()
        conn.commit.assert_called_once()

    def test_empty_ids_no_op(self):
        conn = MagicMock()
        mark_processed(conn, [])
        conn.commit.assert_not_called()


class TestCleanupOldProcessed:
    """cleanup_old_processed のテスト"""

    def test_deletes_old_records(self, capsys):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
        conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        cursor.rowcount = 10

        cleanup_old_processed(conn)
        conn.commit.assert_called_once()
        captured = capsys.readouterr()
        assert "10件" in captured.out

    def test_no_deletes_no_output(self, capsys):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
        conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        cursor.rowcount = 0

        cleanup_old_processed(conn)
        captured = capsys.readouterr()
        assert captured.out == ""


class TestUpdateSchedule:
    """update_schedule のテスト"""

    def _make_conn(self, current_backoff=None):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
        conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        if current_backoff is not None:
            cursor.fetchone.return_value = {"backoff_minutes": current_backoff}
        else:
            cursor.fetchone.return_value = None
        return conn, cursor

    def test_resets_backoff_on_changes(self):
        conn, cursor = self._make_conn(current_backoff=120)
        update_schedule(conn, had_changes=True)
        # backoff は MIN_BACKOFF にリセットされる
        execute_calls = cursor.execute.call_args_list
        # 最後の execute が INSERT ... ON DUPLICATE KEY UPDATE
        last_call_args = execute_calls[-1][0][1]
        # (COLLECTION_KEY, new_backoff, next_run, new_backoff, next_run)
        assert last_call_args[1] == MIN_BACKOFF

    def test_increases_backoff_on_no_changes(self):
        conn, cursor = self._make_conn(current_backoff=MIN_BACKOFF)
        update_schedule(conn, had_changes=False)
        execute_calls = cursor.execute.call_args_list
        last_call_args = execute_calls[-1][0][1]
        expected_backoff = MIN_BACKOFF + BACKOFF_STEP
        assert last_call_args[1] == expected_backoff

    def test_backoff_capped_at_max(self):
        conn, cursor = self._make_conn(current_backoff=MAX_BACKOFF)
        update_schedule(conn, had_changes=False)
        execute_calls = cursor.execute.call_args_list
        last_call_args = execute_calls[-1][0][1]
        assert last_call_args[1] == MAX_BACKOFF

"""collector.py のロジックテスト"""

import os
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

# 環境変数を先にセットしてから import する
os.environ.setdefault("DB_HOST", "localhost")
os.environ.setdefault("DB_USER", "test")
os.environ.setdefault("DB_PASSWORD", "test")
os.environ.setdefault("DB_NAME", "test")

from collector import has_excessive_backlog, should_skip


class TestShouldSkip:
    """should_skip のテスト"""

    def test_skip_when_next_run_at_is_future(self):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
        conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        future = datetime.now(timezone.utc) + timedelta(hours=1)
        cursor.fetchone.return_value = {"next_run_at": future.replace(tzinfo=None)}

        assert should_skip(conn) is True

    def test_no_skip_when_next_run_at_is_past(self):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
        conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        past = datetime.now(timezone.utc) - timedelta(hours=1)
        cursor.fetchone.return_value = {"next_run_at": past.replace(tzinfo=None)}

        assert should_skip(conn) is False

    def test_no_skip_when_row_is_none(self):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
        conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        cursor.fetchone.return_value = None

        assert should_skip(conn) is False

    def test_no_skip_when_next_run_at_is_null(self):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
        conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        cursor.fetchone.return_value = {"next_run_at": None}

        assert should_skip(conn) is False


class TestHasExcessiveBacklog:
    """has_excessive_backlog のテスト"""

    def _make_conn(self, fetch_results):
        """複数回の fetchone を返す mock conn を作る"""
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
        conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        cursor.fetchone.side_effect = fetch_results
        return conn

    def test_no_guard_when_no_cursor_row(self):
        conn = self._make_conn([None])
        assert has_excessive_backlog(conn) is False

    def test_no_guard_when_last_fetch_count_is_none(self):
        conn = self._make_conn([{"last_fetch_count": None}])
        assert has_excessive_backlog(conn) is False

    def test_excessive_when_backlog_exceeds_threshold(self):
        # last_fetch_count=100, backlog=200 → threshold=200, 200 >= 200 → True
        conn = self._make_conn(
            [
                {"last_fetch_count": 100},
                {"cnt": 200},
            ]
        )
        assert has_excessive_backlog(conn) is True

    def test_not_excessive_when_below_threshold(self):
        # last_fetch_count=100, backlog=150 → threshold=200, 150 < 200 → False
        conn = self._make_conn(
            [
                {"last_fetch_count": 100},
                {"cnt": 150},
            ]
        )
        assert has_excessive_backlog(conn) is False

    def test_exactly_at_threshold(self):
        # last_fetch_count=50, backlog=100 → threshold=100, 100 >= 100 → True
        conn = self._make_conn(
            [
                {"last_fetch_count": 50},
                {"cnt": 100},
            ]
        )
        assert has_excessive_backlog(conn) is True

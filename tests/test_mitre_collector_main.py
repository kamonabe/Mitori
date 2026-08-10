"""mitre/collector.py の main フロー・save_raw テスト"""

import json
import os
from unittest.mock import MagicMock, patch

os.environ.setdefault("DB_HOST", "localhost")
os.environ.setdefault("DB_USER", "test")
os.environ.setdefault("DB_PASSWORD", "test")
os.environ.setdefault("DB_NAME", "test")

from collector import main, save_raw


class TestSaveRaw:
    """save_raw のテスト"""

    def test_inserts_objects_and_updates_cursor(self):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
        conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        objects = [{"type": "x-mitre-tactic", "id": "tactic-1"}, {"type": "attack-pattern", "id": "tech-1"}]
        save_raw(conn, objects)

        # 2 INSERT for objects + 1 INSERT/UPDATE for cursor = 3 execute calls
        assert cursor.execute.call_count == 3
        conn.commit.assert_called_once()


class TestMain:
    """main フローテスト"""

    @patch("collector.get_conn")
    def test_db_connection_failure(self, mock_conn, capsys):
        import pymysql

        mock_conn.side_effect = pymysql.Error("connection refused")
        main()
        captured = capsys.readouterr()
        assert "DB接続失敗" in captured.out

    @patch("collector.has_excessive_backlog")
    @patch("collector.should_skip")
    @patch("collector.get_conn")
    def test_skip_when_next_run_not_reached(self, mock_conn, mock_skip, mock_backlog, capsys):
        mock_conn.return_value = MagicMock()
        mock_skip.return_value = True
        main()
        captured = capsys.readouterr()
        assert "Skip" in captured.out
        mock_backlog.assert_not_called()

    @patch("collector.has_excessive_backlog")
    @patch("collector.should_skip")
    @patch("collector.get_conn")
    def test_skip_when_excessive_backlog(self, mock_conn, mock_skip, mock_backlog, capsys):
        mock_conn.return_value = MagicMock()
        mock_skip.return_value = False
        mock_backlog.return_value = True
        main()
        captured = capsys.readouterr()
        assert "backlog" in captured.out.lower()

    @patch("collector.save_raw")
    @patch("collector.fetch_all")
    @patch("collector.has_excessive_backlog")
    @patch("collector.should_skip")
    @patch("collector.get_conn")
    def test_fetch_failure(self, mock_conn, mock_skip, mock_backlog, mock_fetch, mock_save, capsys):
        import requests

        mock_conn.return_value = MagicMock()
        mock_skip.return_value = False
        mock_backlog.return_value = False
        mock_fetch.side_effect = requests.exceptions.RequestException("network error")
        main()
        captured = capsys.readouterr()
        assert "TAXII API取得失敗" in captured.out
        mock_save.assert_not_called()

    @patch("collector.save_raw")
    @patch("collector.fetch_all")
    @patch("collector.has_excessive_backlog")
    @patch("collector.should_skip")
    @patch("collector.get_conn")
    def test_successful_flow(self, mock_conn, mock_skip, mock_backlog, mock_fetch, mock_save, capsys):
        mock_conn.return_value = MagicMock()
        mock_skip.return_value = False
        mock_backlog.return_value = False
        mock_fetch.return_value = [{"type": "x-mitre-tactic"}, {"type": "attack-pattern"}]
        main()
        captured = capsys.readouterr()
        assert "Fetched 2 objects" in captured.out
        assert "Done" in captured.out
        mock_save.assert_called_once()

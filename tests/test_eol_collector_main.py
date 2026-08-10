"""eol-watch/collector.py の main フローテスト"""

import importlib
import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

os.environ.setdefault("DB_HOST", "localhost")
os.environ.setdefault("DB_USER", "test")
os.environ.setdefault("DB_PASSWORD", "test")
os.environ.setdefault("DB_NAME", "test")

# eol_collector モジュールを明示的にロード
_eol_watch_dir = str(Path(__file__).resolve().parent.parent / "eol-watch")
if "eol_collector" not in sys.modules:
    _spec = importlib.util.spec_from_file_location("eol_collector", f"{_eol_watch_dir}/collector.py")
    eol_collector = importlib.util.module_from_spec(_spec)
    sys.modules["eol_collector"] = eol_collector
    _spec.loader.exec_module(eol_collector)
else:
    eol_collector = sys.modules["eol_collector"]


class TestPickTarget:
    """pick_target のテスト"""

    def test_returns_target_when_available(self):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
        conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        cursor.fetchone.return_value = {"id": 1, "product_slug": "python", "display_name": "Python", "status": "active", "consecutive_failures": 0}

        result = eol_collector.pick_target(conn)
        assert result["product_slug"] == "python"
        conn.commit.assert_called_once()

    def test_returns_none_when_no_target(self):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
        conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        cursor.fetchone.return_value = None

        result = eol_collector.pick_target(conn)
        assert result is None


class TestFetchEol:
    """fetch_eol のテスト"""

    @patch("eol_collector.requests.get")
    def test_success(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=MagicMock(return_value={"result": {"label": "Python", "releases": []}})
        )
        result = eol_collector.fetch_eol("python")
        assert result == {"label": "Python", "releases": []}

    @patch("eol_collector.requests.get")
    def test_non_200(self, mock_get, capsys):
        mock_get.return_value = MagicMock(status_code=404)
        result = eol_collector.fetch_eol("nonexistent")
        assert result is None
        captured = capsys.readouterr()
        assert "404" in captured.out

    @patch("eol_collector.requests.get")
    def test_request_exception(self, mock_get, capsys):
        import requests

        mock_get.side_effect = requests.RequestException("timeout")
        result = eol_collector.fetch_eol("python")
        assert result is None
        captured = capsys.readouterr()
        assert "request error" in captured.out


class TestMain:
    """main フローテスト"""

    @patch("eol_collector.get_conn")
    def test_db_connection_failure(self, mock_conn, capsys):
        import pymysql

        mock_conn.side_effect = pymysql.Error("connection refused")
        eol_collector.main()
        captured = capsys.readouterr()
        assert "DB接続失敗" in captured.out

    @patch("eol_collector.send_webhook")
    @patch("eol_collector.fetch_eol")
    @patch("eol_collector.pick_target")
    @patch("eol_collector.get_conn")
    def test_no_target_available(self, mock_conn, mock_pick, mock_fetch, mock_webhook, capsys):
        mock_conn.return_value = MagicMock()
        mock_pick.return_value = None
        eol_collector.main()
        captured = capsys.readouterr()
        assert "No target" in captured.out
        mock_fetch.assert_not_called()

    @patch("eol_collector.send_webhook")
    @patch("eol_collector.mark_failure")
    @patch("eol_collector.fetch_eol")
    @patch("eol_collector.pick_target")
    @patch("eol_collector.get_conn")
    def test_fetch_failure_marks_failure(self, mock_conn, mock_pick, mock_fetch, mock_mark, mock_webhook, capsys):
        mock_conn.return_value = MagicMock()
        mock_pick.return_value = {"id": 1, "product_slug": "test", "status": "active", "consecutive_failures": 0}
        mock_fetch.return_value = None
        eol_collector.main()
        mock_mark.assert_called_once()

    @patch("eol_collector.send_webhook")
    @patch("eol_collector.mark_success")
    @patch("eol_collector.save_snapshot")
    @patch("eol_collector.get_last_snapshot")
    @patch("eol_collector.fetch_eol")
    @patch("eol_collector.pick_target")
    @patch("eol_collector.get_conn")
    def test_successful_fetch_no_change(self, mock_conn, mock_pick, mock_fetch, mock_last, mock_save, mock_mark, mock_webhook, capsys):
        mock_conn.return_value = MagicMock()
        mock_pick.return_value = {"id": 1, "product_slug": "python", "status": "active", "consecutive_failures": 0}
        result_data = {"label": "Python", "releases": [{"label": "3.12", "eolFrom": "2028-10-01", "isMaintained": True}]}
        mock_fetch.return_value = result_data
        serialized = json.dumps(result_data, sort_keys=True, ensure_ascii=False)
        mock_last.return_value = serialized  # 同じ → 変更なし

        eol_collector.main()
        mock_save.assert_called_once()
        mock_mark.assert_called_once()
        # 変更通知はなし（summarize 通知のみ）
        assert mock_webhook.call_count == 1  # summarize の通知のみ

    @patch("eol_collector.send_webhook")
    @patch("eol_collector.mark_success")
    @patch("eol_collector.save_snapshot")
    @patch("eol_collector.get_last_snapshot")
    @patch("eol_collector.fetch_eol")
    @patch("eol_collector.pick_target")
    @patch("eol_collector.get_conn")
    def test_successful_fetch_with_change(self, mock_conn, mock_pick, mock_fetch, mock_last, mock_save, mock_mark, mock_webhook, capsys):
        mock_conn.return_value = MagicMock()
        mock_pick.return_value = {"id": 1, "product_slug": "python", "status": "active", "consecutive_failures": 0}
        result_data = {"label": "Python", "releases": [{"label": "3.12", "eolFrom": "2028-10-01", "isMaintained": True}]}
        mock_fetch.return_value = result_data
        mock_last.return_value = '{"old": "data"}'  # 異なる → 変更あり

        eol_collector.main()
        # summarize 通知 + 変更通知 = 2回
        assert mock_webhook.call_count == 2
        change_msg = mock_webhook.call_args_list[1][0][0]
        assert "変更を検知" in change_msg

"""eol-watch/collector.py のロジックテスト"""

import importlib
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

os.environ.setdefault("DB_HOST", "localhost")
os.environ.setdefault("DB_USER", "test")
os.environ.setdefault("DB_PASSWORD", "test")
os.environ.setdefault("DB_NAME", "test")

# eol-watch の collector を明示的に別名でロード（mitre/collector.py との名前衝突を回避）
_eol_watch_dir = str(Path(__file__).resolve().parent.parent / "eol-watch")
_spec = importlib.util.spec_from_file_location("eol_collector", f"{_eol_watch_dir}/collector.py")
eol_collector = importlib.util.module_from_spec(_spec)
sys.modules["eol_collector"] = eol_collector
_spec.loader.exec_module(eol_collector)

summarize = eol_collector.summarize
mark_failure = eol_collector.mark_failure
send_webhook = eol_collector.send_webhook
FAIL_THRESHOLD_NEW = eol_collector.FAIL_THRESHOLD_NEW
FAIL_THRESHOLD_EXISTING = eol_collector.FAIL_THRESHOLD_EXISTING


class TestSummarize:
    """summarize のテスト"""

    def test_basic_result(self):
        result = {
            "releases": [
                {"label": "3.12", "eolFrom": "2028-10-01", "isMaintained": True},
                {"label": "3.11", "eolFrom": "2027-10-01", "isMaintained": True},
            ]
        }
        output = summarize(result)
        assert "3.12" in output
        assert "2028-10-01" in output
        assert "3.11" in output

    def test_limits_to_5_releases(self):
        result = {
            "releases": [{"label": f"v{i}", "eolFrom": f"2030-0{i}-01", "isMaintained": True} for i in range(1, 8)]
        }
        output = summarize(result)
        lines = [l for l in output.split("\n") if l.strip()]
        assert len(lines) == 5

    def test_empty_releases(self):
        result = {"releases": []}
        output = summarize(result)
        assert output == ""

    def test_no_releases_key(self):
        result = {}
        output = summarize(result)
        assert output == ""


class TestMarkFailure:
    """mark_failure のステータス遷移テスト"""

    def _make_conn(self):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
        conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        return conn, cursor

    @patch("eol_collector.send_webhook")
    def test_pending_below_threshold_no_alert(self, mock_webhook):
        conn, cursor = self._make_conn()
        target = {
            "id": 1,
            "product_slug": "test",
            "status": "pending_validation",
            "consecutive_failures": FAIL_THRESHOLD_NEW - 2,
        }
        mark_failure(conn, target)
        mock_webhook.assert_not_called()

    @patch("eol_collector.send_webhook")
    def test_pending_at_threshold_marks_invalid(self, mock_webhook):
        conn, cursor = self._make_conn()
        target = {
            "id": 1,
            "product_slug": "nonexistent",
            "status": "pending_validation",
            "consecutive_failures": FAIL_THRESHOLD_NEW - 1,
        }
        mark_failure(conn, target)
        mock_webhook.assert_called_once()
        alert_text = mock_webhook.call_args[0][0]
        assert "nonexistent" in alert_text
        assert "除外" in alert_text

    @patch("eol_collector.send_webhook")
    def test_active_at_threshold_sends_warning(self, mock_webhook):
        conn, cursor = self._make_conn()
        target = {
            "id": 2,
            "product_slug": "python",
            "status": "active",
            "consecutive_failures": FAIL_THRESHOLD_EXISTING - 1,
        }
        mark_failure(conn, target)
        mock_webhook.assert_called_once()
        alert_text = mock_webhook.call_args[0][0]
        assert "python" in alert_text
        assert "失敗" in alert_text

    @patch("eol_collector.send_webhook")
    def test_active_below_threshold_no_alert(self, mock_webhook):
        conn, cursor = self._make_conn()
        target = {
            "id": 2,
            "product_slug": "python",
            "status": "active",
            "consecutive_failures": 1,
        }
        mark_failure(conn, target)
        mock_webhook.assert_not_called()


class TestSendWebhook:
    """send_webhook のテスト"""

    @patch("eol_collector.SLACK_WEBHOOK_URL", "")
    def test_skip_when_url_empty(self, capsys):
        send_webhook("test message")
        captured = capsys.readouterr()
        assert "スキップ" in captured.out

    @patch("eol_collector.SLACK_WEBHOOK_URL", "https://hooks.slack.com/test")
    @patch("eol_collector.requests.post")
    def test_sends_post_request(self, mock_post):
        mock_post.return_value = MagicMock(status_code=200)
        send_webhook("hello")
        mock_post.assert_called_once()

    @patch("eol_collector.SLACK_WEBHOOK_URL", "https://hooks.slack.com/test")
    @patch("eol_collector.requests.post")
    def test_handles_exception_gracefully(self, mock_post, capsys):
        import requests as req

        mock_post.side_effect = req.RequestException("timeout")
        send_webhook("hello")
        captured = capsys.readouterr()
        assert "failed" in captured.out

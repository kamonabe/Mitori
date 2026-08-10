"""notify_slack のテスト"""
import os
from unittest.mock import patch, MagicMock

os.environ.setdefault("DB_HOST", "localhost")
os.environ.setdefault("DB_USER", "test")
os.environ.setdefault("DB_PASSWORD", "test")
os.environ.setdefault("DB_NAME", "test")


class TestNotifySlack:
    """notify_slack のテスト"""

    @patch.dict(os.environ, {"SLACK_WEBHOOK_URL": ""})
    def test_skip_when_webhook_url_empty(self, capsys):
        # SLACK_WEBHOOK_URL を空にしてモジュールをリロード
        import importlib
        import normalizer
        importlib.reload(normalizer)

        events = [{"type": "technique", "action": "added", "external_id": "T1234", "name": "Test"}]
        normalizer.notify_slack(events)

        captured = capsys.readouterr()
        assert "スキップ" in captured.out

    @patch.dict(os.environ, {"SLACK_WEBHOOK_URL": "https://hooks.slack.com/test"})
    def test_sends_notification_on_events(self):
        import importlib
        import normalizer
        importlib.reload(normalizer)

        events = [
            {"type": "technique", "action": "added", "external_id": "T1234", "name": "New Technique"},
            {"type": "tactic", "action": "updated", "external_id": "TA0001", "name": "Initial Access"},
        ]

        with patch("normalizer.requests.post") as mock_post:
            mock_response = MagicMock()
            mock_response.raise_for_status = MagicMock()
            mock_post.return_value = mock_response

            normalizer.notify_slack(events)

            mock_post.assert_called_once()
            call_kwargs = mock_post.call_args
            payload = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
            assert "T1234" in payload["text"]
            assert "TA0001" in payload["text"]
            assert "新規追加" in payload["text"]
            assert "更新" in payload["text"]

    @patch.dict(os.environ, {"SLACK_WEBHOOK_URL": "https://hooks.slack.com/test"})
    def test_no_call_when_events_empty(self):
        import importlib
        import normalizer
        importlib.reload(normalizer)

        with patch("normalizer.requests.post") as mock_post:
            normalizer.notify_slack([])
            mock_post.assert_not_called()

    @patch.dict(os.environ, {"SLACK_WEBHOOK_URL": "https://hooks.slack.com/test"})
    def test_handles_request_exception_gracefully(self, capsys):
        import importlib
        import requests
        import normalizer
        importlib.reload(normalizer)

        events = [{"type": "technique", "action": "added", "external_id": "T9999", "name": "Fail"}]

        with patch("normalizer.requests.post", side_effect=requests.RequestException("timeout")):
            # 例外が上がらないことを確認
            normalizer.notify_slack(events)

        captured = capsys.readouterr()
        assert "失敗" in captured.out

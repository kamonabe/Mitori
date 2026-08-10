"""lifecycle_notify.py のロジックテスト"""

import os
from datetime import date
from unittest.mock import MagicMock, patch

os.environ.setdefault("DB_HOST", "localhost")
os.environ.setdefault("DB_USER", "test")
os.environ.setdefault("DB_PASSWORD", "test")
os.environ.setdefault("DB_NAME", "test")


class TestBuildMessage:
    """build_message のテスト"""

    def test_single_item(self):
        from lifecycle_notify import build_message

        items = [
            {
                "product_slug": "python",
                "version": "3.11",
                "description": "CronJobベースイメージ",
                "eol_date": "2027-10-01",
            }
        ]

        with patch("lifecycle_notify.date") as mock_date:
            mock_date.today.return_value = date(2027, 7, 1)
            mock_date.side_effect = lambda *args, **kw: date(*args, **kw)
            result = build_message(items)

        assert "ライフサイクル通知" in result
        assert "1件" in result
        assert "python" in result
        assert "3.11" in result
        assert "残り92日" in result
        assert "CronJobベースイメージ" in result
        assert "my_components" in result

    def test_multiple_items(self):
        from lifecycle_notify import build_message

        items = [
            {"product_slug": "python", "version": "3.11", "description": "", "eol_date": "2027-10-01"},
            {"product_slug": "mariadb", "version": "11.8", "description": "DB", "eol_date": "2027-12-01"},
        ]

        with patch("lifecycle_notify.date") as mock_date:
            mock_date.today.return_value = date(2027, 7, 1)
            mock_date.side_effect = lambda *args, **kw: date(*args, **kw)
            result = build_message(items)

        assert "2件" in result
        assert "python" in result
        assert "mariadb" in result
        # description が空の場合、角括弧は表示されない
        assert "[DB]" in result
        lines = result.split("\n")
        # ヘッダー + 2件 + 空行 + フッター = 5行
        assert len(lines) == 5

    def test_no_description_omits_brackets(self):
        from lifecycle_notify import build_message

        items = [
            {"product_slug": "nodejs", "version": "20", "description": "", "eol_date": "2028-04-30"},
        ]

        with patch("lifecycle_notify.date") as mock_date:
            mock_date.today.return_value = date(2027, 1, 1)
            mock_date.side_effect = lambda *args, **kw: date(*args, **kw)
            result = build_message(items)

        # description が空なら [] が出ない
        assert "[]" not in result

    def test_eol_already_passed(self):
        """EOLが過去の場合、残り日数がマイナスになる"""
        from lifecycle_notify import build_message

        items = [
            {"product_slug": "python", "version": "3.9", "description": "", "eol_date": "2025-10-01"},
        ]

        with patch("lifecycle_notify.date") as mock_date:
            mock_date.today.return_value = date(2026, 1, 1)
            mock_date.side_effect = lambda *args, **kw: date(*args, **kw)
            result = build_message(items)

        assert "残り-92日" in result


class TestSendWebhook:
    """send_webhook のテスト"""

    @patch.dict(os.environ, {"SLACK_WEBHOOK_URL": ""})
    def test_skip_when_url_empty(self, capsys):
        import importlib

        import lifecycle_notify

        importlib.reload(lifecycle_notify)

        lifecycle_notify.send_webhook("test message")

        captured = capsys.readouterr()
        assert "スキップ" in captured.out

    @patch.dict(os.environ, {"SLACK_WEBHOOK_URL": "https://hooks.slack.com/test"})
    def test_sends_post_request(self):
        import importlib

        import lifecycle_notify

        importlib.reload(lifecycle_notify)

        with patch("lifecycle_notify.requests.post") as mock_post:
            mock_post.return_value = MagicMock(status_code=200)
            lifecycle_notify.send_webhook("hello")

            mock_post.assert_called_once()
            call_kwargs = mock_post.call_args
            assert call_kwargs.kwargs["json"] == {"text": "hello"}
            assert call_kwargs.kwargs["timeout"] == 10

    @patch.dict(os.environ, {"SLACK_WEBHOOK_URL": "https://hooks.slack.com/test"})
    def test_handles_request_exception_gracefully(self, capsys):
        import importlib

        import lifecycle_notify
        import requests as req

        importlib.reload(lifecycle_notify)

        with patch("lifecycle_notify.requests.post", side_effect=req.RequestException("timeout")):
            lifecycle_notify.send_webhook("hello")

        captured = capsys.readouterr()
        assert "失敗" in captured.out

    @patch.dict(os.environ, {"SLACK_WEBHOOK_URL": "https://hooks.slack.com/test"})
    def test_logs_non_200_response(self, capsys):
        import importlib

        import lifecycle_notify

        importlib.reload(lifecycle_notify)

        with patch("lifecycle_notify.requests.post") as mock_post:
            mock_post.return_value = MagicMock(status_code=500, text="Internal Server Error")
            lifecycle_notify.send_webhook("hello")

        captured = capsys.readouterr()
        assert "500" in captured.out


class TestMainDeduplication:
    """main() の重複除去ロジックのテスト"""

    @patch.dict(
        os.environ,
        {
            "DB_HOST": "localhost",
            "DB_USER": "t",
            "DB_PASSWORD": "t",
            "DB_NAME": "t",
            "SLACK_WEBHOOK_URL": "https://hooks.slack.com/test",
        },
    )
    def test_deduplicates_same_slug_version(self, capsys):
        import importlib

        import lifecycle_notify

        importlib.reload(lifecycle_notify)

        # DB から重複を含む結果が返ってきた想定
        duplicate_items = [
            {"product_slug": "python", "version": "3.12", "description": "", "eol_date": "2028-10-01"},
            {"product_slug": "python", "version": "3.12", "description": "", "eol_date": "2028-10-01"},
            {"product_slug": "mariadb", "version": "11.8", "description": "DB", "eol_date": "2027-12-01"},
        ]

        with (
            patch.object(lifecycle_notify, "get_conn") as mock_conn,
            patch.object(lifecycle_notify, "fetch_approaching_eol", return_value=duplicate_items),
            patch.object(lifecycle_notify, "send_webhook") as mock_webhook,
        ):
            mock_conn.return_value = MagicMock()

            lifecycle_notify.main()

            # send_webhook が呼ばれたメッセージに「2件」とある（3件ではなく重複除去後の2件）
            mock_webhook.assert_called_once()
            message = mock_webhook.call_args[0][0]
            assert "2件" in message

    @patch.dict(
        os.environ,
        {"DB_HOST": "localhost", "DB_USER": "t", "DB_PASSWORD": "t", "DB_NAME": "t", "SLACK_WEBHOOK_URL": ""},
    )
    def test_no_notification_when_no_items(self, capsys):
        import importlib

        import lifecycle_notify

        importlib.reload(lifecycle_notify)

        with (
            patch.object(lifecycle_notify, "get_conn") as mock_conn,
            patch.object(lifecycle_notify, "fetch_approaching_eol", return_value=[]),
        ):
            mock_conn.return_value = MagicMock()

            lifecycle_notify.main()

        captured = capsys.readouterr()
        assert "通知対象なし" in captured.out

"""kev_notify.py のテスト"""

import os
from unittest.mock import MagicMock, patch

os.environ.setdefault("DB_HOST", "localhost")
os.environ.setdefault("DB_USER", "test")
os.environ.setdefault("DB_PASSWORD", "test")
os.environ.setdefault("DB_NAME", "test")

from kev_notify import main, send_slack_notification


class TestSendSlackNotification:
    """Slack 通知メッセージ組み立てテスト"""

    @patch("kev_notify.SLACK_WEBHOOK_URL", "https://hooks.slack.com/test")
    @patch("kev_notify.requests.post")
    def test_single_entry(self, mock_post):
        entries = [
            {
                "cve_id": "CVE-2026-0001",
                "date_added": "2026-08-11",
                "vendor": "Cisco",
                "product": "ASA",
                "short_description": "Heap overflow vulnerability",
                "due_date": "2026-08-14",
                "known_ransomware_use": "Unknown",
            }
        ]
        send_slack_notification(entries)
        mock_post.assert_called_once()
        payload = mock_post.call_args[1]["json"]
        assert "KEV カタログ新規追加: 1件" in payload["text"]
        assert "CVE-2026-0001" in payload["text"]
        assert "Cisco" in payload["text"]
        assert "対処期限: 2026-08-14" in payload["text"]

    @patch("kev_notify.SLACK_WEBHOOK_URL", "https://hooks.slack.com/test")
    @patch("kev_notify.NOTIFY_MAX_ITEMS", 2)
    @patch("kev_notify.requests.post")
    def test_truncation_over_max_items(self, mock_post):
        entries = [
            {
                "cve_id": f"CVE-2026-000{i}",
                "date_added": "2026-08-11",
                "vendor": "Vendor",
                "product": "Product",
                "short_description": "desc",
                "due_date": "2026-08-14",
                "known_ransomware_use": "Unknown",
            }
            for i in range(5)
        ]
        send_slack_notification(entries)
        mock_post.assert_called_once()
        payload = mock_post.call_args[1]["json"]
        assert "KEV カタログ新規追加: 5件" in payload["text"]
        assert "他 3 件" in payload["text"]

    @patch("kev_notify.SLACK_WEBHOOK_URL", "")
    @patch("kev_notify.requests.post")
    def test_skip_when_no_webhook(self, mock_post):
        entries = [
            {
                "cve_id": "CVE-2026-0001",
                "date_added": "2026-08-11",
                "vendor": "V",
                "product": "P",
                "short_description": "d",
                "due_date": None,
                "known_ransomware_use": "Unknown",
            }
        ]
        send_slack_notification(entries)
        mock_post.assert_not_called()

    @patch("kev_notify.SLACK_WEBHOOK_URL", "https://hooks.slack.com/test")
    @patch("kev_notify.requests.post")
    def test_due_date_none_shows_unset(self, mock_post):
        entries = [
            {
                "cve_id": "CVE-2026-0001",
                "date_added": "2026-08-11",
                "vendor": "V",
                "product": "P",
                "short_description": "d",
                "due_date": None,
                "known_ransomware_use": "Known",
            }
        ]
        send_slack_notification(entries)
        payload = mock_post.call_args[1]["json"]
        assert "対処期限: 未設定" in payload["text"]
        assert "ランサムウェア悪用: Known" in payload["text"]

    @patch("kev_notify.SLACK_WEBHOOK_URL", "https://hooks.slack.com/test")
    @patch("kev_notify.requests.post")
    def test_notification_failure_does_not_raise(self, mock_post):
        import requests

        mock_post.side_effect = requests.ConnectionError("network error")
        entries = [
            {
                "cve_id": "CVE-2026-0001",
                "date_added": "2026-08-11",
                "vendor": "V",
                "product": "P",
                "short_description": "d",
                "due_date": "2026-08-14",
                "known_ransomware_use": "Unknown",
            }
        ]
        # Should not raise
        send_slack_notification(entries)


class TestMain:
    """main() フローテスト"""

    @patch("kev_notify.get_conn")
    def test_db_connection_failure(self, mock_conn, capsys):
        import pymysql

        mock_conn.side_effect = pymysql.Error("connection refused")
        main()
        captured = capsys.readouterr()
        assert "DB接続失敗" in captured.out

    @patch("kev_notify.get_conn")
    def test_no_unnotified_entries(self, mock_conn, capsys):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
        conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        # ensure_tables は何もしない
        # get_unnotified_entries → 空リスト
        cursor.fetchall.return_value = []
        mock_conn.return_value = conn

        main()
        captured = capsys.readouterr()
        assert "未通知エントリなし" in captured.out

    @patch("kev_notify.send_slack_notification")
    @patch("kev_notify.mark_notified")
    @patch("kev_notify.get_conn")
    def test_initial_load_skips_notification(self, mock_conn, mock_mark, mock_slack, capsys):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
        conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        # get_unnotified_entries: 100件の未通知
        unnotified = [{"cve_id": f"CVE-{i}"} for i in range(100)]
        cursor.fetchall.return_value = unnotified
        # is_first_run: notify_log が空 → cnt=0
        cursor.fetchone.return_value = {"cnt": 0}
        mock_conn.return_value = conn

        main()
        captured = capsys.readouterr()
        assert "初回ロード検知" in captured.out
        # Slack通知は呼ばれない
        mock_slack.assert_not_called()
        # mark_notified は "initial_load" タイプで呼ばれる
        mock_mark.assert_called_once()
        kwargs = mock_mark.call_args[1]
        assert kwargs["notification_type"] == "initial_load"

    @patch("kev_notify.send_slack_notification")
    @patch("kev_notify.mark_notified")
    @patch("kev_notify.get_conn")
    def test_normal_notification(self, mock_conn, mock_mark, mock_slack, capsys):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
        conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        # get_unnotified_entries: 3件
        unnotified = [
            {
                "cve_id": f"CVE-2026-000{i}",
                "vendor": "V",
                "product": "P",
                "short_description": "d",
                "date_added": "2026-08-11",
                "due_date": "2026-08-14",
                "known_ransomware_use": "Unknown",
                "vulnerability_name": "Test",
            }
            for i in range(3)
        ]
        cursor.fetchall.return_value = unnotified
        # is_first_run: notify_log にレコードあり → cnt=50
        cursor.fetchone.return_value = {"cnt": 50}
        mock_conn.return_value = conn

        main()
        captured = capsys.readouterr()
        assert "3件を通知済みとして記録" in captured.out
        mock_slack.assert_called_once_with(unnotified)
        mock_mark.assert_called_once()
        kwargs = mock_mark.call_args[1]
        assert kwargs["notification_type"] == "new_kev"

    @patch("kev_notify.send_slack_notification")
    @patch("kev_notify.mark_notified")
    @patch("kev_notify.get_conn")
    def test_first_run_below_threshold_still_notifies(self, mock_conn, mock_mark, mock_slack, capsys):
        """初回実行でもエントリ数が閾値以下なら通常通知する."""
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
        conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        # 閾値(50)以下の件数
        unnotified = [
            {
                "cve_id": f"CVE-2026-000{i}",
                "vendor": "V",
                "product": "P",
                "short_description": "d",
                "date_added": "2026-08-11",
                "due_date": "2026-08-14",
                "known_ransomware_use": "Unknown",
                "vulnerability_name": "Test",
            }
            for i in range(5)
        ]
        cursor.fetchall.return_value = unnotified
        # is_first_run: notify_log が空 → cnt=0
        cursor.fetchone.return_value = {"cnt": 0}
        mock_conn.return_value = conn

        main()
        # 閾値以下なので通常通知
        mock_slack.assert_called_once_with(unnotified)
        mock_mark.assert_called_once()
        kwargs = mock_mark.call_args[1]
        assert kwargs["notification_type"] == "new_kev"

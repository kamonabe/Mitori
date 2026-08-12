"""cve_kev_alert.py のテスト"""

import os
from unittest.mock import MagicMock, patch

os.environ.setdefault("DB_HOST", "localhost")
os.environ.setdefault("DB_USER", "test")
os.environ.setdefault("DB_PASSWORD", "test")
os.environ.setdefault("DB_NAME", "test")

from cve_kev_alert import main, send_slack_notification


class TestSendSlackNotification:
    """Slack 通知メッセージ組み立てテスト"""

    @patch("cve_kev_alert.SLACK_WEBHOOK_URL", "https://hooks.slack.com/test")
    @patch("cve_kev_alert.requests.post")
    def test_single_alert(self, mock_post):
        alerts = [
            {
                "cve_id": "CVE-2025-46599",
                "severity": "HIGH",
                "component": "k3s",
                "summary": "kubelet configuration exposes credentials",
                "fixed_version": "1.32.5+k3s1",
                "date_added": "2025-12-01",
                "due_date": "2025-12-22",
                "known_ransomware_use": "Known",
            }
        ]
        send_slack_notification(alerts)
        mock_post.assert_called_once()
        payload = mock_post.call_args[1]["json"]
        text = payload["text"]
        assert "自環境CVE × KEV 該当: 1件" in text
        assert "CVE-2025-46599" in text
        assert "HIGH" in text
        assert "k3s" in text
        assert "修正版: 1.32.5+k3s1" in text
        assert "ランサムウェア悪用: Known" in text

    @patch("cve_kev_alert.SLACK_WEBHOOK_URL", "https://hooks.slack.com/test")
    @patch("cve_kev_alert.NOTIFY_MAX_ITEMS", 2)
    @patch("cve_kev_alert.requests.post")
    def test_truncation_over_max_items(self, mock_post):
        alerts = [
            {
                "cve_id": f"CVE-2026-000{i}",
                "severity": "CRITICAL",
                "component": f"pkg{i}",
                "summary": "desc",
                "fixed_version": None,
                "date_added": "2026-08-11",
                "due_date": "2026-08-14",
                "known_ransomware_use": "Unknown",
            }
            for i in range(4)
        ]
        send_slack_notification(alerts)
        payload = mock_post.call_args[1]["json"]
        assert "自環境CVE × KEV 該当: 4件" in payload["text"]
        assert "他 2 件" in payload["text"]

    @patch("cve_kev_alert.SLACK_WEBHOOK_URL", "")
    @patch("cve_kev_alert.requests.post")
    def test_skip_when_no_webhook(self, mock_post):
        alerts = [
            {
                "cve_id": "CVE-2026-0001",
                "severity": "HIGH",
                "component": "pkg",
                "summary": "d",
                "fixed_version": None,
                "date_added": "2026-08-11",
                "due_date": None,
                "known_ransomware_use": "Unknown",
            }
        ]
        send_slack_notification(alerts)
        mock_post.assert_not_called()

    @patch("cve_kev_alert.SLACK_WEBHOOK_URL", "https://hooks.slack.com/test")
    @patch("cve_kev_alert.requests.post")
    def test_no_fixed_version_omitted(self, mock_post):
        """fixed_version が None なら '修正版:' 行を出力しない."""
        alerts = [
            {
                "cve_id": "CVE-2026-0001",
                "severity": "CRITICAL",
                "component": "pkg",
                "summary": "test",
                "fixed_version": None,
                "date_added": "2026-08-11",
                "due_date": "2026-08-14",
                "known_ransomware_use": "Unknown",
            }
        ]
        send_slack_notification(alerts)
        payload = mock_post.call_args[1]["json"]
        assert "修正版:" not in payload["text"]

    @patch("cve_kev_alert.SLACK_WEBHOOK_URL", "https://hooks.slack.com/test")
    @patch("cve_kev_alert.requests.post")
    def test_due_date_none_shows_unset(self, mock_post):
        alerts = [
            {
                "cve_id": "CVE-2026-0001",
                "severity": "HIGH",
                "component": "pkg",
                "summary": "test",
                "fixed_version": "2.0.0",
                "date_added": "2026-08-11",
                "due_date": None,
                "known_ransomware_use": "Unknown",
            }
        ]
        send_slack_notification(alerts)
        payload = mock_post.call_args[1]["json"]
        assert "対処期限: 未設定" in payload["text"]

    @patch("cve_kev_alert.SLACK_WEBHOOK_URL", "https://hooks.slack.com/test")
    @patch("cve_kev_alert.requests.post")
    def test_notification_failure_does_not_raise(self, mock_post):
        import requests

        mock_post.side_effect = requests.ConnectionError("network")
        alerts = [
            {
                "cve_id": "CVE-2026-0001",
                "severity": "HIGH",
                "component": "pkg",
                "summary": "test",
                "fixed_version": None,
                "date_added": "2026-08-11",
                "due_date": "2026-08-14",
                "known_ransomware_use": "Unknown",
            }
        ]
        # Should not raise
        send_slack_notification(alerts)


class TestMain:
    """main() フローテスト"""

    @patch("cve_kev_alert.get_conn")
    def test_db_connection_failure(self, mock_conn, capsys):
        import pymysql

        mock_conn.side_effect = pymysql.Error("connection refused")
        main()
        captured = capsys.readouterr()
        assert "DB接続失敗" in captured.out

    @patch("cve_kev_alert.get_conn")
    def test_no_unnotified_alerts(self, mock_conn, capsys):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
        conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        cursor.fetchall.return_value = []
        mock_conn.return_value = conn

        main()
        captured = capsys.readouterr()
        assert "該当なし" in captured.out

    @patch("cve_kev_alert.send_slack_notification")
    @patch("cve_kev_alert.mark_notified")
    @patch("cve_kev_alert.get_conn")
    def test_alerts_found_and_notified(self, mock_conn, mock_mark, mock_slack, capsys):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
        conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        alerts = [
            {
                "cve_id": "CVE-2026-0001",
                "component": "k3s",
                "category": "runtime",
                "severity": "HIGH",
                "summary": "test vuln",
                "fixed_version": "2.0.0",
                "vendor": "K3s",
                "product": "k3s",
                "date_added": "2026-08-11",
                "due_date": "2026-08-14",
                "known_ransomware_use": "Unknown",
            }
        ]
        cursor.fetchall.return_value = alerts
        mock_conn.return_value = conn

        main()
        captured = capsys.readouterr()
        assert "1件" in captured.out
        mock_slack.assert_called_once_with(alerts)
        mock_mark.assert_called_once_with(conn, alerts)

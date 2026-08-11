"""cve_watch.py の通知フィルタリングロジックテスト"""

import os
from unittest.mock import MagicMock, patch

os.environ.setdefault("DB_HOST", "localhost")
os.environ.setdefault("DB_USER", "test")
os.environ.setdefault("DB_PASSWORD", "test")
os.environ.setdefault("DB_NAME", "test")

from cve_watch import (
    is_first_scan_for_component,
    send_slack_notification,
    should_notify,
)


class TestShouldNotify:
    """should_notify の通知フィルタテスト"""

    def test_high_severity_recent_cve(self):
        """HIGH重大度・最近のCVEは通知する"""
        notify, reason = should_notify("HIGH", "2026-08-01T00:00:00Z")
        assert notify is True
        assert reason is None

    def test_critical_severity_always_notifies(self):
        """CRITICALは常に通知する"""
        notify, reason = should_notify("CRITICAL", "2026-08-01T00:00:00Z")
        assert notify is True
        assert reason is None

    @patch("cve_watch.CVE_NOTIFY_MIN_SEVERITY", "HIGH")
    def test_medium_below_threshold(self):
        """閾値HIGHの場合、MEDIUMは通知しない"""
        notify, reason = should_notify("MEDIUM", "2026-08-01T00:00:00Z")
        assert notify is False
        assert reason == "severity_below_threshold"

    @patch("cve_watch.CVE_NOTIFY_MIN_SEVERITY", "HIGH")
    def test_low_below_threshold(self):
        """閾値HIGHの場合、LOWは通知しない"""
        notify, reason = should_notify("LOW", "2026-08-01T00:00:00Z")
        assert notify is False
        assert reason == "severity_below_threshold"

    @patch("cve_watch.CVE_NOTIFY_MIN_SEVERITY", "HIGH")
    def test_unknown_below_threshold(self):
        """閾値HIGHの場合、UNKNOWNは通知しない"""
        notify, reason = should_notify("UNKNOWN", "2026-08-01T00:00:00Z")
        assert notify is False
        assert reason == "severity_below_threshold"

    @patch("cve_watch.CVE_NOTIFY_MIN_SEVERITY", "HIGH")
    def test_high_meets_threshold(self):
        """閾値HIGHの場合、HIGHは通知する"""
        notify, reason = should_notify("HIGH", "2026-08-01T00:00:00Z")
        assert notify is True
        assert reason is None

    @patch("cve_watch.CVE_STALE_DAYS", 365)
    def test_old_cve_skipped(self):
        """1年以上前のCVEは通知しない"""
        notify, reason = should_notify("HIGH", "2020-01-15T00:00:00Z")
        assert notify is False
        assert reason == "stale_cve"

    @patch("cve_watch.CVE_STALE_DAYS", 365)
    def test_recent_cve_not_skipped(self):
        """最近のCVEは通知する"""
        notify, reason = should_notify("HIGH", "2026-07-01T00:00:00Z")
        assert notify is True
        assert reason is None

    def test_no_published_date_passes(self):
        """published日なしの場合はフィルタしない"""
        notify, reason = should_notify("HIGH", None)
        assert notify is True
        assert reason is None

    def test_empty_published_date_passes(self):
        """published日が空文字の場合はフィルタしない"""
        notify, reason = should_notify("HIGH", "")
        assert notify is True
        assert reason is None

    def test_invalid_date_format_passes(self):
        """パース不能な日付はフィルタしない"""
        notify, reason = should_notify("HIGH", "not-a-date")
        assert notify is True
        assert reason is None

    @patch("cve_watch.CVE_STALE_DAYS", 0)
    def test_stale_days_zero_disables_filter(self):
        """CVE_STALE_DAYS=0の場合は日付フィルタ無効"""
        notify, reason = should_notify("HIGH", "2015-01-01T00:00:00Z")
        assert notify is True
        assert reason is None

    @patch("cve_watch.CVE_NOTIFY_MIN_SEVERITY", "LOW")
    def test_default_threshold_allows_all(self):
        """デフォルト閾値LOWでは全重大度が通知対象"""
        for sev in ["LOW", "MEDIUM", "HIGH", "CRITICAL"]:
            notify, _ = should_notify(sev, "2026-08-01T00:00:00Z")
            assert notify is True, f"{sev} should be notified with LOW threshold"


class TestIsFirstScanForComponent:
    """is_first_scan_for_component のテスト"""

    def test_returns_true_when_no_entries(self):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
        conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        cursor.fetchone.return_value = {"cnt": 0}

        assert is_first_scan_for_component(conn, "pkg", "container") is True

    def test_returns_false_when_entries_exist(self):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
        conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        cursor.fetchone.return_value = {"cnt": 5}

        assert is_first_scan_for_component(conn, "pkg", "container") is False


class TestBulkInitialScanNotification:
    """初回スキャン時のサマリ通知テスト"""

    @patch("cve_watch.SLACK_WEBHOOK_URL", "https://hooks.slack.com/test")
    @patch("cve_watch.requests.post")
    def test_bulk_scan_notification_format(self, mock_post):
        """初回スキャンのサマリ通知が正しいフォーマットで送信される"""
        notifications = [
            {
                "type": "bulk_initial_scan",
                "component": "github.com/example/pkg",
                "total_count": 15,
                "severity_breakdown": {"HIGH": 3, "MEDIUM": 8, "LOW": 4},
            }
        ]
        send_slack_notification(notifications)
        mock_post.assert_called_once()
        payload = mock_post.call_args[1]["json"]
        assert "初回スキャン完了" in payload["text"]
        assert "15件のCVEを記録" in payload["text"]
        assert "HIGH:3" in payload["text"]
        assert "次回以降は差分のみ" in payload["text"]

    @patch("cve_watch.SLACK_WEBHOOK_URL", "https://hooks.slack.com/test")
    @patch("cve_watch.requests.post")
    def test_bulk_scan_with_new_cve_combined(self, mock_post):
        """初回スキャン通知と新規CVE通知が混在する場合"""
        notifications = [
            {
                "type": "bulk_initial_scan",
                "component": "pkg-a",
                "total_count": 5,
                "severity_breakdown": {"HIGH": 2, "MEDIUM": 3},
            },
            {
                "type": "new_cve",
                "osv_id": "GHSA-new-1",
                "cve_id": "CVE-2026-1111",
                "component": "pkg-b",
                "severity": "CRITICAL",
                "summary": "New vuln",
                "fixed_version": "3.0.0",
            },
        ]
        send_slack_notification(notifications)
        mock_post.assert_called_once()
        payload = mock_post.call_args[1]["json"]
        assert "初回スキャン完了" in payload["text"]
        assert "新規CVE検知" in payload["text"]

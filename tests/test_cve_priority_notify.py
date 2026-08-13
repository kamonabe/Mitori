"""cve_priority_notify.py のテスト"""

import os
from decimal import Decimal
from unittest.mock import MagicMock, patch

os.environ.setdefault("DB_HOST", "localhost")
os.environ.setdefault("DB_USER", "test")
os.environ.setdefault("DB_PASSWORD", "test")
os.environ.setdefault("DB_NAME", "test")

from cve_priority_notify import (
    build_reason,
    determine_priority,
    main,
    send_slack_notification,
)


class TestDeterminePriority:
    """優先度判定ロジックテスト"""

    def test_critical_kev_and_high_epss(self):
        """KEV掲載 + EPSS >= 0.7 → critical"""
        result = determine_priority(Decimal("0.85"), "HIGH", is_in_kev=True)
        assert result == "critical"

    def test_high_kev_only(self):
        """KEV掲載のみ (EPSS低い) → high"""
        result = determine_priority(Decimal("0.3"), "MEDIUM", is_in_kev=True)
        assert result == "high"

    def test_high_kev_no_epss(self):
        """KEV掲載 + EPSSデータなし → high"""
        result = determine_priority(None, "MEDIUM", is_in_kev=True)
        assert result == "high"

    def test_high_epss_no_kev(self):
        """KEV未掲載 + EPSS >= 0.7 → high"""
        result = determine_priority(Decimal("0.75"), "MEDIUM", is_in_kev=False)
        assert result == "high"

    def test_medium_epss_and_high_severity(self):
        """EPSS >= 0.4 + 重大度HIGH → medium"""
        result = determine_priority(Decimal("0.45"), "HIGH", is_in_kev=False)
        assert result == "medium"

    def test_medium_epss_and_critical_severity(self):
        """EPSS >= 0.4 + 重大度CRITICAL → medium"""
        result = determine_priority(Decimal("0.5"), "CRITICAL", is_in_kev=False)
        assert result == "medium"

    def test_none_epss_below_threshold(self):
        """EPSS < 0.4 + KEV未掲載 → None（通知対象外）"""
        result = determine_priority(Decimal("0.2"), "HIGH", is_in_kev=False)
        assert result is None

    def test_none_medium_epss_low_severity(self):
        """EPSS >= 0.4 だが重大度が LOW → None（medium条件を満たさない）"""
        result = determine_priority(Decimal("0.5"), "LOW", is_in_kev=False)
        assert result is None

    def test_none_no_epss_no_kev(self):
        """EPSSデータなし + KEV未掲載 → None"""
        result = determine_priority(None, "HIGH", is_in_kev=False)
        assert result is None

    def test_boundary_epss_exactly_0_7(self):
        """EPSS = 0.7 ちょうどは high"""
        result = determine_priority(Decimal("0.7"), "LOW", is_in_kev=False)
        assert result == "high"

    def test_boundary_epss_exactly_0_4(self):
        """EPSS = 0.4 ちょうど + HIGH → medium"""
        result = determine_priority(Decimal("0.4"), "HIGH", is_in_kev=False)
        assert result == "medium"

    def test_boundary_epss_just_below_0_4(self):
        """EPSS = 0.39 + HIGH → None"""
        result = determine_priority(Decimal("0.39"), "HIGH", is_in_kev=False)
        assert result is None


class TestBuildReason:
    """判定理由の組み立てテスト"""

    def test_kev_and_high_epss(self):
        reason = build_reason("critical", Decimal("0.85"), Decimal("0.99"), is_in_kev=True)
        assert "KEV掲載中" in reason
        assert "EPSS上位" in reason

    def test_kev_only(self):
        reason = build_reason("high", Decimal("0.3"), Decimal("0.50"), is_in_kev=True)
        assert "KEV掲載中" in reason
        assert "実際の悪用確認済み" in reason

    def test_high_epss_no_kev(self):
        reason = build_reason("high", Decimal("0.85"), Decimal("0.99"), is_in_kev=False)
        assert "EPSS上位" in reason
        assert "悪用される確率" in reason

    def test_medium_epss(self):
        reason = build_reason("medium", Decimal("0.5"), Decimal("0.80"), is_in_kev=False)
        assert "EPSS中位" in reason
        assert "重大度HIGH以上" in reason


class TestSendSlackNotification:
    """Slack 通知メッセージ組み立てテスト"""

    @patch("cve_priority_notify.SLACK_WEBHOOK_URL", "https://hooks.slack.com/test")
    @patch("cve_priority_notify.send_slack")
    def test_single_high_entry(self, mock_send):
        entries = [
            {
                "cve_id": "CVE-2024-9264",
                "component": "docker.io/grafana/grafana",
                "category": "container",
                "severity": "HIGH",
                "summary": "Grafana Command Injection",
                "fixed_version": "11.5.1",
                "epss_score": Decimal("0.95"),
                "percentile": Decimal("0.99"),
                "is_in_kev": False,
                "kev_due_date": None,
                "priority": "high",
                "reason": "EPSS上位1% — 30日以内に悪用される確率95%",
            }
        ]
        send_slack_notification(entries)
        mock_send.assert_called_once()
        text = mock_send.call_args[0][0]
        assert "CVE優先度レポート" in text
        assert "HIGH (早期対応推奨): 1件" in text
        assert "CVE-2024-9264" in text
        assert "EPSS: 0.95" in text
        assert "修正版: 11.5.1" in text

    @patch("cve_priority_notify.SLACK_WEBHOOK_URL", "https://hooks.slack.com/test")
    @patch("cve_priority_notify.send_slack")
    def test_critical_with_kev(self, mock_send):
        entries = [
            {
                "cve_id": "CVE-2025-46599",
                "component": "k3s",
                "category": "runtime",
                "severity": "HIGH",
                "summary": "kubelet credential exposure",
                "fixed_version": "1.32.4",
                "epss_score": Decimal("0.85"),
                "percentile": Decimal("0.99"),
                "is_in_kev": True,
                "kev_due_date": "2025-12-22",
                "priority": "critical",
                "reason": "KEV掲載中 + EPSS上位1%",
            }
        ]
        send_slack_notification(entries)
        text = mock_send.call_args[0][0]
        assert "CRITICAL (即対応推奨): 1件" in text
        assert "KEV: ✓" in text
        assert "KEV対処期限: 2025-12-22" in text

    @patch("cve_priority_notify.SLACK_WEBHOOK_URL", "https://hooks.slack.com/test")
    @patch("cve_priority_notify.send_slack")
    def test_multiple_levels(self, mock_send):
        """critical + high + medium が全てセクションに表示される."""
        entries = [
            {
                "cve_id": "CVE-2025-0001",
                "component": "k3s",
                "category": "runtime",
                "severity": "HIGH",
                "summary": "test",
                "fixed_version": None,
                "epss_score": Decimal("0.85"),
                "percentile": Decimal("0.99"),
                "is_in_kev": True,
                "kev_due_date": "2026-01-01",
                "priority": "critical",
                "reason": "KEV掲載中 + EPSS上位1%",
            },
            {
                "cve_id": "CVE-2025-0002",
                "component": "grafana",
                "category": "container",
                "severity": "HIGH",
                "summary": "test",
                "fixed_version": "2.0.0",
                "epss_score": Decimal("0.75"),
                "percentile": Decimal("0.97"),
                "is_in_kev": False,
                "kev_due_date": None,
                "priority": "high",
                "reason": "EPSS上位3%",
            },
            {
                "cve_id": "CVE-2025-0003",
                "component": "loki",
                "category": "container",
                "severity": "HIGH",
                "summary": "test",
                "fixed_version": None,
                "epss_score": Decimal("0.45"),
                "percentile": Decimal("0.85"),
                "is_in_kev": False,
                "kev_due_date": None,
                "priority": "medium",
                "reason": "EPSS中位",
            },
        ]
        send_slack_notification(entries)
        text = mock_send.call_args[0][0]
        assert "CRITICAL (即対応推奨): 1件" in text
        assert "HIGH (早期対応推奨): 1件" in text
        assert "MEDIUM (計画的対応): 1件" in text
        assert "CRITICAL: 1件 / HIGH: 1件 / MEDIUM: 1件" in text

    @patch("cve_priority_notify.SLACK_WEBHOOK_URL", "")
    @patch("cve_priority_notify.send_slack")
    def test_skip_when_no_webhook(self, mock_send, capsys):
        entries = [
            {
                "cve_id": "CVE-2025-0001",
                "component": "k3s",
                "category": "runtime",
                "severity": "HIGH",
                "summary": "test",
                "fixed_version": None,
                "epss_score": Decimal("0.85"),
                "percentile": Decimal("0.99"),
                "is_in_kev": False,
                "kev_due_date": None,
                "priority": "high",
                "reason": "test",
            }
        ]
        send_slack_notification(entries)
        mock_send.assert_not_called()

    @patch("cve_priority_notify.SLACK_WEBHOOK_URL", "https://hooks.slack.com/test")
    @patch("cve_priority_notify.NOTIFY_MAX_ITEMS", 1)
    @patch("cve_priority_notify.send_slack")
    def test_truncation_over_max_items(self, mock_send):
        entries = [
            {
                "cve_id": f"CVE-2025-000{i}",
                "component": "grafana",
                "category": "container",
                "severity": "HIGH",
                "summary": "test",
                "fixed_version": None,
                "epss_score": Decimal("0.85"),
                "percentile": Decimal("0.99"),
                "is_in_kev": False,
                "kev_due_date": None,
                "priority": "high",
                "reason": "test",
            }
            for i in range(3)
        ]
        send_slack_notification(entries)
        text = mock_send.call_args[0][0]
        assert "他 2 件" in text


class TestMain:
    """main() フローテスト"""

    @patch("cve_priority_notify.get_conn")
    def test_db_connection_failure(self, mock_conn, capsys):
        import pymysql

        mock_conn.side_effect = pymysql.Error("connection refused")
        main()
        captured = capsys.readouterr()
        assert "DB接続失敗" in captured.out

    @patch("cve_priority_notify.get_unnotified_candidates")
    @patch("cve_priority_notify.get_conn")
    def test_no_candidates(self, mock_conn, mock_candidates, capsys):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
        conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.return_value = conn
        mock_candidates.return_value = []

        main()
        captured = capsys.readouterr()
        assert "未通知候補なし" in captured.out

    @patch("cve_priority_notify.send_slack_notification")
    @patch("cve_priority_notify.mark_notified")
    @patch("cve_priority_notify.is_first_run")
    @patch("cve_priority_notify.get_unnotified_candidates")
    @patch("cve_priority_notify.get_conn")
    def test_high_priority_found_and_notified(
        self, mock_conn, mock_candidates, mock_first, mock_mark, mock_slack, capsys
    ):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
        conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.return_value = conn
        mock_first.return_value = False

        mock_candidates.return_value = [
            {
                "cve_id": "CVE-2024-9264",
                "osv_id": "GHSA-xxxx",
                "component": "docker.io/grafana/grafana",
                "category": "container",
                "severity": "HIGH",
                "summary": "Command injection",
                "fixed_version": None,
                "epss_score": Decimal("0.95"),
                "percentile": Decimal("0.99"),
                "kev_cve_id": None,
                "kev_date_added": None,
                "kev_due_date": None,
                "known_ransomware_use": None,
            }
        ]

        main()
        captured = capsys.readouterr()
        assert "高優先CVE: 1件" in captured.out
        mock_slack.assert_called_once()
        mock_mark.assert_called_once()

    @patch("cve_priority_notify.send_slack_notification")
    @patch("cve_priority_notify.mark_notified")
    @patch("cve_priority_notify.is_first_run")
    @patch("cve_priority_notify.get_unnotified_candidates")
    @patch("cve_priority_notify.get_conn")
    def test_no_high_priority_after_filter(self, mock_conn, mock_candidates, mock_first, mock_mark, mock_slack, capsys):
        """全候補が閾値未満の場合は通知しない."""
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
        conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.return_value = conn
        mock_first.return_value = False

        mock_candidates.return_value = [
            {
                "cve_id": "CVE-2024-0001",
                "osv_id": "GHSA-xxxx",
                "component": "grafana",
                "category": "container",
                "severity": "LOW",
                "summary": "minor issue",
                "fixed_version": None,
                "epss_score": Decimal("0.10"),
                "percentile": Decimal("0.40"),
                "kev_cve_id": None,
                "kev_date_added": None,
                "kev_due_date": None,
                "known_ransomware_use": None,
            }
        ]

        main()
        captured = capsys.readouterr()
        assert "高優先CVEなし" in captured.out
        mock_slack.assert_not_called()
        mock_mark.assert_not_called()

    @patch("cve_priority_notify.send_bulk_notification")
    @patch("cve_priority_notify.mark_notified")
    @patch("cve_priority_notify.is_first_run")
    @patch("cve_priority_notify.get_unnotified_candidates")
    @patch("cve_priority_notify.get_conn")
    def test_first_run_bulk_notification(self, mock_conn, mock_candidates, mock_first, mock_mark, mock_bulk, capsys):
        """初回 + 大量検知時はサマリ通知."""
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
        conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.return_value = conn
        mock_first.return_value = True

        # PRIORITY_BULK_THRESHOLD(10)を超える数の高優先CVEを生成
        candidates = [
            {
                "cve_id": f"CVE-2024-{i:04d}",
                "osv_id": f"GHSA-{i:04d}",
                "component": "grafana",
                "category": "container",
                "severity": "HIGH",
                "summary": "test",
                "fixed_version": None,
                "epss_score": Decimal("0.85"),
                "percentile": Decimal("0.99"),
                "kev_cve_id": None,
                "kev_date_added": None,
                "kev_due_date": None,
                "known_ransomware_use": None,
            }
            for i in range(12)
        ]
        mock_candidates.return_value = candidates

        main()
        captured = capsys.readouterr()
        assert "サマリ通知" in captured.out
        mock_bulk.assert_called_once()
        mock_mark.assert_called_once()

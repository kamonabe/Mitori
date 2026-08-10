"""cve_watch.py のロジックテスト"""
from unittest.mock import patch

from cve_watch import (
    normalize_version,
    parse_cvss_severity,
    extract_fixed_version,
    extract_cve_id,
    send_slack_notification,
)


class TestNormalizeVersion:
    """バージョン文字列の正規化テスト"""

    def test_strip_v_prefix(self):
        assert normalize_version("v1.36.2+k3s1") == "1.36.2+k3s1"

    def test_strip_v_simple(self):
        assert normalize_version("v3.13.0") == "3.13.0"

    def test_no_v_prefix(self):
        assert normalize_version("13.1.0") == "13.1.0"

    def test_strip_distroless_suffix(self):
        assert normalize_version("v3.13.0-distroless") == "3.13.0"

    def test_strip_slim_suffix(self):
        assert normalize_version("v1.0.0-slim") == "1.0.0"

    def test_strip_alpine_suffix(self):
        assert normalize_version("2.7.0-alpine") == "2.7.0"

    def test_strip_bookworm_suffix(self):
        assert normalize_version("3.12.4-bookworm") == "3.12.4"

    def test_empty_string(self):
        assert normalize_version("") == ""

    def test_none(self):
        assert normalize_version(None) == ""

    def test_k3s_version_preserved(self):
        """k3s のビルドメタデータ(+k3s1)は残る"""
        assert normalize_version("v1.32.4+k3s1") == "1.32.4+k3s1"


class TestParseCvssSeverity:
    """CVSS severity パーステスト"""

    def test_cvss_v3_vector(self):
        severity_list = [
            {"type": "CVSS_V3", "score": "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H"}
        ]
        severity, score, vector = parse_cvss_severity(severity_list)
        assert vector == "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H"
        assert severity == "UNKNOWN"  # severity_list だけでは severity 文字列は取れない

    def test_db_specific_severity(self):
        severity_list = []
        db_specific = {"severity": "HIGH"}
        severity, score, vector = parse_cvss_severity(severity_list, db_specific)
        assert severity == "HIGH"
        assert vector is None

    def test_db_specific_overrides_unknown(self):
        severity_list = [{"type": "CVSS_V3", "score": "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H"}]
        db_specific = {"severity": "CRITICAL"}
        severity, score, vector = parse_cvss_severity(severity_list, db_specific)
        assert severity == "CRITICAL"
        assert vector == "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H"

    def test_empty_inputs(self):
        severity, score, vector = parse_cvss_severity(None)
        assert severity == "UNKNOWN"
        assert score is None
        assert vector is None

    def test_no_cvss_v3(self):
        severity_list = [{"type": "CVSS_V2", "score": "AV:N/AC:L/Au:N/C:P/I:P/A:P"}]
        severity, score, vector = parse_cvss_severity(severity_list)
        assert vector is None  # V3 のみ対応

    def test_severity_lowercase_normalized(self):
        db_specific = {"severity": "moderate"}
        severity, _, _ = parse_cvss_severity([], db_specific)
        assert severity == "MODERATE"


class TestExtractFixedVersion:
    """fixed version 抽出テスト"""

    def test_basic_extraction(self):
        affected = [
            {
                "ranges": [
                    {
                        "type": "SEMVER",
                        "events": [
                            {"introduced": "0"},
                            {"fixed": "1.9.2"},
                        ],
                    }
                ]
            }
        ]
        assert extract_fixed_version(affected) == "1.9.2"

    def test_multiple_ranges_takes_first(self):
        affected = [
            {
                "ranges": [
                    {
                        "type": "SEMVER",
                        "events": [
                            {"introduced": "0"},
                            {"fixed": "2.0.0"},
                        ],
                    },
                    {
                        "type": "SEMVER",
                        "events": [
                            {"introduced": "3.0.0"},
                            {"fixed": "3.1.0"},
                        ],
                    },
                ]
            }
        ]
        assert extract_fixed_version(affected) == "2.0.0"

    def test_no_fixed_event(self):
        affected = [
            {
                "ranges": [
                    {
                        "type": "SEMVER",
                        "events": [{"introduced": "0"}],
                    }
                ]
            }
        ]
        assert extract_fixed_version(affected) is None

    def test_empty_affected(self):
        assert extract_fixed_version([]) is None

    def test_none_affected(self):
        assert extract_fixed_version(None) is None


class TestExtractCveId:
    """CVE-ID 抽出テスト"""

    def test_basic(self):
        aliases = ["GHSA-xxxx-yyyy-zzzz", "CVE-2024-12345"]
        assert extract_cve_id(aliases) == "CVE-2024-12345"

    def test_multiple_cves_takes_first(self):
        aliases = ["CVE-2024-11111", "CVE-2024-22222"]
        assert extract_cve_id(aliases) == "CVE-2024-11111"

    def test_no_cve(self):
        aliases = ["GHSA-xxxx-yyyy-zzzz"]
        assert extract_cve_id(aliases) == ""

    def test_empty_list(self):
        assert extract_cve_id([]) == ""

    def test_none(self):
        assert extract_cve_id(None) == ""


class TestSendSlackNotification:
    """Slack 通知メッセージ組み立てテスト"""

    @patch("cve_watch.SLACK_WEBHOOK_URL", "https://hooks.slack.com/test")
    @patch("cve_watch.requests.post")
    def test_new_cve_notification(self, mock_post):
        notifications = [
            {
                "type": "new_cve",
                "osv_id": "GHSA-test-1234",
                "cve_id": "CVE-2024-99999",
                "component": "github.com/example/pkg",
                "severity": "HIGH",
                "summary": "Test vulnerability",
                "fixed_version": "1.2.3",
            }
        ]
        send_slack_notification(notifications)
        mock_post.assert_called_once()
        payload = mock_post.call_args[1]["json"]
        assert "新規CVE検知" in payload["text"]
        assert "CVE-2024-99999" in payload["text"]
        assert "HIGH" in payload["text"]

    @patch("cve_watch.SLACK_WEBHOOK_URL", "https://hooks.slack.com/test")
    @patch("cve_watch.requests.post")
    def test_resolved_notification(self, mock_post):
        notifications = [
            {
                "type": "resolved",
                "osv_id": "GHSA-test-5678",
                "cve_id": "CVE-2024-88888",
                "component": "github.com/example/pkg",
                "summary": "Fixed vuln",
                "current_version": "2.0.0",
            }
        ]
        send_slack_notification(notifications)
        mock_post.assert_called_once()
        payload = mock_post.call_args[1]["json"]
        assert "対処済み確認" in payload["text"]

    @patch("cve_watch.SLACK_WEBHOOK_URL", "")
    @patch("cve_watch.requests.post")
    def test_skip_when_no_webhook(self, mock_post):
        notifications = [{"type": "new_cve", "osv_id": "X", "cve_id": "Y", "component": "Z", "severity": "LOW", "summary": "test", "fixed_version": None}]
        send_slack_notification(notifications)
        mock_post.assert_not_called()

    @patch("cve_watch.SLACK_WEBHOOK_URL", "https://hooks.slack.com/test")
    @patch("cve_watch.requests.post")
    def test_empty_notifications_skipped(self, mock_post):
        send_slack_notification([])
        mock_post.assert_not_called()

    @patch("cve_watch.SLACK_WEBHOOK_URL", "https://hooks.slack.com/test")
    @patch("cve_watch.requests.post")
    def test_mixed_notifications(self, mock_post):
        notifications = [
            {"type": "new_cve", "osv_id": "A", "cve_id": "CVE-1", "component": "pkg1", "severity": "HIGH", "summary": "s1", "fixed_version": "1.0"},
            {"type": "fix_available", "osv_id": "B", "cve_id": "CVE-2", "component": "pkg2", "fixed_version": "2.0"},
            {"type": "severity_changed", "osv_id": "C", "cve_id": "CVE-3", "component": "pkg3", "old_severity": "LOW", "new_severity": "CRITICAL"},
        ]
        send_slack_notification(notifications)
        mock_post.assert_called_once()
        payload = mock_post.call_args[1]["json"]
        assert "新規CVE検知" in payload["text"]
        assert "修正版が公開されました" in payload["text"]
        assert "深刻度変更" in payload["text"]

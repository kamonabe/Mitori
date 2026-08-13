"""cve_watch.py の通知フォーマット改善テスト"""

from unittest.mock import patch

from cve_watch import (
    build_action_guide,
    build_reference_urls,
    send_slack_notification,
)


class TestBuildReferenceUrls:
    """参照URL組み立てテスト"""

    def test_cve_and_osv(self):
        urls = build_reference_urls("GO-2025-3646", "CVE-2025-46599")
        assert "https://nvd.nist.gov/vuln/detail/CVE-2025-46599" in urls
        assert "https://osv.dev/vulnerability/GO-2025-3646" in urls
        assert len(urls) == 2

    def test_ghsa_id_adds_github_url(self):
        urls = build_reference_urls("GHSA-xxxx-yyyy-zzzz", "CVE-2025-12345")
        assert "https://nvd.nist.gov/vuln/detail/CVE-2025-12345" in urls
        assert "https://osv.dev/vulnerability/GHSA-xxxx-yyyy-zzzz" in urls
        assert "https://github.com/advisories/GHSA-xxxx-yyyy-zzzz" in urls
        assert len(urls) == 3

    def test_no_cve_id(self):
        urls = build_reference_urls("GO-2025-1234", "")
        assert len(urls) == 1
        assert "https://osv.dev/vulnerability/GO-2025-1234" in urls

    def test_ghsa_without_cve(self):
        urls = build_reference_urls("GHSA-abcd-efgh-ijkl", "")
        assert "https://osv.dev/vulnerability/GHSA-abcd-efgh-ijkl" in urls
        assert "https://github.com/advisories/GHSA-abcd-efgh-ijkl" in urls
        assert len(urls) == 2

    def test_empty_osv_id(self):
        urls = build_reference_urls("", "CVE-2025-99999")
        assert "https://nvd.nist.gov/vuln/detail/CVE-2025-99999" in urls
        assert len(urls) == 1


class TestBuildActionGuide:
    """アクションガイド組み立てテスト"""

    def test_helm_with_fixed(self):
        result = build_action_guide("helm", "2.0.0")
        assert "helm upgrade" in result
        assert "2.0.0" in result

    def test_container_with_fixed(self):
        result = build_action_guide("container", "3.5.1")
        assert "コンテナイメージ" in result
        assert "3.5.1" in result

    def test_runtime_with_fixed(self):
        result = build_action_guide("runtime", "1.32.4")
        assert "k3s" in result
        assert "1.32.4" in result

    def test_database_with_fixed(self):
        result = build_action_guide("database", "11.9.0")
        assert "MariaDB" in result
        assert "11.9.0" in result

    def test_unknown_category_with_fixed(self):
        result = build_action_guide("other", "5.0.0")
        assert "5.0.0" in result
        assert "修正済み" in result

    def test_helm_without_fixed(self):
        result = build_action_guide("helm", None)
        assert "修正版未公開" in result
        assert "リリースノート" in result

    def test_container_without_fixed(self):
        result = build_action_guide("container", None)
        assert "修正版未公開" in result
        assert "上流" in result

    def test_runtime_without_fixed(self):
        result = build_action_guide("runtime", None)
        assert "修正版未公開" in result
        assert "k3s" in result

    def test_database_without_fixed(self):
        result = build_action_guide("database", None)
        assert "修正版未公開" in result

    def test_unknown_category_without_fixed(self):
        result = build_action_guide("other", None)
        assert result == "修正版未公開"


class TestNotificationFormatEnhanced:
    """改善後の通知フォーマット検証テスト"""

    @patch("cve_watch.SLACK_WEBHOOK_URL", "https://hooks.slack.com/test")
    @patch("cve_watch.send_slack")
    def test_new_cve_includes_action_and_urls(self, mock_send):
        """新規CVE通知にアクションガイドと参照URLが含まれる"""
        notifications = [
            {
                "type": "new_cve",
                "osv_id": "GO-2025-3646",
                "cve_id": "CVE-2025-46599",
                "component": "k3s",
                "category": "runtime",
                "version": "v1.36.2+k3s1",
                "severity": "HIGH",
                "summary": "kubelet configuration exposes credentials",
                "fixed_version": "1.32.4",
            }
        ]
        send_slack_notification(notifications)
        mock_send.assert_called_once()
        text = mock_send.call_args[0][0]

        # アクションガイド
        assert "対応:" in text
        assert "k3s を 1.32.4 以降に更新" in text
        # 参照URL
        assert "https://nvd.nist.gov/vuln/detail/CVE-2025-46599" in text
        assert "https://osv.dev/vulnerability/GO-2025-3646" in text
        # 対象にカテゴリとバージョンが含まれる
        assert "k3s (runtime) v1.36.2+k3s1" in text
        # 修正版
        assert "修正版: 1.32.4" in text

    @patch("cve_watch.SLACK_WEBHOOK_URL", "https://hooks.slack.com/test")
    @patch("cve_watch.send_slack")
    def test_new_cve_without_fixed_version(self, mock_send):
        """修正版なしの新規CVE通知"""
        notifications = [
            {
                "type": "new_cve",
                "osv_id": "GHSA-abcd-efgh-ijkl",
                "cve_id": "",
                "component": "docker.io/grafana/grafana",
                "category": "container",
                "version": "11.6.0",
                "severity": "MEDIUM",
                "summary": "Stored XSS in dashboard panel",
                "fixed_version": None,
            }
        ]
        send_slack_notification(notifications)
        text = mock_send.call_args[0][0]

        assert "修正版: なし" in text
        assert "修正版未公開: 上流のリリースを監視" in text
        assert "https://osv.dev/vulnerability/GHSA-abcd-efgh-ijkl" in text
        assert "https://github.com/advisories/GHSA-abcd-efgh-ijkl" in text
        # NVD URLはCVE IDがないので含まれない
        assert "nvd.nist.gov" not in text

    @patch("cve_watch.SLACK_WEBHOOK_URL", "https://hooks.slack.com/test")
    @patch("cve_watch.send_slack")
    def test_fix_available_includes_action_and_urls(self, mock_send):
        """修正版判明通知にアクションガイドと参照URLが含まれる"""
        notifications = [
            {
                "type": "fix_available",
                "osv_id": "GO-2025-9999",
                "cve_id": "CVE-2025-12345",
                "component": "docker.io/grafana/loki",
                "category": "container",
                "severity": "HIGH",
                "fixed_version": "3.5.1",
            }
        ]
        send_slack_notification(notifications)
        text = mock_send.call_args[0][0]

        assert "修正版が公開されました" in text
        assert "コンテナイメージを 3.5.1 以降に更新" in text
        assert "https://nvd.nist.gov/vuln/detail/CVE-2025-12345" in text

    @patch("cve_watch.SLACK_WEBHOOK_URL", "https://hooks.slack.com/test")
    @patch("cve_watch.send_slack")
    def test_resolved_includes_reason(self, mock_send):
        """対処済み通知に理由が含まれる"""
        notifications = [
            {
                "type": "resolved",
                "osv_id": "GO-2025-1111",
                "cve_id": "CVE-2025-46599",
                "component": "k3s",
                "summary": "Fixed vuln",
                "current_version": "v1.36.3+k3s1",
            }
        ]
        send_slack_notification(notifications)
        text = mock_send.call_args[0][0]

        assert "バージョンアップにより解消" in text
        assert "v1.36.3+k3s1" in text

    @patch("cve_watch.SLACK_WEBHOOK_URL", "https://hooks.slack.com/test")
    @patch("cve_watch.send_slack")
    def test_severity_changed_includes_url(self, mock_send):
        """深刻度変更通知に参照URLが含まれる"""
        notifications = [
            {
                "type": "severity_changed",
                "osv_id": "GO-2025-5555",
                "cve_id": "CVE-2025-99999",
                "component": "docker.io/grafana/grafana",
                "old_severity": "MEDIUM",
                "new_severity": "HIGH",
            }
        ]
        send_slack_notification(notifications)
        text = mock_send.call_args[0][0]

        assert "MEDIUM → HIGH" in text
        assert "https://nvd.nist.gov/vuln/detail/CVE-2025-99999" in text

    @patch("cve_watch.SLACK_WEBHOOK_URL", "https://hooks.slack.com/test")
    @patch("cve_watch.send_slack")
    def test_backward_compat_without_category(self, mock_send):
        """category/versionフィールドがない通知dictでも動作する（後方互換）"""
        notifications = [
            {
                "type": "new_cve",
                "osv_id": "GO-2025-0001",
                "cve_id": "CVE-2025-00001",
                "component": "some-pkg",
                "severity": "LOW",
                "summary": "Minor issue",
                "fixed_version": None,
            }
        ]
        send_slack_notification(notifications)
        mock_send.assert_called_once()
        text = mock_send.call_args[0][0]
        assert "some-pkg" in text
        assert "修正版未公開" in text

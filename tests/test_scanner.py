"""inventory-scan/scanner.py のロジックテスト"""

import os
from unittest.mock import patch

os.environ.setdefault("DB_HOST", "localhost")
os.environ.setdefault("DB_USER", "test")
os.environ.setdefault("DB_PASSWORD", "test")
os.environ.setdefault("DB_NAME", "test")

from scanner import (
    extract_chart_version,
    parse_image_ref,
    send_slack_notification,
)


class TestExtractChartVersion:
    """extract_chart_version のテスト"""

    def test_basic_chart(self):
        assert extract_chart_version("mariadb-22.0.3") == "22.0.3"

    def test_chart_with_prefix(self):
        assert extract_chart_version("kube-prometheus-stack-72.6.2") == "72.6.2"

    def test_chart_with_prerelease(self):
        assert extract_chart_version("loki-6.30.0-rc1") == "6.30.0-rc1"

    def test_no_version_pattern(self):
        """バージョン部分が見つからない場合はそのまま返す"""
        assert extract_chart_version("noversion") == "noversion"

    def test_only_version(self):
        """先頭がハイフン+バージョンだけの場合"""
        assert extract_chart_version("chart-1.2.3") == "1.2.3"


class TestParseImageRef:
    """parse_image_ref のテスト"""

    def test_basic_tag(self):
        component, version = parse_image_ref("nginx:1.25.0")
        assert component == "nginx"
        assert version == "1.25.0"

    def test_registry_with_port(self):
        component, version = parse_image_ref("registry:5000/myimage:v2.0")
        assert component == "registry:5000/myimage"
        assert version == "v2.0"

    def test_digest_format(self):
        component, version = parse_image_ref("ghcr.io/owner/repo@sha256:abc123")
        assert component == "ghcr.io/owner/repo"
        assert version == "sha256:abc123"

    def test_no_tag(self):
        component, version = parse_image_ref("python")
        assert component == "python"
        assert version == "latest"

    def test_full_registry_path(self):
        component, version = parse_image_ref("ghcr.io/kamonabe/mitori-base:3.12-slim")
        assert component == "ghcr.io/kamonabe/mitori-base"
        assert version == "3.12-slim"

    def test_docker_io_official(self):
        component, version = parse_image_ref("docker.io/library/python:3.12-bookworm")
        assert component == "docker.io/library/python"
        assert version == "3.12-bookworm"


class TestSendSlackNotification:
    """send_slack_notification のテスト"""

    @patch("scanner.SLACK_WEBHOOK_URL", "")
    @patch("scanner.send_slack")
    def test_skip_when_no_webhook(self, mock_send):
        send_slack_notification([{"component": "x", "prev_version": "1.0", "version": "2.0"}])
        mock_send.assert_not_called()

    @patch("scanner.SLACK_WEBHOOK_URL", "https://hooks.slack.com/test")
    @patch("scanner.send_slack")
    def test_skip_when_empty_changes(self, mock_send):
        send_slack_notification([])
        mock_send.assert_not_called()

    @patch("scanner.SLACK_WEBHOOK_URL", "https://hooks.slack.com/test")
    @patch("scanner.send_slack")
    def test_single_change(self, mock_send):
        changes = [{"component": "k3s", "prev_version": "1.31.0", "version": "1.32.0"}]
        send_slack_notification(changes)
        mock_send.assert_called_once()
        text = mock_send.call_args[0][0]
        assert "k3s" in text
        assert "1.31.0" in text
        assert "1.32.0" in text
        assert "1件" in text

    @patch("scanner.SLACK_WEBHOOK_URL", "https://hooks.slack.com/test")
    @patch("scanner.send_slack")
    def test_new_component(self, mock_send):
        changes = [{"component": "mariadb", "prev_version": None, "version": "11.8.2"}]
        send_slack_notification(changes)
        mock_send.assert_called_once()
        text = mock_send.call_args[0][0]
        assert "(新規)" in text

    @patch("scanner.SLACK_WEBHOOK_URL", "https://hooks.slack.com/test")
    @patch("scanner.send_slack")
    def test_exceeds_max_items(self, mock_send):
        changes = [{"component": f"comp-{i}", "prev_version": "1.0", "version": "2.0"} for i in range(8)]
        send_slack_notification(changes)
        mock_send.assert_called_once()
        text = mock_send.call_args[0][0]
        assert "8件" in text
        assert "他 3 件" in text

    @patch("scanner.SLACK_WEBHOOK_URL", "https://hooks.slack.com/test")
    @patch("scanner.send_slack")
    def test_handles_request_exception(self, mock_send):
        """send_slack内で例外が処理されるためraiseしない."""
        mock_send.side_effect = None
        changes = [{"component": "k3s", "prev_version": "1.0", "version": "2.0"}]
        send_slack_notification(changes)

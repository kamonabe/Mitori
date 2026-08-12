"""cve_coverage_report.py のテスト"""

import os
from unittest.mock import MagicMock, patch

os.environ.setdefault("DB_HOST", "localhost")
os.environ.setdefault("DB_USER", "test")
os.environ.setdefault("DB_PASSWORD", "test")
os.environ.setdefault("DB_NAME", "test")

from cve_coverage_report import build_report, format_message, main


class TestBuildReport:
    """build_report のテスト"""

    def test_all_covered(self):
        inventory = [
            {"component": "k3s", "category": "runtime", "version": "1.36.2"},
            {"component": "mariadb", "category": "database", "version": "11.8.2"},
        ]
        monitored = [
            {
                "inventory_component": "k3s",
                "inventory_category": "runtime",
                "osv_ecosystem": "Go",
                "osv_package_name": "github.com/k3s-io/k3s",
            },
            {
                "inventory_component": "mariadb",
                "inventory_category": "database",
                "osv_ecosystem": "Linux",
                "osv_package_name": "mariadb",
            },
        ]
        covered, uncovered = build_report(inventory, monitored)
        assert len(covered) == 2
        assert len(uncovered) == 0

    def test_some_uncovered(self):
        inventory = [
            {"component": "k3s", "category": "runtime", "version": "1.36.2"},
            {"component": "ruby", "category": "container", "version": "3.3.0"},
        ]
        monitored = [
            {
                "inventory_component": "k3s",
                "inventory_category": "runtime",
                "osv_ecosystem": "Go",
                "osv_package_name": "github.com/k3s-io/k3s",
            },
        ]
        covered, uncovered = build_report(inventory, monitored)
        assert len(covered) == 1
        assert len(uncovered) == 1
        assert uncovered[0]["component"] == "ruby"

    def test_empty_inventory(self):
        covered, uncovered = build_report([], [])
        assert len(covered) == 0
        assert len(uncovered) == 0

    def test_no_monitored(self):
        inventory = [
            {"component": "k3s", "category": "runtime", "version": "1.36.2"},
        ]
        covered, uncovered = build_report(inventory, [])
        assert len(covered) == 0
        assert len(uncovered) == 1


class TestFormatMessage:
    """format_message のテスト"""

    def test_all_covered(self):
        covered = [{"component": "k3s", "category": "runtime", "version": "1.36.2"}]
        uncovered = []
        msg = format_message(covered, uncovered)
        assert "カバレッジ: 100%" in msg
        assert "全コンポーネントがCVE監視対象です" in msg

    def test_some_uncovered(self):
        covered = [{"component": "k3s", "category": "runtime", "version": "1.36.2"}]
        uncovered = [{"component": "ruby", "category": "container", "version": "3.3.0"}]
        msg = format_message(covered, uncovered)
        assert "未監視: 1件" in msg
        assert "ruby" in msg
        assert "マッピングを追加" in msg

    def test_truncation_over_15(self):
        covered = []
        uncovered = [{"component": f"pkg-{i}", "category": "container", "version": "1.0"} for i in range(20)]
        msg = format_message(covered, uncovered)
        assert "他 5 件" in msg


class TestMain:
    """main() フローテスト"""

    @patch("cve_coverage_report.get_conn")
    def test_db_connection_failure(self, mock_conn, capsys):
        import pymysql

        mock_conn.side_effect = pymysql.Error("connection refused")
        main()
        captured = capsys.readouterr()
        assert "DB接続失敗" in captured.out

    @patch("cve_coverage_report.SLACK_WEBHOOK_URL", "https://hooks.slack.com/test")
    @patch("cve_coverage_report.send_slack")
    @patch("cve_coverage_report.get_conn")
    def test_sends_report(self, mock_conn, mock_send, capsys):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
        conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        # get_inventory_components
        inventory = [
            {"component": "k3s", "category": "runtime", "version": "1.36.2"},
            {"component": "ruby", "category": "container", "version": "3.3.0"},
        ]
        # get_monitored_components
        monitored = [
            {
                "inventory_component": "k3s",
                "inventory_category": "runtime",
                "osv_ecosystem": "Go",
                "osv_package_name": "x",
            },
        ]
        cursor.fetchall.side_effect = [inventory, monitored]
        mock_conn.return_value = conn

        main()
        mock_send.assert_called_once()
        text = mock_send.call_args[0][0]
        assert "ruby" in text
        assert "未監視: 1件" in text

    @patch("cve_coverage_report.SLACK_WEBHOOK_URL", "")
    @patch("cve_coverage_report.send_slack")
    @patch("cve_coverage_report.get_conn")
    def test_skip_when_no_webhook(self, mock_conn, mock_send, capsys):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
        conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        cursor.fetchall.side_effect = [
            [{"component": "k3s", "category": "runtime", "version": "1.0"}],
            [],
        ]
        mock_conn.return_value = conn

        main()
        mock_send.assert_not_called()
        captured = capsys.readouterr()
        assert "スキップ" in captured.out

    @patch("cve_coverage_report.get_conn")
    def test_empty_inventory(self, mock_conn, capsys):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
        conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        cursor.fetchall.return_value = []
        mock_conn.return_value = conn

        main()
        captured = capsys.readouterr()
        assert "inventoryが空" in captured.out

"""cve_watch.py の main フロー・auto_resolve テスト"""

import os
from unittest.mock import MagicMock, patch

os.environ.setdefault("DB_HOST", "localhost")
os.environ.setdefault("DB_USER", "test")
os.environ.setdefault("DB_PASSWORD", "test")
os.environ.setdefault("DB_NAME", "test")

from cve_watch import auto_resolve, main


class TestAutoResolve:
    """auto_resolve のテスト"""

    @patch("cve_watch.resolve_cve")
    @patch("cve_watch.query_osv")
    @patch("cve_watch.get_package_mapping")
    def test_resolves_when_no_longer_affected(self, mock_mapping, mock_osv, mock_resolve):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
        conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        cursor.fetchall.return_value = [
            {
                "osv_id": "GHSA-1234",
                "cve_id": "CVE-2024-1111",
                "component": "pkg",
                "category": "container",
                "fixed_version": "2.0.0",
                "summary": "test vuln",
                "current_version": "2.1.0",
            }
        ]
        mock_mapping.return_value = {"osv_ecosystem": "Go", "osv_package_name": "github.com/example/pkg"}
        mock_osv.return_value = []  # 現バージョンでは影響なし

        notifications = []
        auto_resolve(conn, notifications)

        mock_resolve.assert_called_once_with(conn, "GHSA-1234", "pkg", "container")
        assert len(notifications) == 1
        assert notifications[0]["type"] == "resolved"

    @patch("cve_watch.resolve_cve")
    @patch("cve_watch.query_osv")
    @patch("cve_watch.get_package_mapping")
    def test_does_not_resolve_when_still_affected(self, mock_mapping, mock_osv, mock_resolve):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
        conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        cursor.fetchall.return_value = [
            {
                "osv_id": "GHSA-1234",
                "cve_id": "CVE-2024-1111",
                "component": "pkg",
                "category": "container",
                "fixed_version": "3.0.0",
                "summary": "test vuln",
                "current_version": "2.1.0",
            }
        ]
        mock_mapping.return_value = {"osv_ecosystem": "Go", "osv_package_name": "github.com/example/pkg"}
        mock_osv.return_value = [{"id": "GHSA-1234"}]  # まだ影響あり

        notifications = []
        auto_resolve(conn, notifications)

        mock_resolve.assert_not_called()
        assert notifications == []

    @patch("cve_watch.query_osv")
    @patch("cve_watch.get_package_mapping")
    def test_skips_when_no_mapping(self, mock_mapping, mock_osv):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
        conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        cursor.fetchall.return_value = [
            {
                "osv_id": "GHSA-5678",
                "cve_id": "CVE-2024-2222",
                "component": "unmapped",
                "category": "container",
                "fixed_version": "2.0.0",
                "summary": "test",
                "current_version": "2.0.0",
            }
        ]
        mock_mapping.return_value = None  # マッピングなし

        notifications = []
        auto_resolve(conn, notifications)
        mock_osv.assert_not_called()


class TestMain:
    """main フローテスト"""

    @patch("cve_watch.get_conn")
    def test_db_connection_failure(self, mock_conn, capsys):
        import pymysql

        mock_conn.side_effect = pymysql.Error("connection refused")
        main()
        captured = capsys.readouterr()
        assert "DB接続失敗" in captured.out

    @patch("cve_watch.get_conn")
    def test_no_targets(self, mock_conn, capsys):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
        conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        cursor.fetchall.return_value = []
        mock_conn.return_value = conn

        main()
        captured = capsys.readouterr()
        assert "監視対象がありません" in captured.out

    @patch("cve_watch.send_slack_notification")
    @patch("cve_watch.auto_resolve")
    @patch("cve_watch.query_osv")
    @patch("cve_watch.get_conn")
    def test_new_cve_detected(self, mock_conn, mock_osv, mock_resolve, mock_slack, capsys):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
        conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        # fetchall は2回呼ばれる: targets取得 と auto_resolve内
        targets = [
            {
                "inventory_component": "pkg",
                "inventory_category": "container",
                "osv_ecosystem": "Go",
                "osv_package_name": "github.com/example/pkg",
                "version": "v1.0.0",
            }
        ]
        cursor.fetchall.return_value = targets
        # fetchone: 1回目=is_first_scan_for_component(cnt>0=通常運用),
        #           2回目=get_existing_cve(None=新規)
        cursor.fetchone.side_effect = [{"cnt": 1}, None]
        mock_conn.return_value = conn

        mock_osv.return_value = [
            {
                "id": "GHSA-test-1234",
                "aliases": ["CVE-2024-99999"],
                "summary": "Test vuln",
                "severity": [{"type": "CVSS_V3", "score": "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H"}],
                "database_specific": {"severity": "HIGH"},
                "affected": [{"ranges": [{"type": "SEMVER", "events": [{"introduced": "0"}, {"fixed": "2.0.0"}]}]}],
                "published": "2026-08-01T00:00:00Z",
            }
        ]

        main()
        captured = capsys.readouterr()
        assert "新規" in captured.out
        mock_slack.assert_called_once()

    @patch("cve_watch.send_slack_notification")
    @patch("cve_watch.auto_resolve")
    @patch("cve_watch.query_osv")
    @patch("cve_watch.get_conn")
    def test_no_state_changes(self, mock_conn, mock_osv, mock_resolve, mock_slack, capsys):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
        conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        targets = [
            {
                "inventory_component": "pkg",
                "inventory_category": "container",
                "osv_ecosystem": "Go",
                "osv_package_name": "github.com/example/pkg",
                "version": "v2.0.0",
            }
        ]
        cursor.fetchall.return_value = targets
        cursor.fetchone.return_value = {"cnt": 1}  # is_first_scan_for_component
        mock_conn.return_value = conn
        mock_osv.return_value = []  # 脆弱性なし

        main()
        captured = capsys.readouterr()
        assert "状態変化なし" in captured.out
        mock_slack.assert_not_called()

    @patch("cve_watch.send_slack_notification")
    @patch("cve_watch.auto_resolve")
    @patch("cve_watch.update_cve_fixed")
    @patch("cve_watch.query_osv")
    @patch("cve_watch.get_conn")
    def test_fix_available_detected(self, mock_conn, mock_osv, mock_update_fixed, mock_resolve, mock_slack, capsys):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
        conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        targets = [
            {
                "inventory_component": "pkg",
                "inventory_category": "container",
                "osv_ecosystem": "Go",
                "osv_package_name": "github.com/example/pkg",
                "version": "v1.0.0",
            }
        ]
        cursor.fetchall.return_value = targets
        # fetchone: 1回目=is_first_scan_for_component(cnt>0=通常運用),
        #           2回目=get_existing_cve(既存レコードあり)
        cursor.fetchone.side_effect = [
            {"cnt": 1},
            {
                "osv_id": "GHSA-1234",
                "cve_id": "CVE-2024-1111",
                "component": "pkg",
                "category": "container",
                "severity": "HIGH",
                "fixed_version": None,
            },
        ]
        mock_conn.return_value = conn
        mock_osv.return_value = [
            {
                "id": "GHSA-1234",
                "aliases": ["CVE-2024-1111"],
                "summary": "vuln",
                "severity": [{"type": "CVSS_V3", "score": "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H"}],
                "database_specific": {"severity": "HIGH"},
                "affected": [{"ranges": [{"type": "SEMVER", "events": [{"introduced": "0"}, {"fixed": "2.0.0"}]}]}],
            }
        ]

        main()
        captured = capsys.readouterr()
        assert "修正版判明" in captured.out
        mock_update_fixed.assert_called_once()

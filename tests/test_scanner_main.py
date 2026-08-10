"""inventory-scan/scanner.py の main フローテスト"""

import json
import os
from unittest.mock import MagicMock, patch

os.environ.setdefault("DB_HOST", "localhost")
os.environ.setdefault("DB_USER", "test")
os.environ.setdefault("DB_PASSWORD", "test")
os.environ.setdefault("DB_NAME", "test")

from scanner import main


class TestMain:
    """main フローテスト"""

    @patch("scanner.get_conn")
    def test_db_connection_failure(self, mock_conn, capsys):
        import pymysql

        mock_conn.side_effect = pymysql.Error("connection refused")
        main()
        captured = capsys.readouterr()
        assert "DB接続失敗" in captured.out

    @patch("scanner.send_slack_notification")
    @patch("scanner.collect_container_images")
    @patch("scanner.collect_helm_releases")
    @patch("scanner.collect_mariadb_version")
    @patch("scanner.collect_k3s_version")
    @patch("scanner.ensure_table")
    @patch("scanner.get_conn")
    def test_no_changes(self, mock_conn, mock_ensure, mock_k3s, mock_maria, mock_helm, mock_images, mock_slack, capsys):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
        conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.return_value = conn

        # 各コレクタ: 何も返さない or バージョン変更なし
        mock_k3s.return_value = None
        mock_maria.return_value = None
        mock_helm.return_value = []
        mock_images.return_value = []

        main()
        captured = capsys.readouterr()
        assert "バージョン変更なし" in captured.out
        mock_slack.assert_not_called()

    @patch("scanner.send_slack_notification")
    @patch("scanner.collect_container_images")
    @patch("scanner.collect_helm_releases")
    @patch("scanner.collect_mariadb_version")
    @patch("scanner.collect_k3s_version")
    @patch("scanner.upsert_record")
    @patch("scanner.ensure_table")
    @patch("scanner.get_conn")
    def test_k3s_version_change(self, mock_conn, mock_ensure, mock_upsert, mock_k3s, mock_maria, mock_helm, mock_images, mock_slack, capsys):
        conn = MagicMock()
        mock_conn.return_value = conn

        mock_k3s.return_value = "v1.32.0+k3s1"
        mock_maria.return_value = None
        mock_helm.return_value = []
        mock_images.return_value = []
        # upsert_record は古いバージョンを返す(=変更あり)
        mock_upsert.return_value = "v1.31.0+k3s1"

        main()
        captured = capsys.readouterr()
        assert "v1.31.0+k3s1" in captured.out
        assert "v1.32.0+k3s1" in captured.out
        mock_slack.assert_called_once()
        changes_arg = mock_slack.call_args[0][0]
        assert len(changes_arg) == 1
        assert changes_arg[0]["component"] == "k3s"

    @patch("scanner.send_slack_notification")
    @patch("scanner.collect_container_images")
    @patch("scanner.collect_helm_releases")
    @patch("scanner.collect_mariadb_version")
    @patch("scanner.collect_k3s_version")
    @patch("scanner.upsert_record")
    @patch("scanner.ensure_table")
    @patch("scanner.get_conn")
    def test_helm_release_change(self, mock_conn, mock_ensure, mock_upsert, mock_k3s, mock_maria, mock_helm, mock_images, mock_slack, capsys):
        conn = MagicMock()
        mock_conn.return_value = conn

        mock_k3s.return_value = None
        mock_maria.return_value = None
        mock_helm.return_value = [
            {"name": "mariadb", "namespace": "app", "chart": "mariadb-22.0.3", "app_version": "11.8.2"},
        ]
        mock_images.return_value = []
        # k3s/mariadb は None → 変更なし, helm は old version
        mock_upsert.return_value = "11.6.0"

        main()
        captured = capsys.readouterr()
        assert "11.6.0" in captured.out
        mock_slack.assert_called_once()

    @patch("scanner.send_slack_notification")
    @patch("scanner.collect_container_images")
    @patch("scanner.collect_helm_releases")
    @patch("scanner.collect_mariadb_version")
    @patch("scanner.collect_k3s_version")
    @patch("scanner.upsert_record")
    @patch("scanner.ensure_table")
    @patch("scanner.get_conn")
    def test_container_image_first_time_no_notify(self, mock_conn, mock_ensure, mock_upsert, mock_k3s, mock_maria, mock_helm, mock_images, mock_slack, capsys):
        """コンテナイメージの初回登録は通知しない"""
        conn = MagicMock()
        mock_conn.return_value = conn

        mock_k3s.return_value = None
        mock_maria.return_value = None
        mock_helm.return_value = []
        mock_images.return_value = ["nginx:1.25"]
        # upsert_record returns None = 新規
        mock_upsert.return_value = None

        main()
        captured = capsys.readouterr()
        assert "バージョン変更なし" in captured.out
        mock_slack.assert_not_called()

    @patch("scanner.send_slack_notification")
    @patch("scanner.collect_container_images")
    @patch("scanner.collect_helm_releases")
    @patch("scanner.collect_mariadb_version")
    @patch("scanner.collect_k3s_version")
    @patch("scanner.upsert_record")
    @patch("scanner.ensure_table")
    @patch("scanner.get_conn")
    def test_container_image_version_change(self, mock_conn, mock_ensure, mock_upsert, mock_k3s, mock_maria, mock_helm, mock_images, mock_slack, capsys):
        """コンテナイメージのバージョン変更は通知する"""
        conn = MagicMock()
        mock_conn.return_value = conn

        mock_k3s.return_value = None
        mock_maria.return_value = None
        mock_helm.return_value = []
        mock_images.return_value = ["nginx:1.26"]
        # upsert_record returns old version = 変更あり
        mock_upsert.return_value = "1.25"

        main()
        captured = capsys.readouterr()
        assert "1.25" in captured.out
        assert "1.26" in captured.out
        mock_slack.assert_called_once()

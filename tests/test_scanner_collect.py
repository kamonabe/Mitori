"""inventory-scan/scanner.py の収集ロジックテスト"""

import json
import os
from unittest.mock import MagicMock, patch

os.environ.setdefault("DB_HOST", "localhost")
os.environ.setdefault("DB_USER", "test")
os.environ.setdefault("DB_PASSWORD", "test")
os.environ.setdefault("DB_NAME", "test")

from scanner import (
    collect_container_images,
    collect_helm_releases,
    collect_k3s_version,
    collect_mariadb_version,
    run_cmd,
    upsert_record,
)


class TestRunCmd:
    """run_cmd のテスト"""

    @patch("scanner.subprocess.run")
    def test_success(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="hello\n")
        result = run_cmd(["echo", "hello"])
        assert result == "hello\n"

    @patch("scanner.subprocess.run")
    def test_nonzero_returncode(self, mock_run, capsys):
        mock_run.return_value = MagicMock(returncode=1, stderr="error msg")
        result = run_cmd(["bad", "cmd"])
        assert result is None
        captured = capsys.readouterr()
        assert "コマンド失敗" in captured.out

    @patch("scanner.subprocess.run")
    def test_timeout(self, mock_run, capsys):
        import subprocess

        mock_run.side_effect = subprocess.TimeoutExpired(cmd="test", timeout=30)
        result = run_cmd(["slow", "cmd"])
        assert result is None
        captured = capsys.readouterr()
        assert "タイムアウト" in captured.out

    @patch("scanner.subprocess.run")
    def test_generic_exception(self, mock_run, capsys):
        mock_run.side_effect = OSError("not found")
        result = run_cmd(["missing"])
        assert result is None
        captured = capsys.readouterr()
        assert "コマンド実行失敗" in captured.out


class TestCollectK3sVersion:
    """collect_k3s_version のテスト"""

    @patch("scanner.run_cmd")
    def test_success(self, mock_cmd):
        mock_cmd.return_value = json.dumps({"serverVersion": {"gitVersion": "v1.32.4+k3s1"}})
        result = collect_k3s_version()
        assert result == "v1.32.4+k3s1"

    @patch("scanner.run_cmd")
    def test_cmd_failure(self, mock_cmd):
        mock_cmd.return_value = None
        result = collect_k3s_version()
        assert result is None

    @patch("scanner.run_cmd")
    def test_invalid_json(self, mock_cmd, capsys):
        mock_cmd.return_value = "not json"
        result = collect_k3s_version()
        assert result is None
        captured = capsys.readouterr()
        assert "JSONパース失敗" in captured.out

    @patch("scanner.run_cmd")
    def test_empty_git_version(self, mock_cmd, capsys):
        mock_cmd.return_value = json.dumps({"serverVersion": {"gitVersion": ""}})
        result = collect_k3s_version()
        assert result is None
        captured = capsys.readouterr()
        assert "空" in captured.out


class TestCollectMariadbVersion:
    """collect_mariadb_version のテスト"""

    def test_success(self):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
        conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        cursor.fetchone.return_value = {"ver": "11.8.2-MariaDB"}
        result = collect_mariadb_version(conn)
        assert result == "11.8.2-MariaDB"

    def test_empty_result(self, capsys):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
        conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        cursor.fetchone.return_value = None
        result = collect_mariadb_version(conn)
        assert result is None
        captured = capsys.readouterr()
        assert "空" in captured.out

    def test_db_error(self, capsys):
        import pymysql

        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
        conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        cursor.execute.side_effect = pymysql.Error("connection lost")
        result = collect_mariadb_version(conn)
        assert result is None
        captured = capsys.readouterr()
        assert "バージョン取得失敗" in captured.out


class TestCollectHelmReleases:
    """collect_helm_releases のテスト"""

    @patch("scanner.run_cmd")
    def test_success(self, mock_cmd):
        releases = [
            {"name": "mariadb", "namespace": "app", "chart": "mariadb-22.0.3", "app_version": "11.8.2"},
            {"name": "loki", "namespace": "monitoring", "chart": "loki-6.30.0", "app_version": "3.4.0"},
        ]
        mock_cmd.return_value = json.dumps(releases)
        result = collect_helm_releases()
        assert len(result) == 2
        assert result[0]["name"] == "mariadb"

    @patch("scanner.run_cmd")
    def test_cmd_failure(self, mock_cmd):
        mock_cmd.return_value = None
        result = collect_helm_releases()
        assert result == []

    @patch("scanner.run_cmd")
    def test_invalid_json(self, mock_cmd, capsys):
        mock_cmd.return_value = "not json"
        result = collect_helm_releases()
        assert result == []
        captured = capsys.readouterr()
        assert "JSONパース失敗" in captured.out

    @patch("scanner.run_cmd")
    def test_non_list_output(self, mock_cmd, capsys):
        mock_cmd.return_value = json.dumps({"error": "something"})
        result = collect_helm_releases()
        assert result == []
        captured = capsys.readouterr()
        assert "リストではありません" in captured.out


class TestCollectContainerImages:
    """collect_container_images のテスト"""

    @patch("scanner.run_cmd")
    def test_success(self, mock_cmd):
        pods = {
            "items": [
                {
                    "spec": {
                        "containers": [{"image": "nginx:1.25"}],
                        "initContainers": [{"image": "busybox:1.36"}],
                    }
                },
                {
                    "spec": {
                        "containers": [{"image": "nginx:1.25"}, {"image": "redis:7.0"}],
                    }
                },
            ]
        }
        mock_cmd.return_value = json.dumps(pods)
        result = collect_container_images()
        # 重複除去されている
        assert sorted(result) == sorted(["nginx:1.25", "busybox:1.36", "redis:7.0"])

    @patch("scanner.run_cmd")
    def test_cmd_failure(self, mock_cmd):
        mock_cmd.return_value = None
        result = collect_container_images()
        assert result == []

    @patch("scanner.run_cmd")
    def test_invalid_json(self, mock_cmd, capsys):
        mock_cmd.return_value = "broken"
        result = collect_container_images()
        assert result == []
        captured = capsys.readouterr()
        assert "JSONパース失敗" in captured.out

    @patch("scanner.run_cmd")
    def test_empty_items(self, mock_cmd):
        mock_cmd.return_value = json.dumps({"items": []})
        result = collect_container_images()
        assert result == []


class TestUpsertRecord:
    """upsert_record の返値ロジックテスト"""

    def _make_conn(self, existing_version=None):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
        conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        if existing_version is None:
            cursor.fetchone.return_value = None
        else:
            cursor.fetchone.return_value = {"version": existing_version}
        return conn

    def test_new_record_returns_none(self):
        conn = self._make_conn(existing_version=None)
        result = upsert_record(conn, "k3s", "runtime", "v1.32.0")
        assert result is None

    def test_same_version_returns_false(self):
        conn = self._make_conn(existing_version="v1.32.0")
        result = upsert_record(conn, "k3s", "runtime", "v1.32.0")
        assert result is False

    def test_changed_version_returns_old(self):
        conn = self._make_conn(existing_version="v1.31.0")
        result = upsert_record(conn, "k3s", "runtime", "v1.32.0")
        assert result == "v1.31.0"

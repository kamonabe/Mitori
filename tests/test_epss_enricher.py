"""epss_enricher.py のテスト"""

import os
from unittest.mock import MagicMock, patch

os.environ.setdefault("DB_HOST", "localhost")
os.environ.setdefault("DB_USER", "test")
os.environ.setdefault("DB_PASSWORD", "test")
os.environ.setdefault("DB_NAME", "test")

from epss_enricher import fetch_epss_batch, get_open_cve_ids, main, upsert_epss_score


class TestFetchEpssBatch:
    """FIRST EPSS API 呼び出しテスト"""

    @patch("epss_enricher.requests.get")
    def test_successful_fetch(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "status": "OK",
            "total": 2,
            "data": [
                {"cve": "CVE-2024-0001", "epss": "0.850000000", "percentile": "0.990000000", "date": "2026-08-13"},
                {"cve": "CVE-2024-0002", "epss": "0.120000000", "percentile": "0.650000000", "date": "2026-08-13"},
            ],
        }
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        result = fetch_epss_batch(["CVE-2024-0001", "CVE-2024-0002"])
        assert len(result) == 2
        assert result[0]["cve"] == "CVE-2024-0001"
        assert result[0]["epss"] == "0.850000000"
        mock_get.assert_called_once()

    @patch("epss_enricher.requests.get")
    def test_fetch_timeout(self, mock_get):
        import requests

        mock_get.side_effect = requests.Timeout("timeout")

        import pytest

        with pytest.raises(requests.RequestException):
            fetch_epss_batch(["CVE-2024-0001"])

    @patch("epss_enricher.requests.get")
    def test_empty_response(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"status": "OK", "total": 0, "data": []}
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        result = fetch_epss_batch(["CVE-9999-0001"])
        assert result == []


class TestGetOpenCveIds:
    """open CVE ID 取得テスト"""

    def test_returns_distinct_cve_ids(self):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
        conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        cursor.fetchall.return_value = [
            {"cve_id": "CVE-2024-0001"},
            {"cve_id": "CVE-2024-0002"},
        ]

        result = get_open_cve_ids(conn)
        assert result == ["CVE-2024-0001", "CVE-2024-0002"]

    def test_empty_result(self):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
        conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        cursor.fetchall.return_value = []

        result = get_open_cve_ids(conn)
        assert result == []


class TestUpsertEpssScore:
    """UPSERT テスト"""

    def test_upsert_calls_execute_and_commit(self):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
        conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        upsert_epss_score(conn, "CVE-2024-0001", "0.85", "0.99", "2026-08-13")
        cursor.execute.assert_called_once()
        conn.commit.assert_called_once()


class TestMain:
    """main() フローテスト"""

    @patch("epss_enricher.get_conn")
    def test_db_connection_failure(self, mock_conn, capsys):
        import pymysql

        mock_conn.side_effect = pymysql.Error("connection refused")
        main()
        captured = capsys.readouterr()
        assert "DB接続失敗" in captured.out

    @patch("epss_enricher.get_open_cve_ids")
    @patch("epss_enricher.get_conn")
    def test_no_open_cves(self, mock_conn, mock_get_ids, capsys):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
        conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.return_value = conn
        mock_get_ids.return_value = []

        main()
        captured = capsys.readouterr()
        assert "対象CVEなし" in captured.out

    @patch("epss_enricher.fetch_epss_batch")
    @patch("epss_enricher.get_open_cve_ids")
    @patch("epss_enricher.get_conn")
    def test_successful_enrichment(self, mock_conn, mock_get_ids, mock_fetch, capsys):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
        conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.return_value = conn

        mock_get_ids.return_value = ["CVE-2024-0001", "CVE-2024-0002"]
        mock_fetch.return_value = [
            {"cve": "CVE-2024-0001", "epss": "0.85", "percentile": "0.99", "date": "2026-08-13"},
            {"cve": "CVE-2024-0002", "epss": "0.12", "percentile": "0.65", "date": "2026-08-13"},
        ]

        main()
        captured = capsys.readouterr()
        assert "2件更新" in captured.out
        assert "0件スキップ" in captured.out

    @patch("epss_enricher.fetch_epss_batch")
    @patch("epss_enricher.get_open_cve_ids")
    @patch("epss_enricher.get_conn")
    def test_api_failure_graceful(self, mock_conn, mock_get_ids, mock_fetch, capsys):
        import requests

        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
        conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.return_value = conn

        mock_get_ids.return_value = ["CVE-2024-0001"]
        mock_fetch.side_effect = requests.RequestException("network error")

        main()
        captured = capsys.readouterr()
        assert "EPSS API 呼び出し失敗" in captured.out
        assert "0件更新" in captured.out

    @patch("epss_enricher.fetch_epss_batch")
    @patch("epss_enricher.get_open_cve_ids")
    @patch("epss_enricher.get_conn")
    def test_partial_response_counts_skipped(self, mock_conn, mock_get_ids, mock_fetch, capsys):
        """APIにデータがないCVEはスキップとしてカウントされる."""
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
        conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.return_value = conn

        mock_get_ids.return_value = ["CVE-2024-0001", "CVE-2024-0002"]
        # API only returns data for one CVE
        mock_fetch.return_value = [
            {"cve": "CVE-2024-0001", "epss": "0.85", "percentile": "0.99", "date": "2026-08-13"},
        ]

        main()
        captured = capsys.readouterr()
        assert "1件更新" in captured.out
        assert "1件スキップ" in captured.out

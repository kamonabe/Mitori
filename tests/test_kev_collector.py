"""kev_collector.py のテスト"""

import os
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("DB_HOST", "localhost")
os.environ.setdefault("DB_USER", "test")
os.environ.setdefault("DB_PASSWORD", "test")
os.environ.setdefault("DB_NAME", "test")

from kev_collector import fetch_kev_catalog, main


class TestFetchKevCatalog:
    """CISA KEV カタログ取得テスト"""

    @patch("kev_collector.requests.get")
    def test_successful_fetch(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "catalogVersion": "2026.08.11",
            "count": 2,
            "vulnerabilities": [
                {"cveID": "CVE-2026-0001", "vendorProject": "TestVendor"},
                {"cveID": "CVE-2026-0002", "vendorProject": "TestVendor2"},
            ],
        }
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        result = fetch_kev_catalog()
        assert result["catalogVersion"] == "2026.08.11"
        assert len(result["vulnerabilities"]) == 2
        mock_get.assert_called_once()

    @patch("kev_collector.requests.get")
    def test_fetch_timeout(self, mock_get):
        import requests

        mock_get.side_effect = requests.Timeout("timeout")

        with pytest.raises(requests.RequestException):
            fetch_kev_catalog()

    @patch("kev_collector.requests.get")
    def test_fetch_http_error(self, mock_get):
        import requests

        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = requests.HTTPError("500 Server Error")
        mock_get.return_value = mock_resp

        with pytest.raises(requests.RequestException):
            fetch_kev_catalog()


class TestMain:
    """main() フローテスト"""

    @patch("kev_collector.get_conn")
    def test_db_connection_failure(self, mock_conn, capsys):
        import pymysql

        mock_conn.side_effect = pymysql.Error("connection refused")
        main()
        captured = capsys.readouterr()
        assert "DB接続失敗" in captured.out

    @patch("kev_collector.fetch_kev_catalog")
    @patch("kev_collector.get_conn")
    def test_api_failure(self, mock_conn, mock_fetch, capsys):
        import requests

        conn = MagicMock()
        mock_conn.return_value = conn
        mock_fetch.side_effect = requests.RequestException("network error")

        main()
        captured = capsys.readouterr()
        assert "KEV カタログ取得失敗" in captured.out
        conn.close.assert_called_once()

    @patch("kev_collector.fetch_kev_catalog")
    @patch("kev_collector.get_conn")
    def test_successful_insert(self, mock_conn, mock_fetch, capsys):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
        conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        # rowcount=1 means new insert
        cursor.rowcount = 1
        mock_conn.return_value = conn

        mock_fetch.return_value = {
            "catalogVersion": "2026.08.11",
            "vulnerabilities": [
                {
                    "cveID": "CVE-2026-0001",
                    "vendorProject": "Cisco",
                    "product": "ASA",
                    "vulnerabilityName": "Test Vuln",
                    "shortDescription": "A test vulnerability",
                    "requiredAction": "Apply patch",
                    "dateAdded": "2026-08-11",
                    "dueDate": "2026-08-14",
                    "knownRansomwareCampaignUse": "Unknown",
                    "cwes": ["CWE-244"],
                    "notes": "",
                },
            ],
        }

        main()
        captured = capsys.readouterr()
        assert "1件取得" in captured.out
        assert "1件が新規追加" in captured.out

    @patch("kev_collector.fetch_kev_catalog")
    @patch("kev_collector.get_conn")
    def test_duplicate_insert_ignored(self, mock_conn, mock_fetch, capsys):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
        conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        # rowcount=0 means INSERT IGNORE skipped (duplicate)
        cursor.rowcount = 0
        mock_conn.return_value = conn

        mock_fetch.return_value = {
            "catalogVersion": "2026.08.11",
            "vulnerabilities": [
                {
                    "cveID": "CVE-2026-0001",
                    "vendorProject": "Cisco",
                    "product": "ASA",
                    "vulnerabilityName": "Test Vuln",
                    "shortDescription": "Desc",
                    "requiredAction": "Patch",
                    "dateAdded": "2026-08-11",
                    "dueDate": "2026-08-14",
                    "knownRansomwareCampaignUse": "Unknown",
                    "cwes": [],
                    "notes": "",
                },
            ],
        }

        main()
        captured = capsys.readouterr()
        assert "1件取得" in captured.out
        assert "0件が新規追加" in captured.out

    @patch("kev_collector.fetch_kev_catalog")
    @patch("kev_collector.get_conn")
    def test_empty_cve_id_skipped(self, mock_conn, mock_fetch, capsys):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
        conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.return_value = conn

        mock_fetch.return_value = {
            "catalogVersion": "2026.08.11",
            "vulnerabilities": [
                {
                    "cveID": "",
                    "vendorProject": "X",
                    "product": "Y",
                    "vulnerabilityName": "No CVE",
                    "shortDescription": "",
                    "requiredAction": "",
                    "dateAdded": "2026-08-11",
                    "dueDate": None,
                    "knownRansomwareCampaignUse": "Unknown",
                    "cwes": [],
                    "notes": "",
                },
            ],
        }

        main()
        captured = capsys.readouterr()
        assert "0件が新規追加" in captured.out

"""cve_watch.py のOSV API・DB操作ロジックテスト"""

import json
import os
from unittest.mock import MagicMock, patch

os.environ.setdefault("DB_HOST", "localhost")
os.environ.setdefault("DB_USER", "test")
os.environ.setdefault("DB_PASSWORD", "test")
os.environ.setdefault("DB_NAME", "test")

from cve_watch import query_osv


class TestQueryOsv:
    """query_osv のテスト"""

    @patch("cve_watch.requests.post")
    def test_success_with_vulns(self, mock_post):
        vulns = [{"id": "GHSA-1234", "summary": "test vuln"}]
        mock_post.return_value = MagicMock(status_code=200, json=MagicMock(return_value={"vulns": vulns}))
        result = query_osv("Go", "github.com/example/pkg", "1.0.0")
        assert len(result) == 1
        assert result[0]["id"] == "GHSA-1234"

    @patch("cve_watch.requests.post")
    def test_success_no_vulns(self, mock_post):
        mock_post.return_value = MagicMock(status_code=200, json=MagicMock(return_value={}))
        result = query_osv("Go", "github.com/example/pkg", "2.0.0")
        assert result == []

    @patch("cve_watch.requests.post")
    def test_non_200_status(self, mock_post, capsys):
        mock_post.return_value = MagicMock(status_code=500)
        result = query_osv("Go", "github.com/example/pkg", "1.0.0")
        assert result == []
        captured = capsys.readouterr()
        assert "500" in captured.out

    @patch("cve_watch.requests.post")
    def test_request_exception(self, mock_post, capsys):
        import requests as req

        mock_post.side_effect = req.RequestException("timeout")
        result = query_osv("Go", "github.com/example/pkg", "1.0.0")
        assert result == []
        captured = capsys.readouterr()
        assert "リクエスト失敗" in captured.out

    @patch("cve_watch.requests.post")
    def test_json_decode_error(self, mock_post, capsys):
        resp = MagicMock(status_code=200)
        resp.json.side_effect = json.JSONDecodeError("err", "", 0)
        mock_post.return_value = resp
        result = query_osv("Go", "github.com/example/pkg", "1.0.0")
        assert result == []
        captured = capsys.readouterr()
        assert "パース失敗" in captured.out

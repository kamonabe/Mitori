"""cve_watch.py のDB操作ロジックテスト"""

import os
from unittest.mock import MagicMock

os.environ.setdefault("DB_HOST", "localhost")
os.environ.setdefault("DB_USER", "test")
os.environ.setdefault("DB_PASSWORD", "test")
os.environ.setdefault("DB_NAME", "test")

from cve_watch import (
    get_existing_cve,
    get_package_mapping,
    insert_cve,
    resolve_cve,
    update_cve_fixed,
    update_cve_severity,
)


def _make_conn(fetchone_return=None):
    conn = MagicMock()
    cursor = MagicMock()
    conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
    conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    cursor.fetchone.return_value = fetchone_return
    return conn, cursor


class TestGetExistingCve:
    """get_existing_cve のテスト"""

    def test_returns_row_when_found(self):
        row = {"osv_id": "GHSA-1234", "component": "pkg", "category": "container", "severity": "HIGH"}
        conn, cursor = _make_conn(row)
        result = get_existing_cve(conn, "GHSA-1234", "pkg", "container")
        assert result == row

    def test_returns_none_when_not_found(self):
        conn, cursor = _make_conn(None)
        result = get_existing_cve(conn, "GHSA-9999", "pkg", "container")
        assert result is None


class TestInsertCve:
    """insert_cve のテスト"""

    def test_inserts_record(self):
        conn, cursor = _make_conn()
        record = {
            "cve_id": "CVE-2024-12345",
            "osv_id": "GHSA-1234",
            "component": "github.com/example/pkg",
            "category": "container",
            "severity": "HIGH",
            "cvss_score": None,
            "cvss_vector": "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H",
            "summary": "Test vulnerability",
            "fixed_version": "1.2.3",
        }
        insert_cve(conn, record)
        cursor.execute.assert_called_once()
        conn.commit.assert_called_once()
        # SQL に INSERT INTO cve_entries が含まれる
        sql = cursor.execute.call_args[0][0]
        assert "INSERT INTO cve_entries" in sql


class TestUpdateCveFixed:
    """update_cve_fixed のテスト"""

    def test_updates_fixed_version(self):
        conn, cursor = _make_conn()
        update_cve_fixed(conn, "GHSA-1234", "pkg", "container", "2.0.0")
        cursor.execute.assert_called_once()
        conn.commit.assert_called_once()
        args = cursor.execute.call_args[0][1]
        assert args[0] == "2.0.0"


class TestUpdateCveSeverity:
    """update_cve_severity のテスト"""

    def test_updates_severity(self):
        conn, cursor = _make_conn()
        update_cve_severity(conn, "GHSA-1234", "pkg", "container", "CRITICAL", 9.8, "CVSS:3.1/...")
        cursor.execute.assert_called_once()
        conn.commit.assert_called_once()
        args = cursor.execute.call_args[0][1]
        assert args[0] == "CRITICAL"


class TestResolveCve:
    """resolve_cve のテスト"""

    def test_marks_resolved(self):
        conn, cursor = _make_conn()
        resolve_cve(conn, "GHSA-1234", "pkg", "container")
        cursor.execute.assert_called_once()
        conn.commit.assert_called_once()
        sql = cursor.execute.call_args[0][0]
        assert "resolved" in sql


class TestGetPackageMapping:
    """get_package_mapping のテスト"""

    def test_returns_mapping(self):
        row = {"osv_ecosystem": "Go", "osv_package_name": "github.com/example/pkg"}
        conn, cursor = _make_conn(row)
        result = get_package_mapping(conn, "example-pkg", "container")
        assert result["osv_ecosystem"] == "Go"

    def test_returns_none_when_no_mapping(self):
        conn, cursor = _make_conn(None)
        result = get_package_mapping(conn, "unmapped", "container")
        assert result is None

"""normalizer.py の upsert ロジックテスト"""

import os
from unittest.mock import MagicMock, patch

os.environ.setdefault("DB_HOST", "localhost")
os.environ.setdefault("DB_USER", "test")
os.environ.setdefault("DB_PASSWORD", "test")
os.environ.setdefault("DB_NAME", "test")

from normalizer import (
    compute_hash,
    sync_tactic_map,
    upsert_tactic,
    upsert_technique,
)


def _make_conn(fetchone_returns):
    """cursor.fetchone の戻り値リストを受け取って mock conn を作る"""
    conn = MagicMock()
    cursor = MagicMock()
    conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
    conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    cursor.fetchone.side_effect = fetchone_returns
    cursor.fetchall.return_value = []
    return conn, cursor


class TestUpsertTactic:
    """upsert_tactic のテスト"""

    def _sample_tactic(self, **overrides):
        base = {
            "stix_id": "x-mitre-tactic--test-123",
            "tactic_key": "initial-access",
            "external_id": "TA0001",
            "name": "Initial Access",
            "description": "desc",
            "is_deprecated": False,
            "stix_modified": "2025-10-25T14:00:00.000Z",
        }
        base.update(overrides)
        return base

    def test_insert_new_tactic(self):
        """既存レコードなし → INSERT → added イベントを返す"""
        conn, cursor = _make_conn([None])  # SELECT returns None
        n = self._sample_tactic()
        event = upsert_tactic(conn, n)
        assert event is not None
        assert event["action"] == "added"
        assert event["external_id"] == "TA0001"
        conn.commit.assert_called()

    def test_no_change_same_hash(self):
        """既存レコードのハッシュが一致 → None を返す"""
        n = self._sample_tactic()
        content_hash = compute_hash(n)
        conn, cursor = _make_conn([{"id": 1, "content_hash": content_hash, "is_deprecated": False}])
        event = upsert_tactic(conn, n)
        assert event is None

    def test_update_content_changed(self):
        """ハッシュ不一致 → UPDATE → updated イベント"""
        n = self._sample_tactic(name="Updated Access")
        conn, cursor = _make_conn([{"id": 1, "content_hash": "old-hash", "is_deprecated": False}])
        event = upsert_tactic(conn, n)
        assert event is not None
        assert event["action"] == "updated"
        conn.commit.assert_called()

    def test_deprecated_transition(self):
        """既存がdeprecated=False、新がdeprecated=True → deprecated イベント"""
        n = self._sample_tactic(is_deprecated=True)
        conn, cursor = _make_conn([{"id": 1, "content_hash": "old-hash", "is_deprecated": False}])
        event = upsert_tactic(conn, n)
        assert event["action"] == "deprecated"


class TestUpsertTechnique:
    """upsert_technique のテスト"""

    def _sample_technique(self, **overrides):
        base = {
            "stix_id": "attack-pattern--test-456",
            "external_id": "T1566",
            "parent_external_id": None,
            "name": "Phishing",
            "description": "desc",
            "is_subtechnique": False,
            "is_deprecated": False,
            "is_revoked": False,
            "stix_modified": "2025-11-01T10:30:00.000Z",
            "tactic_keys": ["initial-access"],
        }
        base.update(overrides)
        return base

    @patch("normalizer.sync_tactic_map")
    def test_insert_new_technique(self, mock_sync):
        """既存レコードなし → INSERT → added イベント"""
        conn, cursor = _make_conn([None, {"id": 99}])  # SELECT existing=None, then SELECT id
        n = self._sample_technique()
        event = upsert_technique(conn, n)
        assert event is not None
        assert event["action"] == "added"
        assert event["external_id"] == "T1566"
        mock_sync.assert_called_once_with(conn, 99, ["initial-access"])

    @patch("normalizer.sync_tactic_map")
    def test_no_change(self, mock_sync):
        """ハッシュ一致 → None"""
        n = self._sample_technique()
        content_hash = compute_hash({k: v for k, v in n.items() if k != "tactic_keys"})
        conn, cursor = _make_conn([
            {"id": 1, "content_hash": content_hash, "is_deprecated": False, "is_revoked": False},
            {"id": 1},  # SELECT id
        ])
        event = upsert_technique(conn, n)
        assert event is None
        mock_sync.assert_called_once()

    @patch("normalizer.sync_tactic_map")
    def test_update_technique(self, mock_sync):
        """ハッシュ不一致 → UPDATE → updated"""
        n = self._sample_technique(name="Updated Phishing")
        conn, cursor = _make_conn([
            {"id": 1, "content_hash": "old-hash", "is_deprecated": False, "is_revoked": False},
            {"id": 1},
        ])
        event = upsert_technique(conn, n)
        assert event["action"] == "updated"

    @patch("normalizer.sync_tactic_map")
    def test_deprecated_transition(self, mock_sync):
        """deprecated 遷移"""
        n = self._sample_technique(is_deprecated=True)
        conn, cursor = _make_conn([
            {"id": 1, "content_hash": "old-hash", "is_deprecated": False, "is_revoked": False},
            {"id": 1},
        ])
        event = upsert_technique(conn, n)
        assert event["action"] == "deprecated"

    @patch("normalizer.sync_tactic_map")
    def test_revoked_transition(self, mock_sync):
        """revoked 遷移"""
        n = self._sample_technique(is_revoked=True)
        conn, cursor = _make_conn([
            {"id": 1, "content_hash": "old-hash", "is_deprecated": False, "is_revoked": False},
            {"id": 1},
        ])
        event = upsert_technique(conn, n)
        assert event["action"] == "revoked"


class TestSyncTacticMap:
    """sync_tactic_map のテスト"""

    def test_empty_tactic_keys_deletes_all(self):
        conn, cursor = _make_conn([])
        sync_tactic_map(conn, technique_id=1, tactic_keys=[])
        # DELETE が呼ばれる
        assert any("DELETE" in str(c) for c in cursor.execute.call_args_list)
        conn.commit.assert_called()

    def test_inserts_mapped_tactics(self):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
        conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        cursor.fetchall.return_value = [
            {"id": 10, "tactic_key": "initial-access"},
            {"id": 20, "tactic_key": "execution"},
        ]

        sync_tactic_map(conn, technique_id=1, tactic_keys=["initial-access", "execution"])

        # DELETE existing + 2 INSERT IGNORE calls
        execute_calls = [str(c) for c in cursor.execute.call_args_list]
        insert_calls = [c for c in execute_calls if "INSERT IGNORE" in c]
        assert len(insert_calls) == 2
        conn.commit.assert_called()

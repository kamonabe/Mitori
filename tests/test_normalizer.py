"""normalizer.py のロジックテスト"""
import json
import hashlib
from datetime import datetime, timezone

from normalizer import (
    compute_hash,
    normalize_tactic,
    normalize_technique,
    get_mitre_external_id,
    parse_dt,
    build_category_block,
    NOTIFY_MAX_ITEMS,
)


class TestComputeHash:
    """compute_hash のテスト"""

    def test_same_input_same_hash(self):
        data = {"name": "Test", "id": "123"}
        assert compute_hash(data) == compute_hash(data)

    def test_key_order_does_not_matter(self):
        """dict のキー順序が違っても同じハッシュになる（sort_keys=True のため）"""
        data1 = {"b": 2, "a": 1}
        data2 = {"a": 1, "b": 2}
        assert compute_hash(data1) == compute_hash(data2)

    def test_different_input_different_hash(self):
        data1 = {"name": "A"}
        data2 = {"name": "B"}
        assert compute_hash(data1) != compute_hash(data2)

    def test_hash_is_sha256_hex(self):
        data = {"test": "value"}
        result = compute_hash(data)
        assert len(result) == 64
        assert all(c in "0123456789abcdef" for c in result)

    def test_unicode_handling(self):
        """日本語を含むデータでもハッシュが計算できる"""
        data = {"name": "初期アクセス", "description": "テスト"}
        result = compute_hash(data)
        # 手動計算と一致するか確認
        expected = hashlib.sha256(
            json.dumps(data, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()
        assert result == expected


class TestGetMitreExternalId:
    """get_mitre_external_id のテスト"""

    def test_returns_id_when_present(self, sample_tactic_stix):
        assert get_mitre_external_id(sample_tactic_stix) == "TA0001"

    def test_returns_none_when_no_mitre_source(self):
        obj = {
            "external_references": [
                {"source_name": "other-source", "external_id": "X999"}
            ]
        }
        assert get_mitre_external_id(obj) is None

    def test_returns_none_when_no_references(self):
        obj = {}
        assert get_mitre_external_id(obj) is None

    def test_returns_none_when_empty_references(self):
        obj = {"external_references": []}
        assert get_mitre_external_id(obj) is None


class TestParseDt:
    """parse_dt のテスト"""

    def test_zulu_format(self):
        result = parse_dt("2025-10-25T14:00:00.000Z")
        assert result.year == 2025
        assert result.month == 10
        assert result.day == 25
        assert result.hour == 14
        assert result.tzinfo is not None

    def test_offset_format(self):
        result = parse_dt("2025-10-25T14:00:00+00:00")
        assert result.tzinfo is not None

    def test_without_milliseconds(self):
        result = parse_dt("2025-10-25T14:00:00Z")
        assert result.hour == 14


class TestNormalizeTactic:
    """normalize_tactic のテスト"""

    def test_basic_normalization(self, sample_tactic_stix):
        result = normalize_tactic(sample_tactic_stix)
        assert result is not None
        assert result["stix_id"] == "x-mitre-tactic--2558fd61-8c75-4730-94c4-11926db2a263"
        assert result["tactic_key"] == "initial-access"
        assert result["external_id"] == "TA0001"
        assert result["name"] == "Initial Access"
        assert result["is_deprecated"] is False
        assert result["stix_modified"] == "2025-10-25T14:00:00.000Z"

    def test_returns_none_without_external_id(self):
        obj = {
            "id": "x-mitre-tactic--xxx",
            "type": "x-mitre-tactic",
            "name": "No Ref",
            "external_references": [{"source_name": "other", "external_id": "X1"}],
            "x_mitre_shortname": "no-ref",
            "modified": "2025-01-01T00:00:00Z",
        }
        assert normalize_tactic(obj) is None

    def test_deprecated_tactic(self, sample_tactic_stix):
        sample_tactic_stix["x_mitre_deprecated"] = True
        result = normalize_tactic(sample_tactic_stix)
        assert result["is_deprecated"] is True


class TestNormalizeTechnique:
    """normalize_technique のテスト"""

    def test_basic_technique(self, sample_technique_stix):
        result = normalize_technique(sample_technique_stix)
        assert result is not None
        assert result["external_id"] == "T1566"
        assert result["parent_external_id"] is None
        assert result["is_subtechnique"] is False
        assert result["tactic_keys"] == ["initial-access"]
        assert result["name"] == "Phishing"

    def test_subtechnique_parent_extraction(self, sample_subtechnique_stix):
        result = normalize_technique(sample_subtechnique_stix)
        assert result is not None
        assert result["external_id"] == "T1566.001"
        assert result["parent_external_id"] == "T1566"
        assert result["is_subtechnique"] is True

    def test_multiple_tactic_keys(self, sample_technique_stix):
        """複数の kill_chain_phases がある場合、全てのtactic_keyが含まれる"""
        sample_technique_stix["kill_chain_phases"] = [
            {"kill_chain_name": "mitre-attack", "phase_name": "initial-access"},
            {"kill_chain_name": "mitre-attack", "phase_name": "execution"},
        ]
        result = normalize_technique(sample_technique_stix)
        assert result["tactic_keys"] == ["execution", "initial-access"]  # sorted

    def test_non_mitre_kill_chain_ignored(self, sample_technique_stix):
        """mitre-attack 以外の kill_chain は無視される"""
        sample_technique_stix["kill_chain_phases"] = [
            {"kill_chain_name": "mitre-attack", "phase_name": "initial-access"},
            {"kill_chain_name": "lockheed-martin", "phase_name": "reconnaissance"},
        ]
        result = normalize_technique(sample_technique_stix)
        assert result["tactic_keys"] == ["initial-access"]

    def test_returns_none_without_external_id(self):
        obj = {
            "id": "attack-pattern--xxx",
            "type": "attack-pattern",
            "name": "No Ref",
            "external_references": [],
            "kill_chain_phases": [],
            "modified": "2025-01-01T00:00:00Z",
        }
        assert normalize_technique(obj) is None

    def test_revoked_technique(self, sample_technique_stix):
        sample_technique_stix["revoked"] = True
        result = normalize_technique(sample_technique_stix)
        assert result["is_revoked"] is True

    def test_deprecated_technique(self, sample_technique_stix):
        sample_technique_stix["x_mitre_deprecated"] = True
        result = normalize_technique(sample_technique_stix)
        assert result["is_deprecated"] is True


class TestBuildCategoryBlock:
    """build_category_block のテスト"""

    def test_single_event(self):
        events = [{"external_id": "T1234", "name": "Test Technique"}]
        result = build_category_block(":new: 新規追加", events)
        assert "1件" in result
        assert "T1234" in result
        assert "Test Technique" in result

    def test_max_items_not_exceeded(self):
        events = [
            {"external_id": f"T{i}", "name": f"Technique {i}"}
            for i in range(NOTIFY_MAX_ITEMS)
        ]
        result = build_category_block(":new: 新規追加", events)
        assert "上記も含め" not in result

    def test_max_items_exceeded(self):
        events = [
            {"external_id": f"T{i}", "name": f"Technique {i}"}
            for i in range(NOTIFY_MAX_ITEMS + 3)
        ]
        result = build_category_block(":new: 新規追加", events)
        assert f"{NOTIFY_MAX_ITEMS + 3}件の変更を検知しました" in result
        # 最初の NOTIFY_MAX_ITEMS 件は個別列挙される
        for i in range(NOTIFY_MAX_ITEMS):
            assert f"T{i}" in result
        # 超えた分は列挙されない
        assert f"T{NOTIFY_MAX_ITEMS + 2}" not in result

    def test_empty_events(self):
        """空リストでも例外なく動作する"""
        result = build_category_block(":new: 新規追加", [])
        assert "0件" in result

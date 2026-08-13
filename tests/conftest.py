"""共通fixture: サンプルSTIXオブジェクト等"""

import sys
from pathlib import Path

import pytest

# common/ ライブラリを import パスに追加
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "common"))
# eol-watch ディレクトリを import パスに追加
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "eol-watch"))
# cve-watch ディレクトリを import パスに追加
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "cve-watch"))
# epss ディレクトリを import パスに追加
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "epss"))
# mitre/ ディレクトリを import パスに追加（collector.py の名前衝突を避けるため最後に insert=先頭）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "mitre"))


@pytest.fixture
def sample_tactic_stix():
    """x-mitre-tactic 型の STIX オブジェクトサンプル"""
    return {
        "id": "x-mitre-tactic--2558fd61-8c75-4730-94c4-11926db2a263",
        "type": "x-mitre-tactic",
        "name": "Initial Access",
        "description": "The adversary is trying to get into your network.",
        "x_mitre_shortname": "initial-access",
        "external_references": [
            {"source_name": "mitre-attack", "external_id": "TA0001", "url": "https://attack.mitre.org/tactics/TA0001"}
        ],
        "modified": "2025-10-25T14:00:00.000Z",
        "x_mitre_deprecated": False,
    }


@pytest.fixture
def sample_technique_stix():
    """attack-pattern 型の STIX オブジェクトサンプル（テクニック）"""
    return {
        "id": "attack-pattern--a62a8db3-f23a-4d8f-afd6-9dbc77e7813b",
        "type": "attack-pattern",
        "name": "Phishing",
        "description": "Adversaries may send phishing messages.",
        "x_mitre_is_subtechnique": False,
        "x_mitre_deprecated": False,
        "revoked": False,
        "kill_chain_phases": [{"kill_chain_name": "mitre-attack", "phase_name": "initial-access"}],
        "external_references": [
            {"source_name": "mitre-attack", "external_id": "T1566", "url": "https://attack.mitre.org/techniques/T1566"}
        ],
        "modified": "2025-11-01T10:30:00.000Z",
    }


@pytest.fixture
def sample_subtechnique_stix():
    """attack-pattern 型の STIX オブジェクトサンプル（サブテクニック）"""
    return {
        "id": "attack-pattern--sub-1234-5678",
        "type": "attack-pattern",
        "name": "Spearphishing Attachment",
        "description": "A sub-technique of Phishing.",
        "x_mitre_is_subtechnique": True,
        "x_mitre_deprecated": False,
        "revoked": False,
        "kill_chain_phases": [{"kill_chain_name": "mitre-attack", "phase_name": "initial-access"}],
        "external_references": [
            {
                "source_name": "mitre-attack",
                "external_id": "T1566.001",
                "url": "https://attack.mitre.org/techniques/T1566/001",
            }
        ],
        "modified": "2025-11-02T08:00:00.000Z",
    }

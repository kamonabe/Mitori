"""normalizer.py の main フローテスト"""

import json
import os
from unittest.mock import MagicMock, patch

os.environ.setdefault("DB_HOST", "localhost")
os.environ.setdefault("DB_USER", "test")
os.environ.setdefault("DB_PASSWORD", "test")
os.environ.setdefault("DB_NAME", "test")

from normalizer import main


class TestMain:
    """main フローテスト"""

    @patch("normalizer.get_conn")
    def test_db_connection_failure(self, mock_conn, capsys):
        import pymysql

        mock_conn.side_effect = pymysql.Error("connection refused")
        main()
        captured = capsys.readouterr()
        assert "DB接続失敗" in captured.out

    @patch("normalizer.fetch_unprocessed")
    @patch("normalizer.get_conn")
    def test_no_unprocessed_data(self, mock_conn, mock_fetch, capsys):
        mock_conn.return_value = MagicMock()
        mock_fetch.return_value = []
        main()
        captured = capsys.readouterr()
        assert "No unprocessed data" in captured.out

    @patch("normalizer.notify_slack")
    @patch("normalizer.update_schedule")
    @patch("normalizer.cleanup_old_processed")
    @patch("normalizer.mark_processed")
    @patch("normalizer.upsert_technique")
    @patch("normalizer.upsert_tactic")
    @patch("normalizer.fetch_unprocessed")
    @patch("normalizer.get_conn")
    def test_processes_tactic_and_technique(
        self,
        mock_conn,
        mock_fetch,
        mock_upsert_tactic,
        mock_upsert_tech,
        mock_mark,
        mock_cleanup,
        mock_schedule,
        mock_notify,
        capsys,
    ):
        mock_conn.return_value = MagicMock()

        tactic_obj = {
            "type": "x-mitre-tactic",
            "id": "x-mitre-tactic--test",
            "name": "Test Tactic",
            "x_mitre_shortname": "test",
            "external_references": [{"source_name": "mitre-attack", "external_id": "TA9999"}],
            "modified": "2025-01-01T00:00:00Z",
        }
        technique_obj = {
            "type": "attack-pattern",
            "id": "attack-pattern--test",
            "name": "Test Technique",
            "x_mitre_is_subtechnique": False,
            "kill_chain_phases": [{"kill_chain_name": "mitre-attack", "phase_name": "test"}],
            "external_references": [{"source_name": "mitre-attack", "external_id": "T9999"}],
            "modified": "2025-01-01T00:00:00Z",
        }
        other_obj = {"type": "relationship", "id": "rel--test"}

        mock_fetch.return_value = [
            {"id": 1, "raw_json": json.dumps(tactic_obj)},
            {"id": 2, "raw_json": json.dumps(technique_obj)},
            {"id": 3, "raw_json": json.dumps(other_obj)},
        ]
        mock_upsert_tactic.return_value = {
            "type": "tactic",
            "action": "added",
            "external_id": "TA9999",
            "name": "Test Tactic",
        }
        mock_upsert_tech.return_value = {
            "type": "technique",
            "action": "added",
            "external_id": "T9999",
            "name": "Test Technique",
        }

        main()

        mock_upsert_tactic.assert_called_once()
        mock_upsert_tech.assert_called_once()
        mock_mark.assert_called_once_with(mock_conn.return_value, [1, 2, 3])
        mock_cleanup.assert_called_once()
        mock_schedule.assert_called_once_with(mock_conn.return_value, True)
        mock_notify.assert_called_once()
        events = mock_notify.call_args[0][0]
        assert len(events) == 2

        captured = capsys.readouterr()
        assert "had_changes=True" in captured.out

    @patch("normalizer.notify_slack")
    @patch("normalizer.update_schedule")
    @patch("normalizer.cleanup_old_processed")
    @patch("normalizer.mark_processed")
    @patch("normalizer.upsert_tactic")
    @patch("normalizer.fetch_unprocessed")
    @patch("normalizer.get_conn")
    def test_no_changes_detected(
        self, mock_conn, mock_fetch, mock_upsert_tactic, mock_mark, mock_cleanup, mock_schedule, mock_notify, capsys
    ):
        mock_conn.return_value = MagicMock()

        tactic_obj = {
            "type": "x-mitre-tactic",
            "id": "x-mitre-tactic--test",
            "name": "Unchanged",
            "x_mitre_shortname": "unchanged",
            "external_references": [{"source_name": "mitre-attack", "external_id": "TA0001"}],
            "modified": "2025-01-01T00:00:00Z",
        }
        mock_fetch.return_value = [{"id": 1, "raw_json": json.dumps(tactic_obj)}]
        mock_upsert_tactic.return_value = None  # 変更なし

        main()

        mock_schedule.assert_called_once_with(mock_conn.return_value, False)
        # notify_slack は空リストで呼ばれる
        mock_notify.assert_called_once_with([])

        captured = capsys.readouterr()
        assert "had_changes=False" in captured.out

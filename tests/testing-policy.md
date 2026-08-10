# テスト方針

最終更新: 2026-08-10

## 1. 基本方針

「壊れたら困る純粋ロジック」にだけテストを書く。

- ハッシュ計算、正規化、変更検知判定、通知メッセージ組み立てなど
- DB操作や外部API呼び出しそのものはテストしない（mock で切り離す）
- CronJob としての結合動作は手動確認に委ねる（CI で MariaDB を立てるまではやらない）

## 2. テストしない境界線

> CIで自動検証する範囲と手動確認に委ねる範囲の全体像は [CI境界定義](ci-boundary.md) を参照。

| 対象 | 理由 |
|---|---|
| `get_conn()` 関数本体 | 実DB接続。テストでは mock する |
| シェルスクリプト（mirror-check） | pytest の守備範囲外。手動実行で確認 |
| `lifecycle_notify.fetch_approaching_eol` | JSON_TABLE を使う複雑なSQL。実DB必要 |
| DB に依存する統合テスト | GitHub Actions CI 導入済み。docker-compose での統合テストは将来検討 |

## 3. テスト追加の判断基準

- 新しい CronJob を追加したとき → 純粋ロジック（計算・変換・判定）があれば書く。DB/API ラッパーだけなら不要
- 既存ロジックを変更したとき → 変更箇所にテストがなければ追加する

## 4. 構成ルール

- テストファイル名: `test_<対象モジュール名>.py`
- fixture は `conftest.py` に共通化
- テストクラスの docstring に「何のテストか」を日本語で1行書く

## 5. 現在のカバレッジ

| テストファイル | 対象 | 内容 |
|---|---|---|
| `test_collector.py` | `mitre/collector.py` | バックオフ判定(`should_skip`)、バックログガード(`has_excessive_backlog`) |
| `test_mitre_collector_main.py` | `mitre/collector.py` | `save_raw`、`main()`フロー(DB失敗/skip/backlog/成功) |
| `test_normalizer.py` | `mitre/normalizer.py` | ハッシュ計算、外部ID抽出、日時パース、tactic/technique正規化、通知ブロック組み立て |
| `test_normalizer_upsert.py` | `mitre/normalizer.py` | `upsert_tactic`/`upsert_technique`の状態遷移、`sync_tactic_map` |
| `test_normalizer_db.py` | `mitre/normalizer.py` | `fetch_unprocessed`、`mark_processed`、`cleanup_old_processed`、`update_schedule` |
| `test_normalizer_main.py` | `mitre/normalizer.py` | `main()`フロー(tactic→technique処理順序、変更検知) |
| `test_notify_slack.py` | `mitre/normalizer.py` | Slack通知の送信/スキップ/エラーハンドリング |
| `test_eol_collector.py` | `eol-watch/collector.py` | `summarize`、`mark_failure`ステータス遷移、`send_webhook` |
| `test_eol_collector_main.py` | `eol-watch/collector.py` | `pick_target`、`fetch_eol`、`main()`フロー(変更検知含む) |
| `test_lifecycle_notify.py` | `eol-watch/lifecycle_notify.py` | メッセージ組み立て、Webhook送信、重複除去 |
| `test_cve_watch.py` | `cve-watch/cve_watch.py` | バージョン正規化、CVSS severity パース、fixed version 抽出、CVE-ID 抽出、Slack通知組み立て |
| `test_cve_watch_osv.py` | `cve-watch/cve_watch.py` | `query_osv`(成功/エラー各種) |
| `test_cve_watch_db.py` | `cve-watch/cve_watch.py` | DB操作関数(insert/update/resolve/mapping取得) |
| `test_cve_watch_main.py` | `cve-watch/cve_watch.py` | `auto_resolve`、`main()`フロー(新規CVE検知/修正版判明/状態変化なし) |
| `test_scanner.py` | `inventory-scan/scanner.py` | `extract_chart_version`、`parse_image_ref`、`send_slack_notification` |
| `test_scanner_collect.py` | `inventory-scan/scanner.py` | `run_cmd`、`collect_*`系関数、`upsert_record`返値ロジック |
| `test_scanner_main.py` | `inventory-scan/scanner.py` | `main()`フロー(k3s変更/helm変更/初回登録除外) |

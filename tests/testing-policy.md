# テスト方針

最終更新: 2026-08-07

## 1. 基本方針

「壊れたら困る純粋ロジック」にだけテストを書く。

- ハッシュ計算、正規化、変更検知判定、通知メッセージ組み立てなど
- DB操作や外部API呼び出しそのものはテストしない（mock で切り離す）
- CronJob としての結合動作は手動確認に委ねる（CI で MariaDB を立てるまではやらない）

## 2. テストしない境界線

| 対象 | 理由 |
|---|---|
| ConfigMap 内スクリプト（eol-watch collector） | 独立ファイルとして存在しないため import 不可。テストするならファイル分離が先 |
| シェルスクリプト（mirror-check） | pytest の守備範囲外。手動実行で確認 |
| DB に依存する統合テスト | CI/CD + docker-compose 導入後に検討 |

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
| `test_normalizer.py` | `mitre/normalizer.py` | ハッシュ計算、外部ID抽出、日時パース、tactic/technique正規化、通知ブロック組み立て |
| `test_notify_slack.py` | `mitre/normalizer.py` | Slack通知の送信/スキップ/エラーハンドリング |
| `test_lifecycle_notify.py` | `eol-watch/lifecycle_notify.py` | メッセージ組み立て、Webhook送信、重複除去 |
| `test_cve_watch.py` | `cve-watch/cve_watch.py` | バージョン正規化、CVSS severity パース、fixed version 抽出、CVE-ID 抽出、Slack通知組み立て |

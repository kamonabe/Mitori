# Contributing to Mitori

Mitori へのコントリビューションを歓迎します。

## 開発環境のセットアップ

```bash
# テスト用 venv 作成
python3 -m venv tests/.venv
tests/.venv/bin/pip install -r tests/requirements-test.txt
```

## コーディング規約

### Python スクリプト

- DB 接続: `pymysql` + `DictCursor` + `autocommit=False`
- エラーハンドリング: `try/except` で捕捉してログ出力後 `return`（終了コード 0 で終わらせる）
- datetime: `datetime.now(timezone.utc)` を使う（`utcnow()` は非推奨）
- 変更検知: `json.dumps(sort_keys=True, ensure_ascii=False)` → SHA-256 ハッシュ比較
- charset: `utf8mb4` を明示する

### Slack 通知

- Webhook URL は環境変数 `SLACK_WEBHOOK_URL` から取得
- URL 未設定の場合は通知をスキップし、エラーにしない
- 通知失敗もエラーにせずログ出力のみ
- 多件数の場合は `NOTIFY_MAX_ITEMS = 5` 件まで個別列挙、超えたら集約表示

### Kubernetes マニフェスト

- `namespace: app` を必ず明記
- イメージタグは固定（`:latest` 禁止）
- `imagePullSecrets` に `ghcr-secret` を指定
- リソース制約（`requests` / `limits`）を必ず設定

### CronJob 追加パターン

- スクリプトは ConfigMap に格納し `/app/` にマウント
- ConfigMap 名: `<サービス名>-script`
- DB Secret: `<サービス名>-db`（キー: `host`, `username`, `password`, `database`）
- Slack Secret: `<サービス名>-slack`（キー: `webhook-url`）

## テスト

```bash
# 全テスト実行
tests/.venv/bin/pytest

# 特定ファイルのみ
tests/.venv/bin/pytest tests/test_cve_watch.py -v
```

### テスト方針

- 「壊れたら困る純粋ロジック」にだけテストを書く
- DB 操作や外部 API 呼び出しは mock で切り離す
- 詳細は [tests/testing-policy.md](tests/testing-policy.md) を参照

## Lint / Format

```bash
tests/.venv/bin/ruff check .
tests/.venv/bin/ruff format .
```

## コミットメッセージ

特に厳密なルールはありませんが、変更内容が分かる簡潔な日本語 or 英語でお願いします。

## ドキュメント

- 各サービスに設計ドキュメント（`*-design.md`）があります
- 実装変更時は設計ドキュメントの「最終更新日」も更新してください
- トラブルシューティングの知見は `TROUBLESHOOTING.md` に集約してください

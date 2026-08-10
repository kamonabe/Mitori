# Mitori Mini: mitre-sync

[MITRE ATT&CK](https://attack.mitre.org/) の Tactics / Techniques を TAXII 2.1 API 経由で全件取得し、正規化して DB に保存します。変更があれば Slack に通知します。

## クイックスタート

```bash
cp .env.example .env
# .env に SLACK_WEBHOOK_URL を設定（任意）

# 1. DB 起動
docker compose up -d mariadb

# 2. コレクター実行（TAXII API からデータ取得）
docker compose run --rm mitre-collector

# 3. ノーマライザー実行（正規化 + 変更通知）
docker compose run --rm mitre-normalizer
```

## 使い方

collector → normalizer の順で実行します。初回は ATT&CK 全件（約2万オブジェクト）を取得するため、collector に1〜2分かかります。

### 定期実行

ホスト側の cron で定期実行してください:

```cron
# 6時間ごとに collector + normalizer を順次実行
0 */6 * * * cd /path/to/mini/mitre-sync && docker compose run --rm mitre-collector && docker compose run --rm mitre-normalizer
```

collector には adaptive backoff が組み込まれています。変更がなければ次回実行を自動スキップするため、頻繁に cron を回しても API に負荷をかけません。

## DB の確認

```bash
docker compose exec mariadb mariadb -umitre -pmitrepass mitre_attack
```

```sql
-- Tactic 一覧
SELECT external_id, name, is_deprecated FROM mitre_tactics ORDER BY external_id;

-- Technique 数
SELECT COUNT(*) FROM mitre_techniques;
```

## 環境変数

| 変数 | 説明 | デフォルト |
|------|------|-----------|
| `DB_ROOT_PASSWORD` | MariaDB root パスワード | `rootpass` |
| `DB_NAME` | データベース名 | `mitre_attack` |
| `DB_USER` | DB ユーザー名 | `mitre` |
| `DB_PASSWORD` | DB パスワード | `mitrepass` |
| `SLACK_WEBHOOK_URL` | Slack Incoming Webhook URL（未設定で通知スキップ） | 空 |

# Mitori Mini: eol-watch

[endoflife.date](https://endoflife.date/) API を使って、ソフトウェアの EOL（End of Life）情報を定期収集し、変化があれば Slack に通知します。

## クイックスタート

```bash
cp .env.example .env
# .env に SLACK_WEBHOOK_URL を設定（任意）

docker compose up
```

初回起動時に MariaDB の初期化とサンプル監視対象の登録が自動で行われます。

## 監視対象の追加

MariaDB に直接 INSERT します:

```bash
docker compose exec mariadb mariadb -uappuser -papppass appdb
```

```sql
INSERT INTO monitor_targets (product_slug, display_name) VALUES ('nginx', 'Nginx');
```

`product_slug` は [endoflife.date の製品一覧](https://endoflife.date/) で確認できます。

## 定期実行

Docker Compose 単体にはスケジューラがないため、ホスト側の cron で定期実行してください:

```cron
0 * * * * cd /path/to/mini/eol-watch && docker compose run --rm eol-watch
```

または手動実行:

```bash
docker compose run --rm eol-watch
```

## DB の確認

```bash
docker compose exec mariadb mariadb -uappuser -papppass appdb
```

外部ツール（MySQL Workbench 等）からの接続が必要な場合は、各自で `docker-compose.yml` に `ports` を追加してください。

## 環境変数

| 変数 | 説明 | デフォルト |
|------|------|-----------|
| `DB_ROOT_PASSWORD` | MariaDB root パスワード | `rootpass` |
| `DB_NAME` | データベース名 | `appdb` |
| `DB_USER` | DB ユーザー名 | `appuser` |
| `DB_PASSWORD` | DB パスワード | `apppass` |
| `SLACK_WEBHOOK_URL` | Slack Incoming Webhook URL（未設定で通知スキップ） | 空 |

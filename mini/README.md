# Mitori Mini

Mitori のセキュリティ監視ジョブを Docker Compose で単品利用できるパッケージです。

k3s フルセットは不要、Docker さえあれば試せます。必要なものだけどうぞ。

## ラインナップ

| Mini | 概要 | DB | 始め方 |
|------|------|----|--------|
| 🛡️ [cve-watch](./cve-watch/) | OSV API で CVE を日次チェック、状態変化を Slack 通知 | MariaDB | `docker compose run --rm cve-watch` |
| 📅 [eol-watch](./eol-watch/) | endoflife.date で EOL 情報を定期収集・変更通知 | MariaDB | `docker compose run --rm eol-watch` |
| 🔍 [mitre-sync](./mitre-sync/) | MITRE ATT&CK を TAXII API から取得・正規化・変更通知 | MariaDB | `docker compose run --rm mitre-collector` |
| 🪞 [mirror-check](./mirror-check/) | EPEL ミラー死活監視 | なし | `docker compose run --rm mirror-check` |

## 共通の使い方

```bash
cd mini/<サービス名>
cp .env.example .env
# .env を編集（最低限 SLACK_WEBHOOK_URL を設定）

# DB ありのサービス
docker compose up -d mariadb
docker compose run --rm <サービス名>

# DB なしのサービス（mirror-check）
docker compose run --rm mirror-check
```

## 定期実行

Docker Compose にはスケジューラがないため、ホスト側の cron で定期実行してください。各 README に cron の設定例があります。

## DB へのアクセス

```bash
docker compose exec mariadb mariadb -u<user> -p<password> <dbname>
```

外部ツール（MySQL Workbench 等）からの接続が必要な場合は、各自で `docker-compose.yml` に `ports` を追加してください。

## フルセット版について

全ジョブ + 監視スタック（Prometheus / Grafana / Loki）をまとめてデプロイしたい場合は、k3s フルセット版をご利用ください。

→ [k3s フルセット版](../README.md)

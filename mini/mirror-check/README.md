# Mitori Mini: mirror-check

[Fedora ミラーリスト](https://mirrors.fedoraproject.org/) を使って、設定済みの EPEL ミラーがリストに存在するかを確認します。欠落があれば Slack に通知します。

DB 不要。コンテナ1個で完結します。

## クイックスタート

```bash
cp .env.example .env
# .env に監視対象ミラーと SLACK_WEBHOOK_URL を設定

docker compose run --rm mirror-check
```

## 定期実行

```cron
0 9 * * * cd /path/to/mini/mirror-check && docker compose run --rm mirror-check
```

## 終了コード

| コード | 意味 |
|--------|------|
| 0 | 全ミラーがリストに存在（正常） |
| 1 | 1件欠落（注意） |
| 2 | 2件欠落（警戒） |
| 3 | 全件欠落 or 取得失敗（緊急） |

## 環境変数

| 変数 | 説明 | デフォルト |
|------|------|-----------|
| `REPO` | EPEL リポジトリ名 | `epel-10` |
| `ARCH` | アーキテクチャ | `aarch64` |
| `MIRROR_1` | 監視対象ミラー 1 | 空 |
| `MIRROR_2` | 監視対象ミラー 2 | 空 |
| `MIRROR_3` | 監視対象ミラー 3 | 空 |
| `SLACK_WEBHOOK_URL` | Slack Incoming Webhook URL | 空 |

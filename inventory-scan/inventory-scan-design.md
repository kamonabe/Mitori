# Inventory Scan 設計ドキュメント

最終更新: 2026-08-07

## 1. 概要

k3sクラスター内で稼働中のコンポーネントのバージョンを週次で自動収集し、MariaDBの `inventory` テーブルに記録するサービスです。バージョン変更を検知した場合のみSlackに通知します。

収集データは将来の以下サービスから参照される想定です:

- **cve-watch**（計画中）: 現在のバージョンに対する脆弱性の有無を判定
- **lifecycle-notify**: EOL接近の判定に利用（inventory上のバージョンとeol-watchのEOL日を突合）

## 2. 収集対象

OS依存のない情報のみを対象とし、移植性を確保しています。

| カテゴリ | 対象 | 取得方法 | DBカテゴリ値 |
|---|---|---|---|
| ランタイム | k3s | `kubectl version -o json` → `serverVersion.gitVersion` | `runtime` |
| データベース | MariaDB | `SELECT VERSION()` | `database` |
| Helmリリース | 全リリース | `helm list -A -o json` → `app_version` | `helm` |
| コンテナイメージ | 全Pod | `kubectl get pods -A -o json` → image:tag | `container` |

### 対象外（将来検討）

| 対象 | 除外理由 |
|---|---|
| ホストOS（AlmaLinux等） | 取得方法がOS依存 |
| カーネルバージョン | 同上 |
| pipパッケージ | コンテナ内に入らないと取得不可 |

## 3. 処理フロー

```
CronJob起動 (毎週日曜 04:00 UTC)
        ↓
DB接続 → inventoryテーブル存在確認 (CREATE IF NOT EXISTS)
        ↓
┌─ k3s バージョン取得 (kubectl version)
├─ MariaDB バージョン取得 (SELECT VERSION())
├─ Helm リリース一覧取得 (helm list)
└─ コンテナイメージ一覧取得 (kubectl get pods)
        ↓
各コンポーネントについて:
  既存レコードと比較 → INSERT or UPDATE (ON DUPLICATE KEY UPDATE)
        ↓
バージョン変更あり？
   ↙       ↘
  No        Yes
  ↓          ↓
終了       Slack通知して終了
```

## 4. バージョン変更検知ロジック

`INSERT ... ON DUPLICATE KEY UPDATE` を使い、1クエリでupsertと変更検知を行います。

```sql
INSERT INTO inventory (component, category, version, source, scanned_at, prev_version)
VALUES (?, ?, ?, 'auto', NOW(), NULL)
ON DUPLICATE KEY UPDATE
    prev_version = CASE WHEN version != VALUES(version) THEN version ELSE prev_version END,
    version = VALUES(version),
    source = VALUES(source),
    scanned_at = VALUES(scanned_at)
```

- バージョンが変わった場合: 旧バージョンを `prev_version` に退避
- バージョンが同じ場合: `scanned_at` のみ更新

## 5. 通知ポリシー

| 条件 | 通知 |
|---|---|
| バージョン変更あり（1〜5件） | 全件を個別にリスト表示 |
| バージョン変更あり（6件以上） | 先頭5件 + 「他N件」 |
| 変更なし | 通知しない |
| 初回登録（prev_version = NULL） | 通知しない（初回はノイズになるため） |
| Webhook URL未設定 | スキップ（エラーにしない） |
| 通知失敗 | ログ出力のみ、処理継続 |

### 通知フォーマット例

```
📦 inventory-scan: 2件のバージョン変更を検知

  • mariadb: 11.8.2-MariaDB → 11.8.3-MariaDB
  • k3s: v1.36.2+k3s1 → v1.37.0+k3s1
```

## 6. データベース設計

DB: `inventory_scan`（MariaDB）

### inventory テーブル

```sql
CREATE TABLE IF NOT EXISTS inventory (
    component VARCHAR(100) NOT NULL,
    category VARCHAR(50) NOT NULL,
    version VARCHAR(50) NOT NULL,
    source VARCHAR(10) NOT NULL DEFAULT 'auto',
    scanned_at DATETIME NOT NULL,
    prev_version VARCHAR(50) DEFAULT NULL,
    UNIQUE KEY uq_component_category (component, category)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

| カラム | 説明 |
|---|---|
| `component` | コンポーネント名（例: `k3s`, `docker.io/grafana/grafana`） |
| `category` | カテゴリ（`runtime` / `database` / `helm` / `container`） |
| `version` | 現在のバージョン |
| `source` | `auto`（自動収集）/ `manual`（手動登録） |
| `scanned_at` | 最終スキャン日時（UTC） |
| `prev_version` | 前回バージョン（変更検知時に退避） |

ユニークキーは `(component, category)` の複合キー。同じコンポーネント名がhelmとcontainerの両方に存在しうるため、categoryを含めて一意にしています。

### source の使い分け

| source | 意味 | 更新者 |
|---|---|---|
| `auto` | CronJobが自動収集 | inventory-scan |
| `manual` | 手動登録（将来、OS情報等を手動で入れる場合） | 管理者が直接INSERT |

自動収集時に `source=manual` の既存レコードがあった場合は `auto` で上書きされます。

## 7. Helmチャートのコンポーネント名決定

| 条件 | component値 |
|---|---|
| release名が一意 | release名そのまま（例: `loki`） |
| release名が重複 | `<name>/<namespace>`（例: `traefik/kube-system`） |

バージョンは `app_version` フィールドを優先し、空の場合は `chart` フィールドからバージョンサフィックスを抽出します。

## 8. コンテナイメージのパース

| イメージ形式 | component | version |
|---|---|---|
| `docker.io/grafana/grafana:13.1.0` | `docker.io/grafana/grafana` | `13.1.0` |
| `nginx` | `nginx` | `latest` |
| `image@sha256:abc123...` | `image` | `sha256:abc123...` |

## 9. インフラ構成

- **スケジュール**: 毎週日曜 `04:00 UTC`（`0 4 * * 0`）
- **activeDeadlineSeconds**: 3600（60分でタイムアウト）
- **イメージ**: `ghcr.io/kamonabe/inventory-scan:1.0.0`
  - ベース: `python:3.12-slim`
  - 追加: `kubectl`, `helm`, `pymysql`, `requests`
- **ServiceAccount**: `inventory-scan`（ClusterRole でpods/list, /version, secrets/list を許可）
- **ConfigMap**: `inventory-scan-script`（scanner.py）
- **Secret**:
  - `inventory-scan-db`（host / username / password / database）
  - `inventory-scan-slack`（webhook-url、optional）
- **nodeSelector**: `node-role.kubernetes.io/control-plane: "true"`（イメージがmasterノードのみにある暫定対応）

### RBAC

| ClusterRole | 権限 | 目的 |
|---|---|---|
| `inventory-scan` | pods get/list, nodes get, /version get | k3s版・Pod情報取得 |
| `inventory-scan-helm` | secrets get/list | Helm release情報取得（secretsドライバー） |

## 10. エラーハンドリング

全ての収集処理は独立しており、1つが失敗しても他は継続します。

| エラー | 挙動 |
|---|---|
| DB接続失敗 | ログ出力して終了（exit 0） |
| kubectl/helm コマンド失敗 | ログ出力して次のコレクターへ |
| コマンドタイムアウト（30秒） | 同上 |
| JSONパース失敗 | 同上 |
| Slack通知失敗 | ログ出力して処理継続 |

## 11. ファイル構成

```
inventory-scan/
├── Dockerfile                       # コンテナイメージ定義
├── inventory-scan-configmap.yaml    # scanner.py を格納するConfigMap
├── inventory-scan-cronjob.yaml      # CronJobマニフェスト
├── inventory-scan-design.md         # 本ドキュメント
├── inventory-scan-rbac.yaml         # ServiceAccount + ClusterRole + Binding
└── scanner.py                       # メインスクリプト（ローカルテスト用）
```

## 12. 手動実行方法

```bash
kubectl create job inventory-scan-manual --from=cronjob/inventory-scan -n app
kubectl logs -n app -l job-name=inventory-scan-manual -f
kubectl delete job inventory-scan-manual -n app
```

## 13. 今後の課題

[ROADMAP.md](../ROADMAP.md) で一元管理しています。

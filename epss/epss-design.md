# EPSS Enricher + CVE Priority Notify 設計ドキュメント

最終更新: 2026-08-13

## 1. 概要

cve-watch が検知した CVE に対して EPSS（Exploit Prediction Scoring System）スコアを付加し、
KEV・EPSS・CVSS を組み合わせた優先度判定を行い、高優先のものを Slack 通知する仕組みです。

2つの独立した CronJob で構成されます:

```
① epss-enricher       — cve_entries の open CVE に EPSS スコアを日次で付加・更新
② cve-priority-notify — EPSS + KEV + CVSS で優先度判定し、高優先をSlack通知（日次）
```

### 1.1 設計思想

| 原則 | 説明 |
|---|---|
| 1 Pod = 1 機能 | enricher はスコア取得のみ、priority-notify は判定+通知のみ |
| cve-watch との疎結合 | cve_entries テーブルを参照するが、cve-watch のコードには依存しない |
| 既存を壊さない | cve-kev-alert はそのまま残す。priority-notify は別角度の通知 |
| 暗黙のリトライ | 日次実行。1回失敗しても翌日に救済される |

### 1.2 既存サービスとの棲み分け

| サービス | 役割 |
|---|---|
| cve-kev-alert | 「自環境CVEがKEVに載った」→ 即アクション要（バイナリ判定） |
| cve-priority-notify | 「EPSSスコアが高い未対処CVEがある」→ 優先度付きの判断材料提供 |

cve-kev-alert は KEV 掲載の事実を通知する「緊急アラート」。
cve-priority-notify は EPSS を加味した「優先度レポート」。目的が異なるため両方残す。

## 2. データソース

### 2.1 FIRST EPSS API

- **エンドポイント**: `https://api.first.org/data/v1/epss`
- **認証**: 不要
- **レート制限**: 明示的な制限なし（常識的な範囲で利用）
- **データ量**: 約354,000件のCVEにスコアあり（日次更新）
- **バッチクエリ**: `cve` パラメータにカンマ区切りで複数CVE指定可（最大2000文字）

### 2.2 リクエスト例

```
GET https://api.first.org/data/v1/epss?cve=CVE-2021-40438,CVE-2019-16759
```

### 2.3 レスポンス構造

```json
{
  "status": "OK",
  "status-code": 200,
  "version": "1.0",
  "total": 2,
  "offset": 0,
  "limit": 100,
  "data": [
    {
      "cve": "CVE-2021-40438",
      "epss": "0.972240000",
      "percentile": "1.000000000",
      "date": "2022-02-28"
    },
    {
      "cve": "CVE-2019-16759",
      "epss": "0.968170000",
      "percentile": "0.999990000",
      "date": "2022-02-28"
    }
  ]
}
```

| フィールド | 説明 |
|---|---|
| `cve` | CVE ID |
| `epss` | 今後30日間で悪用される確率（0.0〜1.0） |
| `percentile` | 全CVE中のパーセンタイル順位（0.0〜1.0） |
| `date` | スコア算出日 |

### 2.4 API利用上の注意点

- `cve` パラメータの最大長は2000文字（カンマ含む）
- CVE IDは平均16文字 + カンマ1文字 = 約17文字/件 → 1リクエストあたり約115件が上限
- EPSSスコアが存在しないCVE（古すぎる or 採番直後）はレスポンスに含まれない
- OSV ID（GHSA-xxxx等）にはEPSSスコアがない → `cve_id` が空のエントリはスキップ

## 3. データベース設計

DB: `inventory_scan`（cve-watch / KEV と同じ DB を共用）

### 3.1 epss_scores テーブル（新規）

CVEごとのEPSSスコアを格納する。

```sql
CREATE TABLE IF NOT EXISTS epss_scores (
    id INT AUTO_INCREMENT PRIMARY KEY,
    cve_id VARCHAR(50) NOT NULL UNIQUE,
    epss_score DECIMAL(10,9) NOT NULL,
    percentile DECIMAL(10,9) NOT NULL,
    score_date DATE NOT NULL,
    updated_at DATETIME NOT NULL,
    INDEX idx_epss_score (epss_score DESC),
    INDEX idx_cve_id (cve_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

| カラム | 説明 |
|---|---|
| `cve_id` | CVE ID（UNIQUE制約） |
| `epss_score` | EPSS確率値（0.000000000〜1.000000000） |
| `percentile` | パーセンタイル順位 |
| `score_date` | APIが返したスコア算出日 |
| `updated_at` | レコード更新日時 |

### 3.2 cve_priority_notify_log テーブル（新規）

cve-priority-notify の通知済み管理。

```sql
CREATE TABLE IF NOT EXISTS cve_priority_notify_log (
    id INT AUTO_INCREMENT PRIMARY KEY,
    cve_id VARCHAR(50) NOT NULL,
    component VARCHAR(100) NOT NULL,
    category VARCHAR(50) NOT NULL,
    priority_level VARCHAR(20) NOT NULL,
    notified_at DATETIME NOT NULL,
    UNIQUE KEY uq_cve_component (cve_id, component, category)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

| カラム | 説明 |
|---|---|
| `cve_id` | CVE ID |
| `component` | cve_entries の component |
| `category` | cve_entries の category |
| `priority_level` | 通知時の優先度レベル（critical / high / medium） |
| `notified_at` | 通知日時。レコードが存在する = 通知済み |

## 4. 優先度判定ロジック

### 4.1 優先度レベル定義

| レベル | 条件 | 意味 |
|---|---|---|
| `critical` | KEV掲載 **かつ** EPSS ≥ 0.7 | 実悪用中 + 悪用確率極めて高い。即座に対応 |
| `high` | KEV掲載（EPSS問わず）**または** EPSS ≥ 0.7 | 実悪用あり or 悪用確率が非常に高い |
| `medium` | EPSS ≥ 0.4 **かつ** CVSS重大度 HIGH以上 | 悪用確率中〜高 + 影響大 |

### 4.2 判定フロー

```python
def determine_priority(cve_id, epss_score, severity, is_in_kev):
    if is_in_kev and epss_score is not None and epss_score >= 0.7:
        return "critical"
    if is_in_kev:
        return "high"
    if epss_score is not None and epss_score >= 0.7:
        return "high"
    if epss_score is not None and epss_score >= 0.4 and severity in ("HIGH", "CRITICAL"):
        return "medium"
    return None  # 通知対象外
```

### 4.3 閾値のチューニング

閾値は環境変数で設定可能とする:

| 環境変数 | デフォルト | 説明 |
|---|---|---|
| `EPSS_THRESHOLD_HIGH` | `0.7` | high判定の閾値 |
| `EPSS_THRESHOLD_MEDIUM` | `0.4` | medium判定の閾値 |

運用しながら調整する想定。EPSSスコアの分布上、0.7以上は全CVEの上位約3%に該当する。

### 4.4 通知対象外

以下は cve-priority-notify の通知対象外:

- `status = 'resolved'` のCVE（対処済み）
- `cve_id` が空のエントリ（EPSS APIで引けない）
- 既に `cve_priority_notify_log` に記録済み（再通知しない）
- 優先度が `None`（閾値未満）

## 5. 処理フロー

### 5.1 epss-enricher（日次）

```
CronJob起動 (毎日 03:30 UTC — cve-watch 03:00 の後)
        ↓
DB接続 → テーブル存在確認 (CREATE IF NOT EXISTS)
        ↓
cve_entries から status='open' かつ cve_id != '' のCVE ID一覧を取得
        ↓
バッチに分割（1バッチ = 最大100件）
        ↓
各バッチについて:
  FIRST EPSS API に GET (cve=CVE-xxx,CVE-yyy,...)
  レスポンスの各データについて:
    epss_scores に UPSERT (ON DUPLICATE KEY UPDATE)
        ↓
ログ: "N件のCVEに対してEPSSスコアを更新"
        ↓
終了
```

**設計判断**:
- open状態のCVEのみ対象。resolved済みのスコアは不要
- 毎日全件を更新する（EPSSスコアは日次で変動するため）
- API未登録のCVE（レスポンスに含まれない）はスキップ（既存レコードは残す）

### 5.2 cve-priority-notify（日次）

```
CronJob起動 (毎日 04:00 UTC — epss-enricher の後)
        ↓
DB接続 → テーブル存在確認
        ↓
以下のJOINクエリで未通知の高優先CVEを取得:
  cve_entries (open)
    LEFT JOIN epss_scores ON cve_id
    LEFT JOIN kev_catalog ON cve_id
    LEFT JOIN cve_priority_notify_log ON (cve_id, component, category)
  WHERE notify_log IS NULL
        ↓
各行に対して優先度判定ロジックを適用
        ↓
優先度が None でないものを抽出
        ↓
該当なし → 即終了
        ↓
該当あり → Slack通知（優先度別にグルーピング）
  → cve_priority_notify_log に INSERT
        ↓
終了
```

## 6. 通知仕様

### 6.1 通知フォーマット

```
🎯 CVE優先度レポート

━━━━━ CRITICAL (即対応推奨) ━━━━━

■ CVE-2025-46599 (EPSS: 0.85 | CVSS: HIGH | KEV: ✓)
  対象: k3s (runtime)
  概要: kubelet configuration exposes credentials
  修正版: 1.32.4
  KEV対処期限: 2025-12-22
  理由: KEV掲載中 + EPSS上位1%

━━━━━ HIGH (早期対応推奨) ━━━━━

■ CVE-2025-12345 (EPSS: 0.73 | CVSS: HIGH | KEV: -)
  対象: docker.io/grafana/grafana (container)
  概要: Path traversal in file API
  修正版: 11.5.1
  理由: EPSS上位3% — 30日以内に悪用される確率73%

━━━━━ MEDIUM (計画的対応) ━━━━━

■ CVE-2025-99999 (EPSS: 0.45 | CVSS: HIGH | KEV: -)
  対象: docker.io/grafana/loki (container)
  概要: Denial of service via crafted query
  修正版: なし
  理由: EPSS中位 + 重大度HIGH

━━━━━━━━━━━━━━━━━━━━━━━━━━━

未対処CVE総数: 12件
  CRITICAL: 1件 / HIGH: 2件 / MEDIUM: 1件 / 通知閾値未満: 8件
```

### 6.2 通知ルール

- 優先度レベル別にセクション分けする
- 各レベル内は `NOTIFY_MAX_ITEMS = 5` 件まで個別表示、超過分は集約
- 「理由」欄で判定根拠を明示（人間が納得できるように）
- 末尾にサマリ（全体の件数と内訳）を付与
- 新たに高優先になったCVEのみ通知（毎日同じ内容を通知しない）

### 6.3 EPSSスコア上昇時の再通知

初回通知後にEPSSスコアが上昇して上位レベルに昇格した場合:
- **初期実装では再通知しない**（`cve_priority_notify_log` にレコードがあれば通知済み）
- 将来的には `priority_level` の変化を検知して再通知する機能を追加検討

## 7. スケジュール設計

| CronJob | スケジュール | 理由 |
|---|---|---|
| epss-enricher | `30 3 * * *` | cve-watch(03:00)の後。新規CVEのスコアを即取得 |
| cve-priority-notify | `0 4 * * *` | epss-enricherの後。最新スコアで判定 |

### 依存関係

```
cve-watch (03:00) → epss-enricher (03:30) → cve-priority-notify (04:00)
                                             ↑
kev-collector (02:00) ──────────────────────┘
```

epss-enricher は cve-watch が書いた cve_entries を読む。
cve-priority-notify は epss_scores と kev_catalog を読む。
全て DB 経由の疎結合なので、タイミングが多少ずれても問題ない。

## 8. インフラ構成

### 8.1 CronJob

| CronJob名 | イメージ | ConfigMap | Secret |
|---|---|---|---|
| `epss-enricher` | `ghcr.io/kamonabe/mitre-python:1.0.0` | `epss-enricher-script` | `epss-db` |
| `cve-priority-notify` | `ghcr.io/kamonabe/mitre-python:1.0.0` | `cve-priority-notify-script` | `epss-db`, `epss-slack` |

### 8.2 Secret

| Secret名 | キー | 説明 |
|---|---|---|
| `epss-db` | `host`, `username`, `password`, `database` | DB接続情報（database = `inventory_scan`） |
| `epss-slack` | `webhook-url` | Slack通知用 Webhook URL |

### 8.3 DB

`inventory_scan` データベースを cve-watch / KEV と共用。
epss_scores, cve_priority_notify_log を同 DB 内に配置。

理由: cve-priority-notify が `cve_entries` × `epss_scores` × `kev_catalog` を JOIN する必要があるため。

## 9. エラーハンドリング

| エラー | 挙動 |
|---|---|
| DB接続失敗 | ログ出力して終了（exit 0） |
| EPSS API タイムアウト（30秒） | ログ出力して終了（exit 0） |
| EPSS API エラーレスポンス | ログ出力して終了（exit 0） |
| JSON パース失敗 | ログ出力して終了（exit 0） |
| Slack通知失敗 | ログ出力して処理継続 |
| EPSS APIにCVEが存在しない | スキップ（エラーにしない） |

## 10. 初回実行時の振る舞い

### epss-enricher

初回は cve_entries にある全 open CVE（数十件想定）のスコアを一括取得する。
API側のレート制限は緩いため、問題にならない。

### cve-priority-notify

初回実行時に高優先CVEがあれば通知する。
cve-kev-alert と同様、既にリスクがある状態なので初回でも通知すべき。
ただし件数が多い場合（`PRIORITY_BULK_THRESHOLD` = 10件超）はサマリ通知に切り替える。

## 11. 環境変数

### epss-enricher

| 環境変数 | デフォルト | 説明 |
|---|---|---|
| `DB_HOST` | (必須) | MariaDB ホスト |
| `DB_USER` | (必須) | DB ユーザー |
| `DB_PASSWORD` | (必須) | DB パスワード |
| `DB_NAME` | (必須) | DB名 |
| `EPSS_API_TIMEOUT` | `30` | EPSS API タイムアウト（秒） |
| `EPSS_BATCH_SIZE` | `100` | 1リクエストあたりの最大CVE数 |

### cve-priority-notify

| 環境変数 | デフォルト | 説明 |
|---|---|---|
| `DB_HOST` | (必須) | MariaDB ホスト |
| `DB_USER` | (必須) | DB ユーザー |
| `DB_PASSWORD` | (必須) | DB パスワード |
| `DB_NAME` | (必須) | DB名 |
| `SLACK_WEBHOOK_URL` | `""` | Slack Webhook URL（未設定なら通知スキップ） |
| `EPSS_THRESHOLD_HIGH` | `0.7` | high/critical 判定閾値 |
| `EPSS_THRESHOLD_MEDIUM` | `0.4` | medium 判定閾値 |
| `NOTIFY_MAX_ITEMS` | `5` | 各優先度レベルの個別表示上限 |
| `PRIORITY_BULK_THRESHOLD` | `10` | 初回大量通知抑制の閾値 |

## 12. 今後の課題

- EPSSスコア上昇時の再通知: priority_level が昇格したら再通知
- EPSS推移の記録: epss_scores にヒストリカルデータを保持（現在は最新のみ）
- Grafanaダッシュボード: EPSS分布・優先度別CVE数のパネル化
- 週次サマリ: 未対処の高優先CVE一覧を週次でリマインド通知
- EPSSスコア急上昇アラート: 前日比で大幅上昇したCVEを検知

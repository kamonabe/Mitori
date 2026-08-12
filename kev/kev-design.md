# KEV（Known Exploited Vulnerabilities）設計ドキュメント

最終更新: 2026-08-11

## 1. 概要

CISA（米国サイバーセキュリティ・インフラセキュリティ庁）が公開する KEV カタログ（実際に悪用が確認された脆弱性の一覧）を定期取得し、MariaDB に蓄積するサービスです。

3つの独立した CronJob で構成されます:

```
① kev-collector    — KEV JSON を取得して DB に格納（日次）
② kev-notify       — KEV 単体の新規追加を検知して Slack 通知（日次）
③ cve-kev-alert    — cve-watch 検知済み CVE × KEV を突合して通知（3時間毎）
```

### 1.1 設計思想

| 原則 | 説明 |
|---|---|
| 収集・分析・通知の分離 | 各 CronJob は1責務。collector はデータを溜めるだけ、分析系は DB を読むだけ |
| cve-watch との疎結合 | cve-kev-alert は cve_entries テーブルを参照するが、cve-watch のコードには依存しない |
| 暗黙のリトライ | cve-kev-alert は3時間毎に起動。1回失敗しても次周回で救済される |
| ノード非依存 | Pod 内で完結。外部 API を GET して DB に書くだけ |

## 2. データソース

- **エンドポイント**: `https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json`
- **認証**: 不要
- **レート制限**: 特になし（公開フィード）
- **データ量**: 約1,700件（2026-08時点）、JSON で約1.5MB
- **更新頻度**: CISA が随時追加（通常は平日に数件ずつ）

### 2.1 レスポンス構造

```json
{
  "title": "CISA Catalog of Known Exploited Vulnerabilities",
  "catalogVersion": "2026.08.11",
  "dateReleased": "2026-08-11T18:59:43.6861Z",
  "count": 1665,
  "vulnerabilities": [
    {
      "cveID": "CVE-2026-20349",
      "vendorProject": "Cisco",
      "product": "Secure Firewall ASA",
      "vulnerabilityName": "Cisco ASA Heap Inspection Vulnerability",
      "dateAdded": "2026-08-11",
      "shortDescription": "...",
      "requiredAction": "Apply mitigations...",
      "dueDate": "2026-08-14",
      "knownRansomwareCampaignUse": "Unknown",
      "notes": "https://...",
      "cwes": ["CWE-244"]
    }
  ]
}
```

## 3. データベース設計

DB: `inventory_scan`（cve-watch と同じ DB を共用）

### 3.1 kev_catalog テーブル

KEV カタログの各エントリを格納する。

```sql
CREATE TABLE IF NOT EXISTS kev_catalog (
    id INT AUTO_INCREMENT PRIMARY KEY,
    cve_id VARCHAR(50) NOT NULL UNIQUE,
    vendor VARCHAR(200) NOT NULL,
    product VARCHAR(200) NOT NULL,
    vulnerability_name VARCHAR(500) NOT NULL,
    short_description TEXT,
    required_action TEXT,
    date_added DATE NOT NULL,
    due_date DATE,
    known_ransomware_use VARCHAR(20) DEFAULT 'Unknown',
    cwes VARCHAR(500) DEFAULT NULL,
    notes TEXT,
    created_at DATETIME NOT NULL,
    INDEX idx_date_added (date_added),
    INDEX idx_cve_id (cve_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

| カラム | 説明 |
|---|---|
| `cve_id` | CVE ID（UNIQUE制約で重複防止） |
| `vendor` | ベンダー名 |
| `product` | 製品名 |
| `vulnerability_name` | 脆弱性の正式名称 |
| `date_added` | KEV カタログへの追加日 |
| `due_date` | CISA が定める対処期限（BOD適用対象向け） |
| `known_ransomware_use` | ランサムウェアでの悪用: Known / Unknown |
| `cwes` | CWE ID のカンマ区切り |
| `created_at` | レコード挿入日時 |

### 3.2 kev_notify_log テーブル

kev-notify の通知済み管理。

```sql
CREATE TABLE IF NOT EXISTS kev_notify_log (
    id INT AUTO_INCREMENT PRIMARY KEY,
    cve_id VARCHAR(50) NOT NULL,
    notified_at DATETIME NOT NULL,
    notification_type VARCHAR(30) NOT NULL DEFAULT 'new_kev',
    INDEX idx_cve_id (cve_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

### 3.3 cve_kev_alert_log テーブル

cve-kev-alert の通知済み管理。

```sql
CREATE TABLE IF NOT EXISTS cve_kev_alert_log (
    id INT AUTO_INCREMENT PRIMARY KEY,
    cve_id VARCHAR(50) NOT NULL,
    component VARCHAR(100) NOT NULL,
    category VARCHAR(50) NOT NULL,
    notified_at DATETIME NOT NULL,
    UNIQUE KEY uq_cve_component (cve_id, component, category)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

| カラム | 説明 |
|---|---|
| `cve_id` | CVE ID |
| `component` | cve_entries の component（inventory の component と同値） |
| `category` | cve_entries の category |
| `notified_at` | 通知日時。レコードが存在する = 通知済み |

## 4. 処理フロー

### 4.1 kev-collector（日次）

```
CronJob起動 (毎日 02:00 UTC)
        ↓
DB接続 → テーブル存在確認 (CREATE IF NOT EXISTS)
        ↓
CISA KEV JSON を GET
        ↓
各 vulnerability について:
  kev_catalog に UNIQUE(cve_id) で INSERT IGNORE
  → 既存なら何もしない（上書き不要: KEV は追加のみで既存エントリの更新はほぼない）
        ↓
ログ: "N件取得、うちM件が新規"
        ↓
終了
```

**設計判断**: KEV カタログは基本的に「追加のみ」（既存エントリの修正は極めてまれ）のため、`INSERT IGNORE` で十分。万が一 CISA が既存エントリを更新した場合は、初回格納時のデータが残る。この割り切りにより実装をシンプルに保つ。

### 4.2 kev-notify（日次）

```
CronJob起動 (毎日 02:30 UTC — collector の後に実行)
        ↓
DB接続
        ↓
kev_catalog から kev_notify_log に未記録の cve_id を取得:
  SELECT k.* FROM kev_catalog k
  LEFT JOIN kev_notify_log n ON k.cve_id = n.cve_id
  WHERE n.id IS NULL
  ORDER BY k.date_added DESC
        ↓
未通知なし → 即終了
        ↓
未通知あり → Slack通知
  → kev_notify_log に INSERT
        ↓
終了
```

### 4.3 cve-kev-alert（3時間毎）

```
CronJob起動 (*/180 = 0 */3 * * *)
        ↓
DB接続
        ↓
cve_entries × kev_catalog を JOIN し、未通知のものを取得:
  SELECT ce.cve_id, ce.component, ce.category, ce.severity,
         ce.summary, k.vendor, k.product, k.date_added, k.due_date
  FROM cve_entries ce
  INNER JOIN kev_catalog k ON ce.cve_id = k.cve_id
  LEFT JOIN cve_kev_alert_log a
    ON ce.cve_id = a.cve_id AND ce.component = a.component AND ce.category = a.category
  WHERE ce.status = 'open'
    AND a.id IS NULL
        ↓
該当なし → 即終了 (数秒で完了、負荷ほぼゼロ)
        ↓
該当あり → Slack通知
  → cve_kev_alert_log に INSERT
        ↓
終了
```

## 5. 通知仕様

### 5.1 kev-notify（情勢把握用）

KEV に新規追加されたエントリを通知する。自環境との関連は問わない。

```
📋 KEV カタログ新規追加: 3件

━━━━━━━━━━━━━━━━━━━━━━━━━━━
■ CVE-2026-20349 (追加日: 2026-08-11)
  ベンダー: Cisco
  製品: Secure Firewall ASA
  概要: Heap Inspection Vulnerability
  対処期限: 2026-08-14
  ランサムウェア悪用: Unknown
━━━━━━━━━━━━━━━━━━━━━━━━━━━
■ CVE-2026-68820 (追加日: 2026-08-11)
  ベンダー: Microsoft
  製品: Windows AFD for WinSock
  概要: Use-After-Free Vulnerability
  対処期限: 2026-08-25
  ランサムウェア悪用: Unknown
━━━━━━━━━━━━━━━━━━━━━━━━━━━

... 他 1 件
```

- 個別列挙の上限: `NOTIFY_MAX_ITEMS = 5`
- 超過分は「... 他 N 件」と集約

### 5.2 cve-kev-alert（自環境アクション判断用）

cve-watch で検知済みの CVE が KEV に含まれている場合に通知する。緊急度が高い。

```
🚨 自環境CVE × KEV 該当: 1件

以下のCVEは実際に悪用が確認されています。早急な対応を推奨します。

━━━━━━━━━━━━━━━━━━━━━━━━━━━
■ CVE-2025-46599 (HIGH)
  対象: k3s v1.36.2+k3s1
  概要: kubelet configuration exposes credentials
  KEV追加日: 2025-12-01
  対処期限: 2025-12-22
  ランサムウェア悪用: Known
━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

### 5.3 共通通知ルール

- `SLACK_WEBHOOK_URL` が未設定の場合は通知をスキップ（エラーにしない）
- 通知失敗（requests 例外）もエラーにせずログ出力のみ
- 通知済みレコードがある限り同じ内容を再通知しない

## 6. スケジュール設計

| CronJob | スケジュール | 理由 |
|---|---|---|
| kev-collector | `0 2 * * *` | cve-watch(03:00)より前にデータを準備 |
| kev-notify | `30 2 * * *` | collector の後に実行 |
| cve-kev-alert | `0 */3 * * *` | 3時間毎。不足の事態のリトライ機会を確保 |

### 依存関係

```
kev-collector (02:00) → kev-notify (02:30)   : collector が先に動けば十分
cve-watch (03:00)     ┐
kev-collector (02:00) ┴→ cve-kev-alert (*/3h) : 両方のデータが DB にあれば動く
```

cve-kev-alert は実行タイミングに依存しない設計（DB 上で JOIN するだけ）なので、collector や cve-watch がたまたま遅延しても、次の3時間後に拾える。

## 7. インフラ構成

### 7.1 CronJob

| CronJob名 | イメージ | ConfigMap | Secret |
|---|---|---|---|
| `kev-collector` | `ghcr.io/kamonabe/mitre-python:1.0.0` | `kev-collector-script` | `kev-db` |
| `kev-notify` | `ghcr.io/kamonabe/mitre-python:1.0.0` | `kev-notify-script` | `kev-db`, `kev-slack` |
| `cve-kev-alert` | `ghcr.io/kamonabe/mitre-python:1.0.0` | `cve-kev-alert-script` | `kev-db`, `kev-slack` |

### 7.2 Secret

| Secret名 | キー | 説明 |
|---|---|---|
| `kev-db` | `host`, `username`, `password`, `database` | DB接続情報（database = `inventory_scan`） |
| `kev-slack` | `webhook-url` | Slack通知用 Webhook URL |

### 7.3 DB

`inventory_scan` データベースを cve-watch と共用する。KEV のテーブル（`kev_catalog`, `kev_notify_log`, `cve_kev_alert_log`）を同 DB 内に配置する。

理由: cve-kev-alert が `cve_entries` と `kev_catalog` を JOIN する必要があるため、同一 DB に置くのが最もシンプル。

## 8. エラーハンドリング

| エラー | 挙動 |
|---|---|
| DB接続失敗 | ログ出力して終了（exit 0） |
| CISA API タイムアウト（30秒） | ログ出力して終了（exit 0） |
| CISA API エラーレスポンス | ログ出力して終了（exit 0） |
| JSON パース失敗 | ログ出力して終了（exit 0） |
| Slack通知失敗 | ログ出力して処理継続 |

全て graceful に終了する。CronJob の `backoffLimit: 1` で1回リトライ、それでもダメなら翌日（or 3時間後）に再実行される。

## 9. 初回実行時の振る舞い

### kev-collector

初回実行時は KEV カタログ全件（約1,700件）が INSERT される。これは想定動作。

### kev-notify

初回は大量の未通知レコードが存在するが、**初回実行時は通知をスキップし「初期ロード完了: N件」のサマリのみ出力** する。判定方法: `kev_notify_log` が空（レコード0件）かつ未通知件数 > `KEV_BULK_THRESHOLD`（デフォルト: 50）の場合、初回ロードとみなす。

初回ロード時は通知せずに `kev_notify_log` に全件記録し、次回以降の差分通知に備える。

### cve-kev-alert

初回でも通知する。cve_entries に既にある CVE が KEV に該当すれば、それは即座にアクション対象であるため。

## 10. 環境変数

| 環境変数 | デフォルト | 説明 |
|---|---|---|
| `DB_HOST` | (必須) | MariaDB ホスト |
| `DB_USER` | (必須) | DB ユーザー |
| `DB_PASSWORD` | (必須) | DB パスワード |
| `DB_NAME` | (必須) | DB名 |
| `SLACK_WEBHOOK_URL` | `""` | Slack Webhook URL（未設定なら通知スキップ） |
| `KEV_BULK_THRESHOLD` | `50` | kev-notify 初回ロード判定閾値 |
| `NOTIFY_MAX_ITEMS` | `5` | Slack 通知の個別列挙上限 |

## 11. 今後の課題

- EPSS スコアとの連携: KEV × EPSS で優先度をさらに精緻化
- KEV エントリの更新検知: 現在は INSERT IGNORE だが、CISA が既存エントリを修正した場合の差分検知
- kev_catalog のデータ活用: Grafana ダッシュボードでの KEV 追加トレンド可視化
- cve-kev-alert の resolved 対応: cve_entries が resolved になったら alert_log も整理

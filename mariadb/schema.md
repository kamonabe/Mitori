# データベーススキーマ一覧

最終更新: 2026-08-13

MariaDB上の全テーブルを管理するリファレンスです。
新しいテーブルを追加・変更した場合はこのファイルを更新してください。

## 初期セットアップ手順

MariaDB Helm デプロイ後、以下の順序でテーブルを作成する。

### 前提

- MariaDB Pod が Running 状態であること
- `mariadb-auth` Secret が作成済みであること（root パスワードを含む）

### 1. appdb テーブル作成

`appdb` と `appuser` は Helm（`auth.database` / `auth.username`）が自動作成するため、テーブルのみ作成する。

```bash
kubectl exec -it deploy/mariadb -n app -- \
  mariadb -u root -p < mariadb/init-appdb.sql
```

> 実際にはローカルから `kubectl exec` に stdin でファイルを流し込む:
> ```bash
> kubectl exec -i deploy/mariadb -n app -- \
>   mariadb -u root -p"$(kubectl get secret mariadb-auth -n app -o jsonpath='{.data.mariadb-root-password}' | base64 -d)" \
>   < mariadb/init-appdb.sql
> ```

### 2. mitre_attack DB・ユーザー・テーブル作成

`mitre_attack` DB は Helm の管理外のため、DB 作成からすべて手動で行う。

```bash
kubectl exec -i deploy/mariadb -n app -- \
  mariadb -u root -p"$(kubectl get secret mariadb-auth -n app -o jsonpath='{.data.mariadb-root-password}' | base64 -d)" \
  < mariadb/init-mitre.sql
```

SQL 実行後、mitre 用ユーザーを作成する:

```bash
kubectl exec -it deploy/mariadb -n app -- \
  mariadb -u root -p"$(kubectl get secret mariadb-auth -n app -o jsonpath='{.data.mariadb-root-password}' | base64 -d)" \
  -e "CREATE USER IF NOT EXISTS 'mitre'@'%' IDENTIFIED BY '<mitre-attack-db Secretのpasswordと同じ値>';
      GRANT ALL PRIVILEGES ON mitre_attack.* TO 'mitre'@'%';
      FLUSH PRIVILEGES;"
```

### 3. 確認

```bash
kubectl exec -it deploy/mariadb -n app -- \
  mariadb -u root -p -e "SHOW DATABASES; USE appdb; SHOW TABLES; USE mitre_attack; SHOW TABLES;"
```

---

## DB構成

| DB名 | 用途 | 利用サービス |
|---|---|---|
| `appdb` | アプリケーション共通DB | eol-watch |
| `inventory_scan` | インベントリ・CVE・KEV・EPSS共用DB | inventory-scan, cve-watch, kev-collector, kev-notify, cve-kev-alert, epss-enricher, cve-priority-notify |
| `mitre_attack` | MITRE ATT&CK同期専用DB | mitre-collector, mitre-normalizer |

接続先: MariaDB(`bitnami/mariadb`) `app` namespace

---

## appdb

### monitor_targets

EOLウォッチの監視対象製品を管理するテーブル。レコードは手動INSERTで追加する。

```sql
CREATE TABLE monitor_targets (
    id INT AUTO_INCREMENT PRIMARY KEY,
    product_slug VARCHAR(100) NOT NULL UNIQUE,  -- endoflife.date のスラッグ (例: 'python', 'ubuntu')
    display_name VARCHAR(200) NOT NULL,          -- 表示名
    status ENUM('pending_validation','active','error','invalid') NOT NULL DEFAULT 'pending_validation',
    consecutive_failures INT NOT NULL DEFAULT 0,
    last_checked_at DATETIME NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

| カラム | 説明 |
|---|---|
| `product_slug` | endoflife.date APIのスラッグ。URLの末尾部分(例: `https://endoflife.date/ubuntu` → `ubuntu`) |
| `status` | `pending_validation`: 新規登録・確認待ち / `active`: 正常 / `error`: 連続失敗中 / `invalid`: APIで見つからず除外済み |
| `consecutive_failures` | 連続失敗回数。成功時に0リセット |
| `last_checked_at` | 最終チェック開始時刻。`SKIP LOCKED` のロック代わりに使用 |

---

### eol_snapshots

取得したEOL情報のスナップショット。直近3世代のみ保持。

```sql
CREATE TABLE eol_snapshots (
    id INT AUTO_INCREMENT PRIMARY KEY,
    target_id INT NOT NULL,
    raw_json LONGTEXT NOT NULL,
    collected_at DATETIME NOT NULL,
    FOREIGN KEY (target_id) REFERENCES monitor_targets(id) ON DELETE CASCADE,
    INDEX idx_target_collected (target_id, collected_at DESC)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

| カラム | 説明 |
|---|---|
| `raw_json` | endoflife.date APIレスポンスの `result` フィールドをそのまま保存 |
| `collected_at` | 取得日時 |

---

## inventory_scan

### kev_catalog

CISA KEV（Known Exploited Vulnerabilities）カタログの各エントリを格納するテーブル。kev-collectorが日次で取得・INSERT。

```sql
CREATE TABLE kev_catalog (
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
| `date_added` | KEV カタログへの追加日 |
| `due_date` | CISA が定める対処期限 |
| `known_ransomware_use` | ランサムウェアでの悪用: Known / Unknown |
| `cwes` | CWE ID のカンマ区切り |

---

### kev_notify_log

kev-notifyの通知済み管理テーブル。

```sql
CREATE TABLE kev_notify_log (
    id INT AUTO_INCREMENT PRIMARY KEY,
    cve_id VARCHAR(50) NOT NULL,
    notified_at DATETIME NOT NULL,
    notification_type VARCHAR(30) NOT NULL DEFAULT 'new_kev',
    INDEX idx_cve_id (cve_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

| カラム | 説明 |
|---|---|
| `cve_id` | 通知済みの CVE ID |
| `notification_type` | `new_kev`（通常通知）/ `initial_load`（初回ロード時スキップ） |

---

### cve_kev_alert_log

cve-kev-alertの通知済み管理テーブル。cve_entries × kev_catalog の突合結果を記録。

```sql
CREATE TABLE cve_kev_alert_log (
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
| `component` | cve_entries の component（inventory と同値） |
| `category` | cve_entries の category |
| `notified_at` | 通知日時。レコードが存在する = 通知済み |

---

### epss_scores

EPSS（Exploit Prediction Scoring System）スコアを格納するテーブル。epss-enricherが日次で取得・更新。

```sql
CREATE TABLE epss_scores (
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
| `epss_score` | 今後30日間で悪用される確率（0.0〜1.0） |
| `percentile` | 全CVE中のパーセンタイル順位（0.0〜1.0） |
| `score_date` | FIRST APIが返したスコア算出日 |
| `updated_at` | レコード更新日時 |

---

### cve_priority_notify_log

cve-priority-notifyの通知済み管理テーブル。EPSS + KEV + CVSS の優先度判定結果を記録。

```sql
CREATE TABLE cve_priority_notify_log (
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
| `priority_level` | 判定された優先度（critical / high / medium） |
| `notified_at` | 通知日時。レコードが存在する = 通知済み |

---

## mitre_attack

### mitre_raw_staging

① Collectorが書き込む生データ置き場。② Normalizerが処理後に `processed_at` を更新する。

```sql
CREATE TABLE mitre_raw_staging (
    id INT AUTO_INCREMENT PRIMARY KEY,
    source VARCHAR(20) NOT NULL,          -- 'enterprise-attack' 固定
    fetched_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    raw_json LONGTEXT NOT NULL,           -- TAXIIから取得したSTIXオブジェクトのJSON
    processed_at DATETIME NULL,           -- NULLが未処理、設定済みが処理完了
    INDEX idx_unprocessed (source, processed_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

---

### mitre_taxii_cursor

CollectorとNormalizerの実行タイミング管理テーブル。

```sql
CREATE TABLE mitre_taxii_cursor (
    collection_id VARCHAR(100) NOT NULL PRIMARY KEY,  -- 'enterprise-attack' 固定
    next_offset INT NOT NULL DEFAULT 0,               -- 未使用(Range非対応のため無効)
    last_added_after DATETIME NULL,                   -- 未使用(added_afterは更新検知に使えないため不採用)
    page_size INT NOT NULL DEFAULT 500,               -- 未使用
    total_count INT NULL,                             -- 未使用
    next_run_at DATETIME NULL,                        -- Collectorの次回実行可能時刻
    backoff_minutes INT NOT NULL DEFAULT 60,          -- 現在のバックオフ間隔(分)
    last_fetch_count INT NULL,                        -- Collectorが前回取得した件数(バックログ閾値の基準値)
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

> `next_offset` / `last_added_after` / `page_size` / `total_count` はページング・時刻フィルタ方式の検討時の名残。現在は未使用。

---

### mitre_tactics

MITRE ATT&CKの戦術(Tactic)テーブル。`x-mitre-tactic` typeのSTIXオブジェクトから正規化。

```sql
CREATE TABLE mitre_tactics (
    id INT AUTO_INCREMENT PRIMARY KEY,
    stix_id VARCHAR(100) NOT NULL UNIQUE,    -- 'x-mitre-tactic--...'
    tactic_key VARCHAR(50) NOT NULL UNIQUE,  -- x_mitre_shortname (例: 'privilege-escalation')
    external_id VARCHAR(20) NOT NULL,        -- 例: 'TA0004'
    name VARCHAR(150) NOT NULL,
    description TEXT,
    is_deprecated BOOLEAN NOT NULL DEFAULT FALSE,
    content_hash CHAR(64) NOT NULL,          -- SHA-256。変更検知に使用
    stix_modified DATETIME NOT NULL,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

---

### mitre_techniques

MITRE ATT&CKのテクニック・サブテクニックテーブル。`attack-pattern` typeのSTIXオブジェクトから正規化。

```sql
CREATE TABLE mitre_techniques (
    id INT AUTO_INCREMENT PRIMARY KEY,
    stix_id VARCHAR(100) NOT NULL UNIQUE,      -- 'attack-pattern--...'
    external_id VARCHAR(20) NOT NULL UNIQUE,   -- 例: 'T1590.001'
    parent_external_id VARCHAR(20) NULL,       -- サブテクニックの場合、親の external_id (例: 'T1590')
    name VARCHAR(255) NOT NULL,
    description TEXT,
    is_subtechnique BOOLEAN NOT NULL DEFAULT FALSE,
    is_deprecated BOOLEAN NOT NULL DEFAULT FALSE,
    is_revoked BOOLEAN NOT NULL DEFAULT FALSE,
    content_hash CHAR(64) NOT NULL,            -- SHA-256。変更検知に使用
    stix_modified DATETIME NOT NULL,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_parent (parent_external_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

---

### mitre_technique_tactic_map

テクニックと戦術の多対多の紐付けテーブル。1テクニックが複数のTacticに属し得るため中間テーブルとして設計。

```sql
CREATE TABLE mitre_technique_tactic_map (
    technique_id INT NOT NULL,
    tactic_id INT NOT NULL,
    PRIMARY KEY (technique_id, tactic_id),
    FOREIGN KEY (technique_id) REFERENCES mitre_techniques(id) ON DELETE CASCADE,
    FOREIGN KEY (tactic_id) REFERENCES mitre_tactics(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

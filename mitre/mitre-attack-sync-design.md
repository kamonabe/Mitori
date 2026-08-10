# MITRE ATT&CK 定期同期サービス 設計ドキュメント

最終更新: 2026-08-07

## 1. 概要

MITRE ATT&CK(Enterprise)の情報をTAXII 2.1 APIから定期取得し、正規化してDBに格納する。変更検知時はSlack Webhookで通知する。

処理は3段階のパイプラインに分割し、各段階の責務を明確に分離する設計とした。

```
① Collector(取得) → ② Normalizer(正規化) → ③ Notifier(Slack通知)
```

## 2. データソース

- **エンドポイント**: `https://attack-taxii.mitre.org/api/v21/`(TAXII 2.1)
  - 旧URL `cti-taxii.mitre.org` は廃止済み。接続不可(タイムアウト)になるため注意。
- **対象コレクション**: `Enterprise ATT&CK`
  - collection_id: `x-mitre-collection--1f5f1533-f617-4ca8-9ab4-6a02367fa019`
  - 他に `ICS ATT&CK`, `Mobile ATT&CK` も存在するが今回はスコープ外
- **利用ライブラリ**: `taxii2-client`(pip名。importは`taxii2client`とハイフンなし)
- **レート制限**: 送信元IPごとに10分間で10リクエストまで
- **既知の制約**: サーバーはHTTP `Range`ヘッダによる部分取得(ページング)に対応していない。`Range`を付けても無視され、コレクション全件(現状25,843件、約38.5MB)が1リクエストで返る。そのため、ページ分割方式は採用せず「全件取得」を前提とした設計に変更した。

## 3. パイプライン設計

### 3.1 責務分担

| 段階 | 役割 | 判断ロジック |
|---|---|---|
| ① Collector | TAXIIから全件取得し、生JSONをステージングテーブルに保存するだけ | `next_run_at` を見て、未来なら即終了。過去/NULLなら実行。加えて、未処理バックログが異常に溜まっていないかも確認(3.3参照) |
| ② Normalizer | ステージングの未処理データを読み、type別に正規化テーブルへ反映。次回①の実行タイミング(`next_run_at`)もここで決定・更新 | 未処理データがなければ即終了。処理した場合、差分の有無に応じてバックオフ間隔を調整 |
| ③ Notifier | ②が検知した変更をSlack Webhookで通知。②の処理末尾で呼び出される(`normalizer.py`内の`notify_slack()`)。 | 変更イベントが0件なら何もしない。`SLACK_WEBHOOK_URL`未設定の場合もスキップ。 |

①は②の内部ロジックやスケジュールを一切知らない。3.3のバックログガードのみ例外的に②の状況を間接的に参照するが、これは「②の状態を直接見に行く」のではなく「①自身の出力先(ステージングテーブル)のサイズ異常を確認する自己防衛」という位置づけであり、責務分離の設計思想は維持している。

### 3.2 実行頻度の自己調整(SNMPポーリング的バックオフ)

CronJobのスケジュール自体は固定(現在10分おき)とし、実行するかどうかの判断をアプリケーション側に持たせることで、動的なスケジュール変更を回避した。

- 差分あり → 次回は最短間隔(10分後)に戻す
- 差分なし → 次回間隔を60分ずつ延長(最大6時間まで)

この状態(`next_run_at`, `backoff_minutes`)は `mitre_taxii_cursor` テーブルに永続化されるため、Podが再起動しても失われない。

### 3.3 バックログガード(②の永続的異常に対する安全弁)

②に何らかの理由(バグ、DB権限エラー等)で継続的な異常が発生した場合、①は`next_run_at`だけを判断材料にしていると、②の状態に関係なく10分おきに全件取得を続け、`mitre_raw_staging`に取得結果を無限に積み上げてしまうリスクがある。これを防ぐため、①の実行条件に以下を追加した。

- ①は取得完了のたびに、今回取得した件数を `mitre_taxii_cursor.last_fetch_count` に記録する
- 次回実行時、`mitre_raw_staging` の未処理件数(`processed_at IS NULL`)が `last_fetch_count × 2` 以上溜まっていた場合、②が正常に処理できていない可能性が高いと判断し、①自身の実行を見送る
- 前回件数が未記録(初回実行など)の場合はガードしない

閾値を固定値ではなく「前回取得件数の2倍」という相対値にすることで、将来コレクションの総件数が増減しても手動でのしきい値調整が不要になる設計とした。

### 3.4 Slack通知仕様(③ Notifier)

`normalizer.py` の `notify_slack()` 関数として②に内包されており、処理末尾で呼び出される。

- 変更イベントを `added` / `updated` / `deprecated` / `revoked` の4種類に分類して整理
- 各カテゴリで最大5件(`NOTIFY_MAX_ITEMS`)まで `external_id` と名前を個別列挙し、超えた場合は「上記も含め、N件の変更を検知しました」と集約
- `SLACK_WEBHOOK_URL` が未設定の場合は通知をスキップ(エラーにはしない)
- 通知例:
  ```
  :bell: *MITRE ATT&CK 変更検知 (2026-08-06)*

  :new: 新規追加 (2件)
    • T1234        Example Technique
    • T1234.001    Example Sub-technique

  :pencil2: 更新 (1件)
    • TA0001       Initial Access
  ```

## 4. データベース設計

DB名: `mitre_attack`(MariaDB)

### 4.1 mitre_raw_staging(①が書き込む生データ置き場)

```sql
CREATE TABLE mitre_raw_staging (
    id INT AUTO_INCREMENT PRIMARY KEY,
    source VARCHAR(20) NOT NULL,
    fetched_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    raw_json LONGTEXT NOT NULL,
    processed_at DATETIME NULL,
    INDEX idx_unprocessed (source, processed_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

### 4.2 mitre_taxii_cursor(実行タイミング管理)

```sql
CREATE TABLE mitre_taxii_cursor (
    collection_id VARCHAR(100) NOT NULL PRIMARY KEY,
    next_offset INT NOT NULL DEFAULT 0,           -- 未使用(Range非対応のため無効化した名残)
    last_added_after DATETIME NULL,               -- 未使用(added_afterは更新検知に使えないため不採用)
    page_size INT NOT NULL DEFAULT 500,           -- 未使用
    total_count INT NULL,                          -- 未使用
    next_run_at DATETIME NULL,                     -- ①の次回実行可能時刻
    backoff_minutes INT NOT NULL DEFAULT 60,       -- 現在のバックオフ間隔
    last_fetch_count INT NULL,                     -- ①が前回取得した件数(バックログ閾値の基準値。3.3参照)
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

> 補足: `next_offset` / `last_added_after` / `page_size` / `total_count` はページング方式・時刻フィルタ方式を検討した際の名残。TAXIIサーバーがRange非対応、`added_after`は「新規追加検知」はできても「内容更新検知」ができないと判明したため、最終的に「全件取得+ハッシュ比較」方式に変更した。カラムは実害がないため残しているが、将来的に整理してもよい。

### 4.3 mitre_tactics(戦術/カテゴリ)

```sql
CREATE TABLE mitre_tactics (
    id INT AUTO_INCREMENT PRIMARY KEY,
    stix_id VARCHAR(100) NOT NULL UNIQUE,       -- 'x-mitre-tactic--...'
    tactic_key VARCHAR(50) NOT NULL UNIQUE,      -- x_mitre_shortname 例: 'privilege-escalation'
    external_id VARCHAR(20) NOT NULL,            -- 例: 'TA0004'
    name VARCHAR(150) NOT NULL,
    description TEXT,
    is_deprecated BOOLEAN NOT NULL DEFAULT FALSE,
    content_hash CHAR(64) NOT NULL,
    stix_modified DATETIME NOT NULL,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

### 4.4 mitre_techniques(テクニック/サブテクニック)

```sql
CREATE TABLE mitre_techniques (
    id INT AUTO_INCREMENT PRIMARY KEY,
    stix_id VARCHAR(100) NOT NULL UNIQUE,         -- 'attack-pattern--...'
    external_id VARCHAR(20) NOT NULL UNIQUE,       -- 例: 'T1590.001'
    parent_external_id VARCHAR(20) NULL,            -- サブテクニックの場合、親の external_id(例: 'T1590')
    name VARCHAR(255) NOT NULL,
    description TEXT,
    is_subtechnique BOOLEAN NOT NULL DEFAULT FALSE,
    is_deprecated BOOLEAN NOT NULL DEFAULT FALSE,
    is_revoked BOOLEAN NOT NULL DEFAULT FALSE,
    content_hash CHAR(64) NOT NULL,
    stix_modified DATETIME NOT NULL,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_parent (parent_external_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

### 4.5 mitre_technique_tactic_map(多対多の紐付け)

```sql
CREATE TABLE mitre_technique_tactic_map (
    technique_id INT NOT NULL,
    tactic_id INT NOT NULL,
    PRIMARY KEY (technique_id, tactic_id),
    FOREIGN KEY (technique_id) REFERENCES mitre_techniques(id) ON DELETE CASCADE,
    FOREIGN KEY (tactic_id) REFERENCES mitre_tactics(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

1テクニックが複数のTacticに属し得るため、カラム追加ではなく多対多の中間テーブルとして設計。将来カテゴリが増えてもスキーマ変更不要。

## 5. 正規化ロジックの要点

- `attack-pattern` オブジェクトの `kill_chain_phases[].phase_name` と、`x-mitre-tactic` オブジェクトの `x_mitre_shortname` が一致するキーとなっており、これを介してTactic-Technique間の紐付けを行う。`relationship`オブジェクトを経由する必要はなかった。
- 外部ID(`T1590.001`等)は `external_references` の中から `source_name == "mitre-attack"` のエントリを探して取得する。
- サブテクニックの親IDは `external_id` を `.` で分割して導出(例: `T1590.001` → 親は `T1590`)。
- 変更検知は正規化後の内容を `json.dumps(sort_keys=True)` してSHA-256ハッシュ化し、既存レコードと比較。差分がなければ書き込みをスキップする(Galeraへの無駄な書き込み負荷を避けるため)。
- **処理済みレコードのクリーンアップ**: normalizer の毎回の実行末尾で `cleanup_old_processed()` を呼び出し、`processed_at` から7日(`CLEANUP_RETENTION_DAYS`)以上経過したレコードを自動削除する。これによりテーブルの無制限肥大化を防止している。
- **処理順序の注意**: `mitre_raw_staging` から取得した順(type混在)でそのまま処理すると、technique処理時に対応するtacticがまだ登録されておらず、紐付けが欠落する不具合が実際に発生した。対策として、②は必ず2パス構成にする: **Pass 1で全tacticを先に処理→Pass 2でtechniqueを処理**。

## 6. スコープ(現時点)

Enterprise ATT&CKコレクションには以下のtypeが含まれる(2026-07-13時点、実測値)。今回実装したのは太字の2種類のみ。

| type | 件数 | 対応状況 |
|---|---|---|
| relationship | 21,025 | 未対応 |
| x-mitre-analytic | 1,758 | 未対応 |
| **attack-pattern** | **858** | **対応済み(Technique/Sub-technique)** |
| malware | 729 | 未対応 |
| x-mitre-detection-strategy | 699 | 未対応 |
| course-of-action | 268 | 未対応(Mitigation) |
| intrusion-set | 189 | 未対応(Group) |
| x-mitre-data-component | 109 | 未対応 |
| tool | 95 | 未対応 |
| campaign | 56 | 未対応 |
| x-mitre-data-source | 38 | 未対応 |
| **x-mitre-tactic** | **15** | **対応済み(Tactic)** |
| x-mitre-matrix | 1 | 未対応 |
| x-mitre-collection | 1 | 未対応 |
| marking-definition | 1 | 未対応 |
| identity | 1 | 未対応 |

Phase 2以降で `course-of-action`(Mitigation)、`intrusion-set`(Group)、`malware`/`tool`、`campaign` 等の対応を検討。

## 7. インフラ構成

- **DB接続**: ClusterIP Service(`mariadb`)経由で接続する。Galeraは使用しない。
- **Secret**:
  - `mitre-attack-db`(host/username/password/database)
  - `mitre-attack-slack`(webhook-url) — normalizerのみ参照
- **CronJob**:
  - `mitre-collector`: `*/10 * * * *`、`concurrencyPolicy: Forbid`、`completions:1, parallelism:1`
  - `mitre-normalizer`: `*/10 * * * *`、`concurrencyPolicy: Forbid`、`completions:1, parallelism:1`
  - 両方とも `successfulJobsHistoryLimit: 3` / `failedJobsHistoryLimit: 3` を設定し、Job履歴の際限ない蓄積を防止。
- **ConfigMap**: `mitre-collector-script`(collector.py) / `mitre-normalizer-script`(normalizer.py)

## 8. トラブルシューティング

過去に発生した問題の記録は [`TROUBLESHOOTING.md`](../TROUBLESHOOTING.md) を参照。

## 9. 今後の課題

- Phase 2スコープ(Mitigation, Group, Malware/Tool, Campaign等)の対応要否判断
- `mitre_taxii_cursor` の未使用カラム(`next_offset`, `last_added_after`, `page_size`, `total_count`)の整理

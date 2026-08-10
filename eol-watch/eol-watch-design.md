# EOL Watch 設計ドキュメント

最終更新: 2026-08-10 (スケジュールを毎時→日次に変更)

## 1. 概要

[endoflife.date](https://endoflife.date) APIを使って、監視対象ソフトウェアのEOL(End of Life)情報を定期収集し、変更を検知したらSlackに通知するサービスです。

## 2. データソース

- **エンドポイント**: `https://endoflife.date/api/v1/products/<slug>`
- **認証**: 不要(公開API)
- **タイムアウト**: 10秒

## 3. 処理フロー

```
monitor_targets から対象を1件取得(SKIP LOCKED)
        ↓
endoflife.date API にリクエスト
        ↓
    成功？
   ↙       ↘
  No        Yes
  ↓          ↓
mark_failure  スナップショット保存(直近3件を保持)
  ↓          ↓
(閾値超え)  前回スナップショットと比較
Slack通知    ↓
          変更あり？
         ↙       ↘
        No        Yes
        ↓          ↓
    定期チェック  変更検知
    Slack通知    Slack通知(追加)
```

### キュー方式による順次処理

`monitor_targets` テーブルをキューとして使い、1回の実行（1 Pod）で1件だけ処理する設計です。

CronJob は `completions: 2, parallelism: 2` で構成しており、1回のスケジュール起動で2つのPodが同時に立ち上がる。各Podがそれぞれ1件ずつ取得するため、**1回のCronJob起動あたり最大2件を並列処理**する。

```sql
SELECT ... FROM monitor_targets
WHERE status IN ('pending_validation','active','error')
ORDER BY (status = 'pending_validation') DESC,  -- 未検証を優先
         (last_checked_at IS NULL) DESC,          -- 未チェックを優先
         last_checked_at ASC                      -- 古いものから順に
LIMIT 1
FOR UPDATE SKIP LOCKED                            -- 多重実行時の競合を防止
```

- `FOR UPDATE SKIP LOCKED` により、複数Podが同時起動しても同じ対象を二重処理しない
- `last_checked_at` を取得開始時点で更新することで、処理中に別Podが同じ対象を取りにこないようにしている
- 監視対象が1件しかない場合、2つ目のPodは `pick_target()` で `None` を返し即終了する（無害）

> **completions / parallelism の調整**: 監視対象が増えた場合は `completions` / `parallelism` を増やすことでスループットを上げられる。ただし endoflife.date API への同時リクエスト数が増えるため、レート制限には注意すること。

## 4. ステータス管理

`monitor_targets.status` の遷移:

```
(INSERT時) → pending_validation
                  ↓ 成功
               active ←─────────────────┐
                  ↓ 連続失敗5回          │
               error ──── 成功時に回復 ──┘
                  
pending_validation → 連続失敗3回 → invalid(監視対象から除外)
```

| ステータス | 意味 |
|---|---|
| `pending_validation` | 新規登録済み、APIで存在確認中 |
| `active` | 正常に取得できている |
| `error` | 連続失敗中(5回以上でSlackアラート) |
| `invalid` | APIで見つからず除外済み |

### 失敗時の閾値

| ステータス | 閾値 | アクション |
|---|---|---|
| `pending_validation` | 3回 | `invalid` に変更、Slack通知 |
| `active` / `error` | 5回 | `error` に変更、Slack通知 |

成功すると `consecutive_failures` は0にリセットされ、`active` に戻る。

## 5. スナップショット管理

- 取得成功のたびに `eol_snapshots` テーブルにJSONを保存
- 直近 **3世代**(`KEEP_GENERATIONS = 3`)のみ保持し、古いものは自動削除
- 前回スナップショットと `json.dumps(sort_keys=True)` した文字列を比較して変更検知

## 6. Slack通知

| トリガー | メッセージ |
|---|---|
| 毎回の取得成功 | `:mag: EOL定期チェック: *{label}*` + 直近5リリースのEOL日・サポート状況 |
| 変更検知時(追加) | `:bell: *{label}* のEOL情報に変更を検知しました。` |
| `pending_validation` で3回失敗 | `:x: {slug} は見つかりませんでした。除外します。` |
| `active`/`error` で5回失敗 | `:warning: {slug} の取得がN回連続で失敗しています。` |

## 7. データベース設計

DB: `appdb`(MariaDB)。詳細は [`mariadb/schema.md`](../mariadb/schema.md) を参照。

### monitor_targets

監視対象製品の管理テーブル。レコードは手動INSERTで追加する。

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

### eol_snapshots

取得したEOL情報のスナップショット。直近3件のみ保持。

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

## 8. インフラ構成

- **スケジュール**: 毎日 06:00 UTC `0 6 * * *`
- **CronJob設定**: `completions: 2, parallelism: 2`（1回の起動で最大2件並列処理）
- **ConfigMap**: `eol-watch-script`（collector.py）
- **Secret**:
  - `eol-watch-db`（host/username/password/database）
  - `eol-watch-slack`（webhook-url）
- **イメージ**: `ghcr.io/kamonabe/mitre-python:1.0.0`（Python 3.12 + pymysql + requests）

## 9. 監視対象の追加方法

```sql
INSERT INTO monitor_targets (product_slug, display_name)
VALUES ('ubuntu', 'Ubuntu');
```

`status` はデフォルトで `pending_validation` になり、次回CronJob実行時に自動でAPIの存在確認が行われる。`slug` は endoflife.date のURL(`https://endoflife.date/ubuntu`)の末尾部分。

## 10. 今後の課題

[ROADMAP.md](../ROADMAP.md) で一元管理しています。

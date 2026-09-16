# Requirements Document

## Introduction

inventory-scan は、k3sクラスター内の全コンポーネントの現在バージョンを定期的に収集し、MariaDBの `inventory` テーブルに記録するCronJobである。収集データは将来の cve-watch（脆弱性監視）および lifecycle-notify（EOL接近通知）の入力データとなる。バージョン変更を検知した場合のみSlack通知を送信する。

## Glossary

- **Inventory_Scanner**: inventory-scan CronJob内で動作するPythonスクリプト。クラスターAPIおよびDB接続を通じてバージョン情報を収集し、inventoryテーブルに記録する
- **Inventory_Table**: MariaDB上の `inventory` テーブル。コンポーネント名・カテゴリ・バージョン・ソース・スキャン日時・前回バージョンを格納する
- **Cluster_API**: kubectl および helm CLI経由でアクセスするk3sクラスターのAPI群
- **Version_Change**: 収集したバージョンが Inventory_Table に記録済みの既存バージョンと異なる状態
- **Source_Label**: inventoryレコードの `source` カラムの値。`auto`（自動収集）と `manual`（手動登録）を区別する

## Requirements

### Requirement 1: k3sバージョン収集

**User Story:** As a platform operator, I want to automatically record the current k3s version, so that cve-watch can check for known vulnerabilities against the running version.

#### Acceptance Criteria

1. WHEN the Inventory_Scanner executes, THE Inventory_Scanner SHALL retrieve the k3s server version by invoking `kubectl version -o json` with a timeout of 30 seconds and extracting the `serverVersion.gitVersion` field
2. WHEN the k3s server version is successfully retrieved, THE Inventory_Scanner SHALL store it in the Inventory_Table with component `k3s`, category `runtime`, and source `auto`
3. IF the kubectl command fails (non-zero exit code, timeout exceeding 30 seconds, or unparseable JSON response), THEN THE Inventory_Scanner SHALL log the error message and continue processing remaining collection tasks

### Requirement 2: MariaDBバージョン収集

**User Story:** As a platform operator, I want to automatically record the current MariaDB version, so that cve-watch can monitor for database-related vulnerabilities.

#### Acceptance Criteria

1. WHEN the Inventory_Scanner executes, THE Inventory_Scanner SHALL retrieve the MariaDB version by executing `SELECT VERSION()` via the database connection with a query timeout of 10 seconds
2. WHEN the MariaDB version is successfully retrieved, THE Inventory_Scanner SHALL store the full raw version string without parsing or trimming in the Inventory_Table with component `mariadb`, category `database`, and source `auto`
3. IF the MariaDB version query fails, THEN THE Inventory_Scanner SHALL log the error message and continue processing remaining collection tasks
4. IF `SELECT VERSION()` returns NULL or an empty string, THEN THE Inventory_Scanner SHALL treat it as a failure condition, log the error, and continue processing remaining collection tasks

### Requirement 3: Helmチャートバージョン収集

**User Story:** As a platform operator, I want to automatically record all deployed Helm chart versions, so that cve-watch can check for vulnerabilities in third-party chart dependencies.

#### Acceptance Criteria

1. WHEN the Inventory_Scanner executes, THE Inventory_Scanner SHALL retrieve all deployed Helm releases by invoking `helm list -A -o json` with a timeout of 30 seconds
2. WHEN Helm release data is successfully retrieved, THE Inventory_Scanner SHALL store each release in the Inventory_Table with component set to the release `name` field, category `helm`, source `auto`, and version set to the `app_version` field
3. IF a Helm release has an empty or missing `app_version` field, THEN THE Inventory_Scanner SHALL store the record with version set to the `chart` field's version suffix (the portion after the last hyphen-separated version pattern)
4. IF multiple Helm releases share the same `name` field value, THEN THE Inventory_Scanner SHALL store each release as a separate record using `<name>/<namespace>` as the component value to ensure uniqueness
5. IF the helm command fails or exceeds the 30-second timeout, THEN THE Inventory_Scanner SHALL log the error message and continue processing remaining collection tasks

### Requirement 4: コンテナイメージバージョン収集

**User Story:** As a platform operator, I want to automatically record all container images running in the cluster, so that cve-watch can check for vulnerabilities in container base images and application images.

#### Acceptance Criteria

1. WHEN the Inventory_Scanner executes, THE Inventory_Scanner SHALL retrieve all Pod specifications across all namespaces by invoking `kubectl get pods -A -o json`
2. WHEN Pod data is successfully retrieved, THE Inventory_Scanner SHALL extract container image references from both regular containers and init containers in each Pod spec, parse each reference into the full image name (registry and repository path excluding the tag) as the component value and the tag portion as the version value, and store each unique combination in the Inventory_Table with category `container` and source `auto`
3. IF a container image reference has no explicit tag, THEN THE Inventory_Scanner SHALL record the version as `latest`
4. IF a container image reference uses a digest format (e.g. `image@sha256:...`), THEN THE Inventory_Scanner SHALL record the version as the digest string (including the `sha256:` prefix)
5. THE Inventory_Scanner SHALL deduplicate container images so that each unique component and version combination is recorded only once per scan regardless of how many Pods reference the same image
6. IF the kubectl pods command fails, THEN THE Inventory_Scanner SHALL log the error message and continue processing remaining collection tasks

### Requirement 5: バージョン変更検知

**User Story:** As a platform operator, I want the scanner to detect when component versions change, so that I am aware of version drift and can take action.

#### Acceptance Criteria

1. WHEN a collected version differs from the version currently stored in the Inventory_Table for the same composite key (`component`, `category`), THE Inventory_Scanner SHALL update the record with the new version, set `prev_version` to the previously stored version, and set `scanned_at` to the current UTC timestamp
2. WHEN a collected version is an exact string match with the version currently stored in the Inventory_Table for the same composite key (`component`, `category`), THE Inventory_Scanner SHALL update the `scanned_at` timestamp to the current UTC time without modifying the version or prev_version columns
3. WHEN a component is collected that does not exist in the Inventory_Table (no matching `component` and `category` pair), THE Inventory_Scanner SHALL insert a new record with `prev_version` set to NULL, `scanned_at` set to the current UTC timestamp, and `source` set to `auto`
4. WHEN a record exists in the Inventory_Table with `source` = `auto` but is not present in the current scan's collected results, THE Inventory_Scanner SHALL retain the record without modification
5. IF a database write fails during a version update or insert, THEN THE Inventory_Scanner SHALL log the error message and continue processing remaining components

### Requirement 6: Slack変更通知

**User Story:** As a platform operator, I want to receive Slack notifications only when version changes are detected, so that I am alerted to important changes without notification noise.

#### Acceptance Criteria

1. WHEN one or more Version_Changes are detected during a scan and the count is 5 or fewer, THE Inventory_Scanner SHALL send a Slack notification listing each change with the product name, previous version, and new version
2. WHEN no Version_Changes are detected during a scan, THE Inventory_Scanner SHALL complete without sending a Slack notification
3. WHEN the number of Version_Changes exceeds 5, THE Inventory_Scanner SHALL send a Slack notification with the header "N件のバージョン変更を検知しました" followed by the first 5 changes each showing the product name, previous version, and new version
4. IF the SLACK_WEBHOOK_URL environment variable is not set or is an empty string, THEN THE Inventory_Scanner SHALL skip notification without raising an error and SHALL exit with code 0
5. IF the Slack notification request fails or does not respond within 10 seconds, THEN THE Inventory_Scanner SHALL log an error message indicating the failure reason and SHALL continue execution with exit code 0

### Requirement 7: スケジュール実行

**User Story:** As a platform operator, I want the inventory scan to run weekly, so that version data stays current without excessive resource consumption.

#### Acceptance Criteria

1. THE Inventory_Scanner SHALL execute on a weekly schedule as a Kubernetes CronJob in the `app` namespace with `successfulJobsHistoryLimit: 3` and `failedJobsHistoryLimit: 3`
2. THE Inventory_Scanner SHALL prevent concurrent execution by using `concurrencyPolicy: Forbid`
3. WHEN the scan completes successfully, THE Inventory_Scanner SHALL exit with code 0
4. IF an expected error occurs (DB connection failure, external API timeout after 30 seconds of no response, or HTTP error response from external API), THEN THE Inventory_Scanner SHALL log the error to stdout and exit with code 0
5. IF an unexpected error occurs (unhandled exception), THEN THE Inventory_Scanner SHALL exit with a non-zero exit code
6. THE Inventory_Scanner SHALL set `activeDeadlineSeconds: 3600` on the Job spec to terminate execution that exceeds 60 minutes

### Requirement 8: inventoryテーブルスキーマ

**User Story:** As a platform operator, I want a structured inventory table, so that downstream consumers (cve-watch, lifecycle-notify) can query current component versions.

#### Acceptance Criteria

1. THE Inventory_Table SHALL contain the columns: `component` (VARCHAR(100) NOT NULL), `category` (VARCHAR(50) NOT NULL), `version` (VARCHAR(50) NOT NULL), `source` (VARCHAR(100) NOT NULL), `scanned_at` (DATETIME NOT NULL), `prev_version` (VARCHAR(50) nullable)
2. THE Inventory_Table SHALL use a composite unique key on (`component`, `category`) to prevent duplicate entries for the same component
3. THE Inventory_Table SHALL store `scanned_at` in UTC timezone using `datetime.now(timezone.utc)` at application level on each write
4. THE Inventory_Table SHALL use InnoDB engine with DEFAULT CHARSET=utf8mb4
5. WHEN a record with an existing (`component`, `category`) pair is inserted, THE Inventory_Table SHALL update `version`, `source`, `scanned_at` to the new values and set `prev_version` to the previous `version` value via INSERT ... ON DUPLICATE KEY UPDATE

### Requirement 9: ソース区別

**User Story:** As a platform operator, I want to distinguish between automatically collected and manually registered inventory entries, so that future consumers can handle them appropriately.

#### Acceptance Criteria

1. WHEN the Inventory_Scanner inserts or updates a record, THE Inventory_Scanner SHALL set the `source` column to `auto`
2. THE Inventory_Table SHALL accept records with `source` set to `manual` inserted by external processes without constraint violations
3. IF a record with the same composite key (`component`, `category`) already exists with `source` set to `manual`, THEN THE Inventory_Scanner SHALL overwrite it by setting `source` to `auto` and updating the version fields
4. THE Inventory_Table SHALL restrict the `source` column to the values `auto` and `manual`

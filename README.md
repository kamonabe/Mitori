# Mitori

**A security monitoring and automation platform on k3s.**

Mitori watches external threat intelligence, tracks software EOL dates, detects CVEs in your cluster components, and notifies changes via Slack — all running as lightweight CronJobs.

## What it does

| Service | Description |
|---|---|
| **eol-watch** | Collects EOL info from endoflife.date, detects changes |
| **lifecycle-notify** | Alerts when your components approach end-of-life |
| **mirror-check** | Monitors EPEL mirror availability |
| **inventory-scan** | Weekly scan of cluster component versions |
| **cve-watch** | Daily CVE check via OSV API, tracks status changes |
| **kev-collector** | Fetches CISA KEV (Known Exploited Vulnerabilities) catalog |
| **kev-notify** | Notifies new KEV additions for situational awareness |
| **cve-kev-alert** | Cross-references detected CVEs with KEV for urgent action |
| **epss-enricher** | Enriches CVEs with EPSS exploit probability scores |
| **cve-priority-notify** | Prioritizes CVEs using EPSS + KEV + CVSS, notifies high-priority ones |
| **mitre-collector** | Fetches MITRE ATT&CK data from TAXII 2.1 API |
| **mitre-normalizer** | Normalizes ATT&CK data, notifies on changes |

## Tech stack

k3s (single node, aarch64) · Python 3.12 · MariaDB · Helm · Prometheus + Grafana + Loki

## Quick start

See the detailed setup instructions below (in Japanese).
For standalone usage without k3s, check out [Mitori Mini](mini/) — Docker Compose versions of individual services.

---

# Mitori — セキュリティ情報監視プラットフォーム

最終更新: 2026-08-13

## 1. 概要

**Mitori**（見取り）は、k3s上で稼働するセキュリティ情報監視・運用自動化プラットフォームです。
外部の脅威情報やインフラ状態を定期収集・監視し、変化をSlackに通知します。

POC環境として単一ノードで動作しています。

- **リポジトリ**: https://github.com/kamonabe/Mitori

## 2. Mitori Mini（Docker Compose 単品提供）

「k3s フルセットは不要だけど、CVE 通知だけ欲しい」——
各ジョブを Docker Compose で単独起動できます。必要なものだけどうぞ。

| Mini | 概要 | 始め方 |
|------|------|--------|
| 🛡️ [cve-watch](mini/cve-watch/) | OSV API で CVE を日次チェック、状態変化を Slack 通知 | [→ README](mini/cve-watch/README.md) |
| 📅 [eol-watch](mini/eol-watch/) | endoflife.date で EOL 情報を定期収集・変更通知 | [→ README](mini/eol-watch/README.md) |
| 🔍 [mitre-sync](mini/mitre-sync/) | MITRE ATT&CK を TAXII API から取得・正規化・変更通知 | [→ README](mini/mitre-sync/README.md) |
| 🪞 [mirror-check](mini/mirror-check/) | EPEL ミラー死活監視 | [→ README](mini/mirror-check/README.md) |

→ [Mitori Mini 全体の説明](mini/README.md)

## 3. ディレクトリ構成

```
k3s/
├── README.md                  # このファイル
├── mini/                      # Docker Compose 単品提供版
├── kustomization.yaml         # アプリCronJob一括デプロイ用(kubectl apply -k .)
├── pyproject.toml             # ruff(linter/formatter) + pytest 設定
├── common/
│   ├── db.py                  # 共通DBコネクション(get_conn)
│   └── slack.py               # 共通Slack通知(send_slack)
├── bootstrap/
│   └── get_helm.sh            # Helmインストールスクリプト(公式スクリプト)
├── mariadb/
│   ├── mariadb-values.yaml    # MariaDB Helm values
│   ├── init-appdb.sql         # appdb テーブル初期化SQL
│   ├── init-mitre.sql         # mitre_attack DB・テーブル初期化SQL
│   └── schema.md              # DBスキーマ一覧
├── monitoring/
│   ├── monitoring-values.yaml      # kube-prometheus-stack Helm values
│   ├── loki-values.yaml            # Loki Helm values
│   ├── k8s-monitoring-values.yaml  # grafana/k8s-monitoring Helm values (Alloyログ収集)
│   └── monitoring-design.md        # モニタリング設計ドキュメント
├── eol-watch/
│   ├── eol-configmap.yaml              # EOLウォッチ スクリプト(ConfigMap)
│   ├── eol-watch-cronjob.yaml          # EOLウォッチ CronJob マニフェスト
│   ├── lifecycle-notify-configmap.yaml # ライフサイクル通知 スクリプト(ConfigMap)
│   ├── lifecycle-notify-cronjob.yaml   # ライフサイクル通知 CronJob マニフェスト
│   ├── lifecycle_notify.py             # ライフサイクル通知 スクリプト(ローカル参照用)
│   └── eol-watch-design.md             # EOLウォッチ設計ドキュメント
├── mirror-check/
│   ├── check-epel-mirrors.sh        # EPELミラー確認スクリプト(ローカル実行用)
│   ├── mirror-check-configmap.yaml  # 同スクリプト(ConfigMap版)
│   ├── mirror-check-cronjob.yaml    # EPELミラー監視 CronJob
│   └── mirror-check-design.md       # EPELミラー監視 設計ドキュメント
├── inventory-scan/
│   ├── Dockerfile                       # コンテナイメージ定義(kubectl+helm+python)
│   ├── scanner.py                       # メインスクリプト(ローカル参照用)
│   ├── inventory-scan-configmap.yaml    # スクリプト ConfigMap
│   ├── inventory-scan-cronjob.yaml      # CronJob マニフェスト
│   ├── inventory-scan-rbac.yaml         # ServiceAccount + ClusterRole + Binding
│   └── inventory-scan-design.md         # 設計ドキュメント
├── cve-watch/
│   ├── cve_watch.py                     # メインスクリプト(ローカル参照用)
│   ├── cve_coverage_report.py           # カバレッジレポートスクリプト
│   ├── cve-watch-configmap.yaml         # スクリプト ConfigMap
│   ├── cve-watch-cronjob.yaml           # CronJob マニフェスト
│   ├── cve-coverage-report-cronjob.yaml # カバレッジレポート CronJob マニフェスト
│   └── cve-watch-design.md             # 設計ドキュメント
├── kev/
│   ├── kev_collector.py                 # KEV カタログ取得スクリプト
│   ├── kev_notify.py                    # KEV 新規追加通知スクリプト
│   ├── cve_kev_alert.py                 # CVE × KEV 突合通知スクリプト
│   ├── kev-collector-cronjob.yaml       # kev-collector CronJob マニフェスト
│   ├── kev-notify-cronjob.yaml          # kev-notify CronJob マニフェスト
│   ├── cve-kev-alert-cronjob.yaml       # cve-kev-alert CronJob マニフェスト
│   └── kev-design.md                    # KEV 設計ドキュメント
├── epss/
│   ├── epss_enricher.py                 # EPSS スコア取得スクリプト
│   ├── cve_priority_notify.py           # CVE 優先度判定・通知スクリプト
│   ├── epss-enricher-cronjob.yaml       # epss-enricher CronJob マニフェスト
│   ├── cve-priority-notify-cronjob.yaml # cve-priority-notify CronJob マニフェスト
│   └── epss-design.md                   # EPSS 設計ドキュメント
├── mitre/
│   ├── collector.py                    # MITRE ATT&CK Collector(① 取得)
│   ├── normalizer.py                   # MITRE ATT&CK Normalizer(② 正規化 + ③ Slack通知)
│   ├── Dockerfile                      # mitre-python コンテナイメージ
│   ├── mitre-collector-configmap.yaml  # Collector スクリプト ConfigMap
│   ├── mitre-collector-cronjob.yaml    # Collector CronJob マニフェスト
│   ├── mitre-normalizer-configmap.yaml # Normalizer スクリプト ConfigMap
│   ├── mitre-normalizer-cronjob.yaml   # Normalizer CronJob マニフェスト
│   └── mitre-attack-sync-design.md     # MITRE ATT&CK 同期サービス設計ドキュメント
└── tests/
    ├── requirements-test.txt   # テスト用依存(pytest, ruff, pymysql等)
    ├── conftest.py             # 共通fixture
    ├── test_collector.py       # collector.py のテスト
    ├── test_normalizer.py      # normalizer.py のテスト
    └── test_notify_slack.py    # Slack通知のテスト
```

## 4. サービス一覧

| サービス | Namespace | 種別 | 概要 |
|---|---|---|---|
| MariaDB | `app` | Helm (Deployment) | アプリ用RDB。eol-watch / MITRE ATT&CKが利用 |
| eol-watch | `app` | CronJob | endoflife.date APIでEOL情報を定期収集・変更通知 |
| lifecycle-notify | `app` | CronJob | 自環境コンポーネントのEOL接近をSlack通知 |
| mirror-check | `app` | CronJob | EPELミラーリスト死活監視・Slack通知 |
| inventory-scan | `app` | CronJob | クラスター内コンポーネントのバージョン収集・変更通知 |
| cve-watch | `app` | CronJob | OSV APIでCVE日次チェック・状態変化時にSlack通知 |
| cve-coverage-report | `app` | CronJob | inventory vs CVE監視対象の差分を週次Slack通知 |
| kev-collector | `app` | CronJob | CISA KEVカタログを日次取得・DB蓄積 |
| kev-notify | `app` | CronJob | KEV新規追加を検知してSlack通知（情勢把握） |
| cve-kev-alert | `app` | CronJob | cve-watch検知CVE × KEV突合・緊急Slack通知 |
| epss-enricher | `app` | CronJob | cve_entriesのCVEにEPSSスコアを日次付加 |
| cve-priority-notify | `app` | CronJob | EPSS+KEV+CVSSで優先度判定・高優先をSlack通知 |
| mitre-collector | `app` | CronJob | MITRE ATT&CK TAXII APIから全件取得 |
| mitre-normalizer | `app` | CronJob | MITRE ATT&CKデータを正規化・Slack通知 |
| kube-prometheus-stack | `monitoring` | Helm | Prometheus + Grafana によるメトリクス監視 |
| Loki | `monitoring` | Helm | Podログ収集・保管 |
| Grafana Alloy | `monitoring` | Helm (DaemonSet) | Podログ収集エージェント(Lokiへ転送) |

## 5. Helmリポジトリ

```bash
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo add grafana              https://grafana.github.io/helm-charts
helm repo add bitnami              https://charts.bitnami.com/bitnami
helm repo update
```

## 6. デプロイ手順(概要)

### 前提

- k3s インストール済み
- `kubectl` / `helm` が利用可能(`bootstrap/get_helm.sh` でHelmをインストール可能)
- 各Secretが事前に作成済みであること(後述)

### Namespace

```bash
kubectl create namespace app
kubectl create namespace monitoring
```

### Secret 一覧

| Secret名 | Namespace | キー | 用途 |
|---|---|---|---|
| `mariadb-auth` | `app` | `mariadb-root-password`, `mariadb-password` | MariaDB認証 |
| `eol-watch-db` | `app` | `host`, `username`, `password`, `database` | EOL Watch DB接続 |
| `eol-watch-slack` | `app` | `webhook-url` | EOL Watch Slack通知 |
| `mitre-attack-db` | `app` | `host`, `username`, `password`, `database` | MITRE DB接続 |
| `mitre-attack-slack` | `app` | `webhook-url` | MITRE変更検知Slack通知 |
| `mirror-check-slack` | `app` | `webhook-url` | EPELミラー監視Slack通知 |
| `inventory-scan-db` | `app` | `host`, `username`, `password`, `database` | Inventory Scan DB接続 |
| `inventory-scan-slack` | `app` | `webhook-url` | Inventory Scan Slack通知 |
| `cve-watch-db` | `app` | `host`, `username`, `password`, `database` | CVE Watch / KEV DB接続 |
| `cve-watch-slack` | `app` | `webhook-url` | CVE Watch / KEV Slack通知 |
| `epss-db` | `app` | `host`, `username`, `password`, `database` | EPSS Enricher / Priority Notify DB接続 |
| `epss-slack` | `app` | `webhook-url` | CVE Priority Notify Slack通知 |
| `ghcr-secret` | `app` | (dockerconfigjson) | GHCR(ghcr.io)からのイメージPull |

### Secret 作成コマンド例

> 各 `<...>` は実際の値に置き換えてください。

```bash
# MariaDB 認証
kubectl create secret generic mariadb-auth -n app \
  --from-literal=mariadb-root-password='<rootパスワード>' \
  --from-literal=mariadb-password='<appuserパスワード>'

# EOL Watch DB接続
kubectl create secret generic eol-watch-db -n app \
  --from-literal=host='mariadb' \
  --from-literal=username='appuser' \
  --from-literal=password='<appuserパスワード>' \
  --from-literal=database='appdb'

# EOL Watch Slack通知
kubectl create secret generic eol-watch-slack -n app \
  --from-literal=webhook-url='https://hooks.slack.com/services/XXX/YYY/ZZZ'

# MITRE ATT&CK DB接続
kubectl create secret generic mitre-attack-db -n app \
  --from-literal=host='mariadb' \
  --from-literal=username='mitre' \
  --from-literal=password='<mitreユーザーパスワード>' \
  --from-literal=database='mitre_attack'

# MITRE ATT&CK Slack通知
kubectl create secret generic mitre-attack-slack -n app \
  --from-literal=webhook-url='https://hooks.slack.com/services/XXX/YYY/ZZZ'

# EPELミラー監視 Slack通知
kubectl create secret generic mirror-check-slack -n app \
  --from-literal=webhook-url='https://hooks.slack.com/services/XXX/YYY/ZZZ'

# Inventory Scan DB接続
kubectl create secret generic inventory-scan-db -n app \
  --from-literal=host='mariadb.app.svc.cluster.local' \
  --from-literal=username='inv_app' \
  --from-literal=password='<inv_appパスワード>' \
  --from-literal=database='inventory_scan'

# Inventory Scan Slack通知
kubectl create secret generic inventory-scan-slack -n app \
  --from-literal=webhook-url='https://hooks.slack.com/services/XXX/YYY/ZZZ'

# GHCR イメージPull用
kubectl create secret docker-registry ghcr-secret -n app \
  --docker-server=ghcr.io \
  --docker-username='<GitHubユーザー名>' \
  --docker-password='<GitHub PAT (read:packages)>' \
  --docker-email='<メールアドレス>'
```

> **注意**: `ghcr-secret` に使用する PAT には `read:packages` スコープが必要です。PAT の有効期限が切れた場合は Secret を再作成してください。

### MariaDB

```bash
helm upgrade --install mariadb bitnami/mariadb \
  -n app \
  -f mariadb/mariadb-values.yaml
```

### モニタリングスタック

```bash
# kube-prometheus-stack (Prometheus + Grafana)
helm upgrade --install monitoring prometheus-community/kube-prometheus-stack \
  -n monitoring \
  -f monitoring/monitoring-values.yaml

# Loki
helm upgrade --install loki grafana/loki \
  -n monitoring \
  -f monitoring/loki-values.yaml

# Grafana Alloy (ログ収集エージェント)
helm upgrade --install k8s-monitoring grafana/k8s-monitoring \
  -n monitoring \
  -f monitoring/k8s-monitoring-values.yaml
```

### アプリ CronJob / ConfigMap

```bash
kubectl apply -k .
```

> 個別に適用したい場合は従来通り `kubectl apply -f <ファイル>` でもOK。

## 7. アクセス

| 用途 | アクセス方法 |
|---|---|
| Grafana | `http://<NodeIP>:30080`(NodePort) |

## 8. 関連ドキュメント

- [アーキテクチャ図](docs/architecture.md)
- [環境構築ガイド（ゼロからの再構築手順）](SETUP.md)
- [MITRE ATT&CK 同期サービス設計](mitre/mitre-attack-sync-design.md)
- [EOL Watch 設計](eol-watch/eol-watch-design.md)
- [EPELミラー監視 設計](mirror-check/mirror-check-design.md)
- [Inventory Scan 設計](inventory-scan/inventory-scan-design.md)
- [CVE Watch 設計](cve-watch/cve-watch-design.md)
- [KEV 設計](kev/kev-design.md)
- [EPSS 設計](epss/epss-design.md)
- [モニタリング設計](monitoring/monitoring-design.md)
- [DBスキーマ一覧](mariadb/schema.md)
- [ライフサイクル管理](LIFECYCLE.md)
- [トラブルシューティング記録](TROUBLESHOOTING.md)
- [ロードマップ（今後の課題）](ROADMAP.md)
- [セキュリティ評価・改善項目](SECURITY.md)
- [テスト方針](tests/testing-policy.md)

## 9. テスト

Python ロジックのユニットテストを pytest で実行できます。

```bash
# 初回セットアップ（venv 作成 + 依存インストール）
python3 -m venv tests/.venv
tests/.venv/bin/pip install -r tests/requirements-test.txt

# テスト実行
tests/.venv/bin/pytest
```

テスト対象: 全サービスの純粋ロジック（DB操作モック、ハッシュ計算、正規化、バックオフ判定、Slack通知メッセージ組み立て）。

## 10. Lint / Format

[ruff](https://docs.astral.sh/ruff/) を使用。設定は `pyproject.toml` に記載。

```bash
# チェック
tests/.venv/bin/ruff check common/ mitre/ eol-watch/ cve-watch/ kev/ epss/ inventory-scan/

# 自動修正
tests/.venv/bin/ruff check --fix common/ mitre/ eol-watch/ cve-watch/ kev/ epss/ inventory-scan/

# フォーマット
tests/.venv/bin/ruff format common/ mitre/ eol-watch/ cve-watch/ kev/ epss/ inventory-scan/
```

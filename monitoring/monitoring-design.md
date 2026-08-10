# モニタリング設計ドキュメント

最終更新: 2026-08-07

## 1. 概要

k3sクラスター上のメトリクス監視とログ収集を担うスタックです。
リソース制約のあるPOC環境を前提に、各コンポーネントを最小構成で動かしています。

```
[各Pod] → Alloy(DaemonSet) → Loki(ログ)
[各Pod/Node] → Prometheus(メトリクス) → Grafana(可視化)
```

## 2. コンポーネント構成

| コンポーネント | Helmチャート | Namespace | 役割 |
|---|---|---|---|
| Prometheus | `prometheus-community/kube-prometheus-stack` | `monitoring` | メトリクス収集・保管 |
| Grafana | `prometheus-community/kube-prometheus-stack` (同梱) | `monitoring` | メトリクス・ログの可視化 |
| kube-state-metrics | `prometheus-community/kube-prometheus-stack` (同梱) | `monitoring` | KubernetesリソースのメトリクスExporter |
| prometheus-node-exporter | `prometheus-community/kube-prometheus-stack` (同梱) | `monitoring` | ノードレベルのメトリクスExporter |
| Loki | `grafana/loki` | `monitoring` | ログ収集・保管 |
| Grafana Alloy | `grafana/k8s-monitoring` | `monitoring` | Podログ収集エージェント(Lokiへ転送) |

Alertmanager は有効化しています。`monitoring` namespace のアラートをSlack Webhookで通知する設定です。

### 3.5 Alertmanager

- **通知先**: Slack Incoming Webhook（Secret `slack-webhook` in `monitoring` namespace）
- **ルーティング**: `monitoring` namespace のアラートのみ通知。それ以外は破棄（receiver `"null"`）
- **リピート間隔**: 4時間
- **設定方法**: `AlertmanagerConfig` CRD（`alertmanager-config.yaml`）
- **k3s対応**: `kubeProxy`, `kubeControllerManager`, `kubeScheduler` のメトリクス収集・アラートルールは無効化（k3sでは独立Podとして動かないため常時発火するため）

## 3. 各コンポーネントの設定要点

### 3.1 Prometheus (`monitoring-values.yaml`)

- **データ保持期間**: 6時間(`retention: 6h`)
  - POC環境のためストレージを節約。長期保持が必要になった場合は延長を検討。
- **Alertmanager**: 無効(`enabled: false`)
- **リソース上限**: memory 512Mi

### 3.2 Grafana (`monitoring-values.yaml`)

- **アクセス**: NodePort `30080`(`http://<NodeIP>:30080`)
- **永続化**: 無効(`persistence.enabled: false`)
  - Podが再起動するとダッシュボードの設定が失われる。永続化が必要な場合はPVCを有効化すること。
- **データソース**: kube-prometheus-stack のデフォルト設定でPrometheusが自動登録される。LokiはGrafana UIから手動追加が必要(URL: `http://loki.monitoring.svc.cluster.local:3100`)。
- **リソース上限**: memory 256Mi

### 3.3 Loki (`loki-values.yaml`)

- **デプロイモード**: Monolithic(シングルバイナリ)
  - 分散コンポーネント(ingester/querier/distributor等)はすべて`replicas: 0`に設定し、不要なリソース消費を排除。
- **認証**: 無効(`auth_enabled: false`)
- **ストレージ**: ファイルシステム(`object_store: filesystem`)
- **データ保持期間**: 24時間(`retention_period: 24h`)
- **永続化**: 無効(`persistence.enabled: false`)
  - Podが再起動するとログが消える。永続化が必要な場合はPVCを有効化すること。
- **スキーマ**: v13 / TSDB
- **キャッシュ**: chunksCache / resultsCache ともに無効
- **リソース上限**: memory 256Mi
- **Push エンドポイント**: `http://loki.monitoring.svc.cluster.local:3100/loki/api/v1/push`

### 3.4 Grafana Alloy / k8s-monitoring (`k8s-monitoring-values.yaml`)

- **クラスター名**: `k3s-poc`
- **ログ収集**: `podLogsViaLoki` を有効化し、DaemonSetとして全ノードに展開
- **プリセット**: `small`, `filesystem-log-reader`
  - `filesystem-log-reader`: ノードのファイルシステム(`/var/log/pods/`)からログを直接読み取る方式
  - `small`: リソース使用量を抑えた設定セット
- **転送先**: `http://loki.monitoring.svc.cluster.local:3100/loki/api/v1/push`

## 4. リソース使用量まとめ

| コンポーネント | CPU request | Memory request | Memory limit |
|---|---|---|---|
| Prometheus | 100m | 256Mi | 512Mi |
| Grafana | 50m | 128Mi | 256Mi |
| Loki | 50m | 128Mi | 256Mi |
| kube-state-metrics | 20m | 64Mi | - |
| prometheus-node-exporter | 20m | 32Mi | - |

## 5. 運用上の注意

- **Grafanaの設定はPod再起動で消える**: `persistence.enabled: false` のため、ダッシュボードやデータソースの追加設定はPod再起動で失われる。恒久的な設定が必要になった場合はPVC有効化を検討。
- **Lokiのログも再起動で消える**: 同様に永続化無効のため、デバッグ用途に限定して使うこと。
- **Prometheusのデータ保持は6時間**: 長期トレンド分析には不向き。必要であれば `retention` を延長するかRemote Writeを構成する。
- **LokiへのデータソースはGrafana UIで手動登録が必要**: kube-prometheus-stackの自動設定対象外のため、初期セットアップ時に追加すること。

> **永続化を無効にしている理由**: 現環境はPOC用途の単一ノードであり、ディスク容量に制約がある。ログやダッシュボード設定が消失しても運用上問題ないため、意図的に永続化を無効にしている。別環境で稼働させる場合は永続化の要否を再度検討すること。

> **Grafanaのパスワードについて**: `adminPassword` を明示設定していないため、チャートのデフォルト値(`prom-operator`)が使用される。現環境はUTM仮想ネットワーク内に閉じておりホストMacからのみアクセス可能なため、デフォルトパスワードによるリスクは許容している。別環境（共有ネットワークや外部公開）で稼働させる場合はSecretによるパスワード管理を再度検討すること。

## 6. 今後の課題

- Grafana / Loki の永続化対応: 現環境では不要と判断済み(理由は5章参照)。別環境で稼働させる場合に再検討
- Loki データソースの Grafana への自動プロビジョニング設定
- Prometheusの保持期間延長またはRemote Write設定の検討
- Alertmanagerの通知対象拡大（`app` namespace のアラートも通知する等）
- HighCPU / HighMemory アラートの閾値チューニング

# 環境構築ガイド

最終更新: 2026-08-06

このドキュメントは、k3s クラスター環境をゼロから再構築するための手順書です。
`README.md` がクラスター上のサービス群の説明とデプロイ手順であるのに対し、本書はその前提となるホスト環境の構築を扱います。

---

## 1. ホスト環境

| 項目 | 詳細 |
|---|---|
| 仮想化基盤 | UTM (macOS 上の仮想マシンマネージャー) |
| ゲストOS | AlmaLinux 10.2 (Lavender Lion) |
| アーキテクチャ | aarch64 (Apple Silicon) |
| カーネル | 6.12.0-211.40.1.el10_2.aarch64 |
| CPU | 4 vCPU |
| メモリ | 3.5 GiB |
| ディスク | 39 GB (LVM: `/dev/mapper/almalinux-root`) |
| ネットワーク | UTM Shared Network (192.168.64.0/24) |
| ホスト名 | `k3s-master` |
| IP | `192.168.64.10`（enp0s1） |

---

## 2. UTM 仮想マシン作成時の設定

1. UTM で「Virtualize」→「Linux」を選択
2. AlmaLinux 10 の aarch64 ISO を指定してインストール
3. 推奨設定:
   - CPU: 4コア
   - メモリ: 4096 MB
   - ディスク: 40 GB
   - ネットワーク: Shared Network（ホスト Mac から `192.168.64.x` でアクセス可能）
4. インストール時にユーザー `kamonabe` を作成し、sudo 権限を付与

---

## 3. OS 初期設定

```bash
# パッケージ更新
sudo dnf update -y

# 必要パッケージのインストール
sudo dnf install -y curl git tar

# swap の有効化（メモリ 3.5GB のため推奨）
# AlmaLinux インストーラーが自動で swap パーティションを作成済みの場合は不要
sudo swapon --show

# firewalld の設定（k3s が使うポートを許可）
sudo firewall-cmd --permanent --add-port=6443/tcp   # Kubernetes API
sudo firewall-cmd --permanent --add-port=10250/tcp  # kubelet
sudo firewall-cmd --permanent --add-port=30080/tcp  # Grafana NodePort
sudo firewall-cmd --reload
```

---

## 4. k3s インストール

```bash
# k3s インストール（シングルノード、デフォルト設定）
curl -sfL https://get.k3s.io | sh -

# バージョン確認
k3s --version
# 期待値: v1.36.2+k3s1（2026-08-06時点）

# kubectl を一般ユーザーで使えるようにする
mkdir -p ~/.kube
sudo cp /etc/rancher/k3s/k3s.yaml ~/.kube/config
sudo chown $(id -u):$(id -g) ~/.kube/config
chmod 600 ~/.kube/config

# 動作確認
kubectl get nodes
```

> **注意**: k3s はデフォルトで Traefik と ServiceLB をバンドルしている。本環境ではそのまま使用。

---

## 5. Helm インストール

```bash
# 公式インストールスクリプトを使用
bash k3s/bootstrap/get_helm.sh

# バージョン確認
helm version --short
# 期待値: v3.21.2（2026-08-06時点）
```

---

## 6. Helm リポジトリ登録

```bash
helm repo add bitnami              https://charts.bitnami.com/bitnami
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo add grafana              https://grafana.github.io/helm-charts
helm repo update
```

---

## 7. Namespace 作成

```bash
kubectl create namespace app
kubectl create namespace monitoring
```

---

## 8. コンテナレジストリ (ghcr.io) の準備

カスタムイメージ (`ghcr.io/kamonabe/mitre-python:1.0.0`) を Pull するために `docker-registry` 型の Secret を作成する。

```bash
kubectl create secret docker-registry ghcr-secret -n app \
  --docker-server=ghcr.io \
  --docker-username='<GitHubユーザー名>' \
  --docker-password='<GitHub PAT (read:packages)>' \
  --docker-email='<メールアドレス>'
```

PAT の管理方針については [`SECURITY.md`](SECURITY.md) を参照。

---

## 9. 次のステップ

ここまでで「空のクラスター」が立ち上がった状態。以降は [`README.md`](README.md) の手順に従ってサービスをデプロイする:

1. Secret 作成（README「Secret 作成コマンド例」セクション）
2. MariaDB デプロイ
3. DB 初期化（[`mariadb/schema.md`](mariadb/schema.md)「初期セットアップ手順」セクション）
4. モニタリングスタック デプロイ
5. アプリ CronJob デプロイ

---

## 10. ホスト Mac からのアクセス

| 用途 | URL |
|---|---|
| Grafana | `http://192.168.64.10:30080` |
| kubectl（Mac 側から直接） | `~/.kube/config` に `server: https://192.168.64.10:6443` を設定 |

---

## 11. バックアップ・復元

### UTM スナップショット

大きな変更を行う前に UTM のスナップショット機能でVM全体のスナップショットを取得しておくと安全。

### k3s の完全リセット

何らかの理由でクラスターを完全にやり直す場合:

```bash
# k3s アンインストール（全データ削除）
sudo /usr/local/bin/k3s-uninstall.sh

# 再インストール
curl -sfL https://get.k3s.io | sh -
```

> PVC に保存された MariaDB データも消えるため、必要に応じて事前に `mysqldump` でバックアップすること。

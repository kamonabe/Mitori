# Mitori ライフサイクル管理

最終更新: 2026-08-07

## 1. 方針

### 基本的な考え方

- EOLを迎えたコンポーネントはセキュリティパッチが提供されなくなるため、**EOLの半年〜1年前にアップグレード計画を立てる**
- POC環境ではあるが、外部APIと通信しDB にデータを保持するため、放置は避ける
- 「壊れてから直す」ではなく「期限が来る前に上げる」を原則とする

### Tier分類

| Tier | 基準 | 更新頻度の目安 |
|---|---|---|
| **Tier 1: セキュリティ直結** | EOL後にCVE修正が来なくなる。放置すると脆弱性が残る | EOL 1年前に計画、半年前に実施 |
| **Tier 2: 機能・互換性** | 古いままだと新しいチャートやAPIが動かなくなる | 年1回確認・必要に応じて更新 |
| **Tier 3: 低リスク** | メンテ停止しても即座に問題にはならないが、長期放置は避けたい | 年1回確認、Dependabot等で自動追跡 |

---

## 2. 現状の一覧（2026-08-07 時点）

### Tier 1: セキュリティ直結

| コンポーネント | 現バージョン | EOL | 猶予 | 次のアクション |
|---|---|---|---|---|
| **k3s (Kubernetes)** | v1.36.2+k3s1 | 2027年6月頃 | 約11ヶ月 | 2026年秋に1.37リリース安定後アップグレード |
| **Python** | 3.12.13 | 2028年10月 | 約2年 | 2027年中に3.14へ移行予定 |
| **MariaDB** | 11.8.2 | 要確認（LTSなら数年） | おそらく余裕 | 次回確認: 2027年初頭 |
| **AlmaLinux** | 10.2 | 2035年6月 | 約9年 | 当面対応不要 |

### Tier 2: 機能・互換性

| コンポーネント | 現バージョン | 注意点 |
|---|---|---|
| **python:3.12-slim (ベースイメージ)** | Debian Bookworm系 | ベースOSのEOLに連動。Pythonアップグレード時に一緒に更新 |
| **kube-prometheus-stack** | Helm管理 | Kubernetes APIの廃止に追従が必要。k3sアップグレード時にセットで確認 |
| **Loki** | Helm管理 | Grafana Labsのサポートポリシーに依存 |
| **Grafana Alloy** | Helm管理 | 同上 |
| **bitnami/mariadb チャート** | Helm管理 | Bitnamiのチャート廃止・非互換変更に注意 |

### Tier 3: 低リスク

| コンポーネント | 現バージョン | 備考 |
|---|---|---|
| **pymysql** | 1.2.0 | 枯れたライブラリ。破壊的変更は稀 |
| **requests** | 2.34.2 | 同上 |
| **taxii2-client** | 2.3.0 | MITRE側のAPI変更時に対応が必要になる可能性あり |
| **Helm CLI** | 最新 | 後方互換性が高い。壊れることは稀 |

---

## 3. 更新手順の概要

### k3s

シングルノードのため、上書きインストールで完了する。

```bash
# 特定バージョンを指定してアップグレード
curl -sfL https://get.k3s.io | INSTALL_K3S_VERSION="v1.37.x+k3s1" sh -

# 確認
k3s --version
kubectl get nodes
```

**注意**: アップグレード前に `kubectl get apiservices` で deprecated API の利用状況を確認すること。

### Python (コンテナイメージ)

1. `mitre/Dockerfile` のベースイメージを `python:3.14-slim` に変更
2. ローカルでビルド・テスト実行
3. `ghcr.io` にプッシュ
4. CronJobマニフェストのイメージタグを更新

### MariaDB

Helm values でバージョンを指定して `helm upgrade` を実行。

```bash
helm upgrade mariadb bitnami/mariadb -n app -f mariadb/mariadb-values.yaml
```

**注意**: メジャーバージョンアップ時はバックアップ必須。`mysqldump` で事前にダンプを取得すること。

### Helmチャート群

```bash
helm repo update
# 差分確認
helm diff upgrade <release> <chart> -n <namespace> -f <values>.yaml
# アップグレード
helm upgrade <release> <chart> -n <namespace> -f <values>.yaml
```

### Pythonライブラリ

GitHubリポジトリ移行後は Dependabot または Renovate で自動PR化する。手動の場合:

```bash
# requirements.txt を更新後
pip install -r requirements.txt
pytest
```

---

## 4. 年間カレンダー（目安）

| 時期 | やること |
|---|---|
| **毎四半期** | k3sのパッチリリース適用を検討 |
| **2026年秋** | k3s 1.37 安定版リリース後にアップグレード |
| **2027年初頭** | MariaDB EOL確認、Helmチャート更新確認 |
| **2027年中** | Python 3.14 移行（3.12 EOLの1年以上前） |
| **年1回（年末）** | 全コンポーネントのバージョン棚卸し・本ドキュメント更新 |

---

## 5. 参考リンク

- [Kubernetes リリース一覧](https://kubernetes.io/releases/)
- [Python EOL](https://endoflife.date/python)
- [AlmaLinux EOL](https://endoflife.date/almalinux)
- [MariaDB EOL](https://endoflife.date/mariadb)
- [endoflife.date (汎用)](https://endoflife.date/)

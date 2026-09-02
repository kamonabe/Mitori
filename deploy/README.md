# Mitori デプロイ自動化（pyinfra・ミニマムスタート版）

最終更新: 2026-09-02

新規構築時に手作業でいちばん面倒な「namespace 作成・Helm リポジトリ登録・Secret 作成・Helm デプロイ・アプリ適用」を [pyinfra](https://pyinfra.com/) で一括実行するためのディレクトリです。

## 位置づけ（ミニマムスタート）

このスクリプトは **クラスタ前提層 + アプリ/監視層** だけを自動化します。意図的に範囲を絞っています。

| 範囲 | 自動化 | 備考 |
|---|---|---|
| ホスト構築（OS・firewalld・k3s・helm install） | ❌ 対象外 | 頻度が低くリスクが高いため手動。[`../SETUP.md`](../SETUP.md) 参照 |
| namespace / Helm リポジトリ / Secret | ✅ | `.env` から Secret 値を読み込み |
| MariaDB / 監視スタック（Helm） | ✅ | 既存の values ファイルを参照 |
| DB 初期化 SQL の投入 | ❌ 対象外 | [`../mariadb/schema.md`](../mariadb/schema.md) 参照 |
| アプリ CronJob / ConfigMap | ✅ | `kubectl apply -k` |

デプロイ後の日常運用（スクリプト更新など）は従来どおり `kubectl apply -k .` を使ってください。pyinfra は **再構築・初期構築用** と割り切っています。

今後の拡張（ホスト構築の pyinfra 化、Secret の SOPS/age 管理、DB 初期化の自動化など）は別途検討です。

## 前提

- 実行元ホストに Python と pyinfra が入っていること（OS は不問）
- 対象ホストで `kubectl` / `helm` が使え、kubeconfig が有効なこと
- SSH で対象ホストに接続できること（接続先 IP・ユーザーは `inventory.py` に記載）
- SSH 先ユーザーは **sudo 不要**（`kubectl` / `helm` を叩くだけ）。ただし有効な kubeconfig を読める必要がある。詳細は [設計ドキュメント 第3.1章](deploy-design.md) を参照

## セットアップ

```bash
cd deploy

# pyinfra インストール（venv 推奨）
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# Secret 値を用意
cp .env.example .env
# .env を編集して実値を埋める（.gitignore で除外済み）
```

## 実行

```bash
# SSH 経由でリモートのクラスタ制御ノードへ
.venv/bin/pyinfra inventory.py deploy_cluster.py

# 制御ノード上で直接実行する場合
.venv/bin/pyinfra @local deploy_cluster.py
```

`--dry-run` で実行内容を確認してから流すと安全です:

```bash
.venv/bin/pyinfra inventory.py deploy_cluster.py --dry
```

## 冪等性について

- namespace: 存在すればスキップ
- Helm リポジトリ: `--force-update` で登録
- Secret: `create --dry-run=client -o yaml | kubectl apply -f -` で既存でも上書き
- Helm デプロイ: `helm upgrade --install`
- アプリ: `kubectl apply -k`

いずれも再実行して安全な作りです。

## 注意

- `.env` には Secret 実値が入ります。**絶対にコミットしないこと**（`.gitignore` で除外済み）。
- Secret の値は既存の [`../README.md`](../README.md) の「Secret 作成コマンド例」と対応しています。DB ユーザーとパスワードの対応関係を変えた場合は両方を合わせて更新してください。

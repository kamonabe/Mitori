# デプロイ自動化（pyinfra）設計ドキュメント

最終更新: 2026-09-02

## 1. 概要

Mitori のクラスタ構築において、手作業でいちばん煩雑な「namespace 作成・Helm リポジトリ登録・Secret 作成・Helm デプロイ・アプリ適用」を [pyinfra](https://pyinfra.com/) で一括実行するためのプロビジョニング層です。

新規構築・再構築時の手順ミスを減らすことを目的とし、日常運用（スクリプト更新など）には使いません。**初期構築・再構築専用ツール**として位置づけます。

### 1.1 導入理由

現状のデプロイは `SETUP.md`（ホスト構築）と `README.md`（サービスデプロイ）の手順書に沿って手作業で行っている。この方式には以下の課題がある。

| 課題 | 詳細 |
|---|---|
| Secret 作成の手作業が多い | 13 個の Secret を `kubectl create secret` で個別に手打ちする。値の入れ忘れ・コピペミスが起きやすい |
| 手順の再現性が属人的 | 手順書を上から順に実行する前提で、実行漏れや順序間違いに気づきにくい |
| 再構築コストが高い | POC 環境を作り直すたびに同じ手作業を繰り返す |

これらは「一度きりの手作業」に見えて、POC 環境ではクラスタの作り直しが繰り返し発生するため、積み重なると無視できないコストになる。宣言的なスクリプトに落とすことで、再現性と実行速度を確保する。

### 1.2 設計思想

#### 基本原則: 小さく始め、できないことは明記する

この自動化は「まず確実に動く小さな範囲から始め、対応できないことは正直に書き残す」という方針を貫く。すべてを一度に自動化しようとせず、旨味が大きくリスクの小さい部分から着手する。

その上で、対象外にした領域・現時点で対応していない使い方は、**理由とともに明示**する。これには次の狙いがある。

- **誤用・事故を防ぐ**: 「できるはず」と期待して失敗する事態を、事前の宣言で防ぐ（例: SSH 越し実行は非対応 → 第3章で明記）
- **「未実装」と「意図的に外した」を区別する**: 後から読む人が、バグなのか設計判断なのかを迷わない
- **拡張の入口を用意する**: 「できないこと」は「今後の課題」（第9章）として、次に着手する人の起点になる

以下の個別原則は、この基本原則から導かれる。

| 原則 | 説明 |
|---|---|
| ミニマムスタート | 自動化の旨味が大きい範囲だけを対象にし、リスクの高い領域（k3s 構築など）は手動のまま残す |
| 境界の明示 | 対象外・非対応の使い方は理由とともに書き、`inventory.py` のように将来の布石は「現状未使用」と明記する |
| 冪等性 | 何度実行しても同じ結果になる。途中失敗しても再実行で回復できる |
| 既存資産の再利用 | Helm values・kustomization・SQL は既存ファイルをそのまま参照し、二重管理しない |
| Secret 値の非コミット | 実値はリポジトリに置かず `.env`（gitignore 済み）から読む |
| フォールバック維持 | 手動手順（README / SETUP.md）は残し、pyinfra を使わない選択肢を潰さない |

## 2. スコープ

### 2.1 対象範囲（自動化する）

| 範囲 | 内容 |
|---|---|
| namespace 作成 | `app` / `monitoring` |
| Helm リポジトリ登録・更新 | bitnami / prometheus-community / grafana |
| Secret 作成 | 13 個の Secret（`.env` から値を読み込み） |
| MariaDB / 監視スタック デプロイ | `helm upgrade --install` × 4 |
| アプリ CronJob / ConfigMap 適用 | `kubectl apply -k` |

### 2.2 対象外（手動 or 別途検討）

| 範囲 | 理由 | 参照 |
|---|---|---|
| ホスト構築（OS 初期設定・firewalld・k3s install・helm install） | 頻度が低くリスクが高い。k3s の作り直しは慎重に手動で行うべき | `SETUP.md` |
| DB 初期化（`init-*.sql` によるテーブル作成 + DB ユーザー `eol_app`/`inv_app`/`mitre_app` 作成） | MariaDB Pod の起動完了を待つ必要があり、root パスワードを扱う。初回のみの操作 | `mariadb/schema.md` |
| k3s クラスタ自体の作り直し | 破壊的操作。UTM スナップショットや `k3s-uninstall.sh` と組み合わせる領域 | `SETUP.md` |

ミニマムスタートとして意図的に範囲を絞っている。対象外領域の自動化は「今後の課題」（第 9 章）とする。

## 3. 全体アーキテクチャ

```
k3s 制御ノード（この1台の上で完結）
  ├─ リポジトリを clone 済み（deploy/ を含む）
  ├─ pyinfra @local deploy_cluster.py
  │     │
  │     ├─ inventory.py      （@local 実行では未使用。将来の SSH 実行用）
  │     ├─ deploy_cluster.py デプロイ操作の定義（operations）
  │     └─ .env              Secret 実値（gitignore 済み）
  │
  └─ kubectl / helm（kubeconfig 有効）でクラスタを操作
```

**ミニマムスタートでは「制御ノード上で `@local` 実行」に限定する。** pyinfra を起動するホストと `kubectl` / `helm` を実行するホストが同一（＝制御ノード自身）であることを前提とする。

##### なぜ @local 限定なのか（重要な設計判断）

`deploy_cluster.py` は `helm ... -f {REPO_ROOT}/mariadb/mariadb-values.yaml` や `kubectl apply -k {REPO_ROOT}` のように、**リポジトリ内のファイルパス（`REPO_ROOT`）をコマンドに埋め込む**。

- `REPO_ROOT` は `deploy_cluster.py` の場所から計算される「pyinfra 起動ホスト上の絶対パス」
- 一方 `server.shell()` のコマンドは「pyinfra が接続した対象ホスト」で実行される

この2つが同一ホスト（`@local`）なら、パスが一致して正しく動く。しかし SSH 越しに別ホストを対象にすると、**起動ホストのパス文字列を SSH 先で実行してしまい、そのパスが存在せず失敗する**。values ファイルや kustomize ツリーは対象ホストに転送されないためである。

このため本バージョンは `@local` に限定する。SSH 越し実行にはファイル転送（`files.put` / `files.rsync` で values・SQL・kustomize ツリーを対象ホストへ配布）の仕組みが必要で、これは今後の課題とする（第 9 章）。

前提:

- **実行ホスト**: k3s 制御ノード自身。Python と pyinfra が動くこと
- クラスタ操作: そのホストで `kubectl` / `helm` が使え、kubeconfig が有効なこと
- リポジトリ: そのホストに clone 済みで、`deploy/` から相対的に values / kustomize ツリーを参照できること

> `inventory.py` は `@local` 実行では参照されない。将来 SSH 実行を実装する際の接続先定義として残してある（第 9 章）。

### 3.1 実行権限（実行ユーザーに必要な権限）

制御ノード上で `pyinfra @local` を実行するユーザーが必要とする権限を、OS レベルと Kubernetes レベルに分けて示す。

#### OS レベル: sudo は不要

本スクリプトは制御ノード上で `kubectl` / `helm` を実行するだけで、OS 側の操作（パッケージインストール・systemd 操作・ファイアウォール設定など）は行わない。したがって **sudo / root 権限は不要**。一般ユーザーで実行できる。

> OS レベルの操作を伴うホスト構築（k3s / helm のインストール等）は本スクリプトのスコープ外（第 2.2 章）。そちらは `SETUP.md` に従い別途 sudo で行う。

#### kubeconfig の読み取り権限

実行ユーザーが有効な kubeconfig を参照できること。

- k3s の既定の kubeconfig（`/etc/rancher/k3s/k3s.yaml`）は `root` 所有・パーミッション 600 のため、一般ユーザーからは直接読めない。
- `SETUP.md` の手順どおり `~/.kube/config` にコピーし、当該ユーザー所有にしておく必要がある。
- `KUBECONFIG` 環境変数で別パスを指す運用でもよい。

#### Kubernetes レベル: RBAC

kubeconfig が示す認証主体が、以下の操作を行える権限を持つこと。

| 操作 | 必要なスコープ |
|---|---|
| namespace の作成 | クラスタスコープ（`namespaces` の create/get） |
| Secret の作成・更新 | `app` namespace の `secrets` の create/apply |
| Helm デプロイ（MariaDB / 監視） | `app` / `monitoring` namespace の広範なリソース操作（Deployment/Service/ConfigMap/PVC/CRD 等）。監視スタックは CRD やクラスタスコープのリソースも作るため、実質 cluster-admin 相当が要る |
| `kubectl apply -k` | `app` namespace の CronJob / ConfigMap の apply |

k3s が生成する既定の kubeconfig は **cluster-admin 相当**のため、上記をすべて満たす。専用の権限を絞った ServiceAccount を用意する場合は、少なくとも namespace 作成（クラスタスコープ）と監視スタックの CRD 作成をカバーする必要がある点に注意。最小権限化は今後の課題（第 9 章）。

> SSH 越しに別ホストから実行する場合も、最終的にコマンドは制御ノード上で走るため、必要な権限はここで述べたものと同じ（実行ユーザーが SSH 先で持つ権限として読み替える）。

## 4. デプロイ順序と依存関係

`deploy_cluster.py` は以下の順序で操作を実行する。順序には意味がある。

```
1. namespace 作成（app / monitoring）
        ↓  Secret / Helm リリースの配置先が必要
2. Helm リポジトリ登録・更新
        ↓  MariaDB / 監視スタックの chart 取得に必要
3. Secret 作成（13 個）
        ↓  MariaDB は mariadb-auth を、CronJob は各 Secret を参照
4. MariaDB / 監視スタック Helm デプロイ
        ↓  ★ここで DB 初期化（手動）が必要 → 4.1 参照
5. アプリ CronJob / ConfigMap 適用（kubectl apply -k）
```

### 4.1 DB 初期化ギャップ（重要）

ステップ 4（MariaDB デプロイ）とステップ 5（アプリ適用）の**間**に、手動の DB 初期化が必要になる。

理由:
- CronJob は `eol_watch` / `inventory_scan` / `mitre_attack` のテーブルが存在する前提で動く
- テーブル作成（`init-appdb.sql` / `init-mitre.sql` など）は MariaDB Pod が Running になってから実行する必要がある
- DB ユーザー（`eol_app` / `inv_app` / `mitre_app`）作成は root パスワードを使う手動操作

ミニマムスタートでは、この初期化を pyinfra に含めず、次のいずれかで対処する。

- **初回構築時**: ステップ 4 の後に `mariadb/schema.md` の初期セットアップ手順を手動実行し、その後ステップ 5 を実行する
- **再構築時（PVC が残っている場合）**: テーブルは永続化されているため初期化不要。`deploy_cluster.py` をそのまま通しで実行してよい

このギャップを運用でどう埋めるかは第 8 章で扱う。

## 5. Secret 設計

### 5.1 Secret 一覧と値のマッピング

`.env` の環境変数から各 Secret を組み立てる。DB ユーザー・DB 名・host の対応は **稼働中クラスタの実態**（`kubectl get secret ... -o jsonpath` で確認）に準拠する。README / schema.md の記載は一部実態とずれているため、実態を正とした（第 5.4 章参照）。

| Secret 名 | 型 | user | database | host | パスワード源（.env） |
|---|---|---|---|---|---|
| `mariadb-auth` | generic | — | — | — | `MARIADB_ROOT_PASSWORD` / `MARIADB_HELM_APPUSER_PASSWORD` |
| `eol-watch-db` | generic | `eol_app` | `eol_watch` | FQDN | `DB_EOL_APP_PASSWORD` |
| `mitre-attack-db` | generic | `mitre_app` | `mitre_attack` | FQDN | `DB_MITRE_APP_PASSWORD` |
| `inventory-scan-db` | generic | `inv_app` | `inventory_scan` | FQDN | `DB_INV_APP_PASSWORD` |
| `cve-watch-db` | generic | `inv_app` | `inventory_scan` | FQDN | `DB_INV_APP_PASSWORD` |
| `epss-db` | generic | `inv_app` | `inventory_scan` | FQDN | `DB_INV_APP_PASSWORD` |
| `eol-watch-slack` | generic | — | — | — | `EOL_WATCH_SLACK_WEBHOOK` |
| `mitre-attack-slack` | generic | — | — | — | `MITRE_ATTACK_SLACK_WEBHOOK` |
| `mirror-check-slack` | generic | — | — | — | `MIRROR_CHECK_SLACK_WEBHOOK` |
| `inventory-scan-slack` | generic | — | — | — | `INVENTORY_SCAN_SLACK_WEBHOOK` |
| `cve-watch-slack` | generic | — | — | — | `CVE_WATCH_SLACK_WEBHOOK` |
| `epss-slack` | generic | — | — | — | `EPSS_SLACK_WEBHOOK` |
| `ghcr-secret` | docker-registry | — | — | — | `GHCR_USERNAME` / `GHCR_PAT` / `GHCR_EMAIL` |

- `FQDN` = `mariadb.app.svc.cluster.local`
- DB 接続ユーザーは 3 系統: `inv_app`（CVE/KEV/EPSS/inventory 共用）/ `eol_app`（EOL）/ `mitre_app`（MITRE）。それぞれ別パスワード。
- `inv_app` を使う 3 つの Secret（cve-watch / epss / inventory-scan）は同一パスワード（`DB_INV_APP_PASSWORD`）を共有する。

### 5.2 Secret 値の管理方針

- 実値は `.env` に置き、`.gitignore`（`.env` / `.env.*`、ただし `!.env.example`）で除外する
- `.env.example` にキーの一覧だけを置き、テンプレートとして配布する
- 既存の `SECURITY.md` の Secret 管理方針と整合させる
- ミニマムスタートでは平文 `.env` を許容する。SOPS/age による暗号化管理は今後の課題（第 9 章）

#### 引数渡しのリスク（許容する前提）

Secret 値は `kubectl create secret --from-literal=...` の**コマンドライン引数**として渡す。コマンドライン引数は実行の一瞬、対象ホスト上の `ps` や `/proc/<pid>/cmdline` から他ユーザーに見え得る（[一般的な指針](https://stackoverflow.com/questions/68441903/is-it-safe-to-pass-github-secrets-as-an-argument-to-a-python-code)）。

本環境は単一ノードの POC で、対象ホストに非信頼ユーザーがいない前提のため、このリスクを許容する。値のシェルインジェクション対策として、埋め込むすべての値はシングルクォートで囲みエスケープする（`deploy_cluster.py` の `sq()`）。STDIN 経由の受け渡しや SOPS/External Secrets への移行は今後の課題（第 9 章）。

> Content was rephrased for compliance with licensing restrictions.

### 5.3 Secret 作成の冪等化

`kubectl create secret ... --dry-run=client -o yaml | kubectl apply -f -` パターンを使う。これにより:

- Secret が存在しなければ新規作成
- 既に存在すれば値を上書き（PAT ローテーション時などに再実行できる）

### 5.4 実態とドキュメントの差異（確認済み）

稼働中クラスタの Secret を確認した結果、README / schema.md の記載と以下の差異があった。**実態を正**として本スクリプトに反映済み。

| 項目 | README / schema.md の記載 | 実態（正） |
|---|---|---|
| CVE/EPSS 系の DB ユーザー | `appuser` | `inv_app` |
| CVE/EPSS 系の DB 名 | `appdb` | `inventory_scan` |
| EOL の DB ユーザー / DB 名 | `appuser` / `appdb` | `eol_app` / `eol_watch` |
| MITRE の DB ユーザー | `mitre` | `mitre_app` |
| host | `mariadb`（短縮名）中心 | `mariadb.app.svc.cluster.local`（FQDN）中心 |
| `epss-db` の host | — | 実態は短縮名 `mariadb` だが、本スクリプトは FQDN に統一（同 namespace では DNS 解決が等価なため機能差なし） |

確認方法（実行済み）:

```bash
kubectl get secret <name> -n app -o jsonpath='{.data.database}' | base64 -d
```

> `README.md` と `mariadb/schema.md` の該当記載は実態とずれている。これらの修正は本デプロイ自動化のスコープ外だが、別タスクで揃えるべき（第 9 章の課題）。

## 6. 冪等性の設計

再実行して安全であることを全操作で担保する。

| 操作 | 冪等化の方法 |
|---|---|
| namespace | `kubectl get ... \|\| kubectl create ...`（存在すればスキップ） |
| Helm リポジトリ | `helm repo add ... --force-update` |
| Secret | `create --dry-run=client -o yaml \| kubectl apply -f -` |
| Helm デプロイ | `helm upgrade --install` |
| アプリ適用 | `kubectl apply -k`（宣言的適用） |

## 7. エラーハンドリング

| ケース | 挙動 |
|---|---|
| `.env` が存在しない | `load_env()` が `FileNotFoundError` を送出し、コピー手順を案内して停止 |
| `.env` の必須値が空 | `require()` が `ValueError` を送出し、該当キー名を示して停止 |
| いずれかの操作が失敗 | pyinfra が当該ホストで停止。原因を修正して再実行（冪等なので途中からで安全） |

Secret 値の欠落は「デプロイを始める前」に検出したいため、`require()` はスクリプト読み込み時（operations 組み立て時）に評価される。値が 1 つでも欠けていれば、実際の `kubectl` 実行に入る前に止まる。

## 8. 運用手順

### 8.1 初回構築

```
（前提: SETUP.md に従い k3s / helm / kubectl が導入済み。
        制御ノードにリポジトリを clone 済みで、deploy/ に cd している）
1. cp .env.example .env && .env を編集
2. pyinfra @local deploy_cluster.py
   → namespace / repo / Secret / MariaDB / 監視 / apply -k まで実行される
3. MariaDB Pod が Running になったら DB 初期化（mariadb/schema.md）
   ※ アプリ CronJob が正しく動くのはこのステップ完了後
```

> 補足: ステップ 2 で `apply -k` まで一気に実行されるが、DB 初期化前は CronJob が DB 接続に失敗する。CronJob は graceful に終了する設計（exit 0）のため、初期化完了後の次回スケジュールから正常動作する。急ぐ場合は初期化後に手動で Job を起動する。

### 8.2 再構築（PVC が残存）

DB テーブルは永続化されているため初期化は不要。制御ノード上で `pyinfra @local deploy_cluster.py` を通しで実行するだけでよい。

### 8.3 Secret のローテーション

`.env` を更新して `deploy_cluster.py` を再実行すれば、対象 Secret が上書きされる。個別の Secret だけ更新したい場合は従来どおり手動 `kubectl` でもよい。

### 8.4 ドライラン

```bash
pyinfra @local deploy_cluster.py --dry
```

実行される操作の一覧だけを表示し、実際の変更は行わない。本番実行前の確認に使う。

## 9. 今後の課題

- **SSH 越し実行のサポート**: 現状は制御ノード上の `@local` 実行に限定（第 3 章）。リモートの実行元から SSH で流すには、values / SQL / kustomize ツリーを `files.put` / `files.rsync` で対象ホストへ転送し、転送先パスで helm / kubectl を実行する仕組みが必要。`inventory.py` はその布石として残してある
- **README / schema.md の記載修正**: 本スクリプトは実態（第 5.4 章）に合わせたが、`README.md` の Secret 作成例と `mariadb/schema.md` の DB 構成表には `appuser` / `appdb` など実態とずれた記載が残っている。別タスクで実態に揃える
- **DB 初期化の自動化**: MariaDB Pod の Ready 待ち + `init-*.sql` 投入 + mitre ユーザー作成を pyinfra 化し、ステップ 4/5 のギャップを埋める
- **Secret の暗号化管理**: 平文 `.env` から SOPS/age や External Secrets Operator への移行
- **RBAC 最小権限化**: 現状は cluster-admin 相当の kubeconfig を前提としている（第 3.1 章）。デプロイ専用の ServiceAccount を作り、必要最小限の権限に絞る
- **ホスト構築層の取り込み**: SETUP.md の OS 初期設定・k3s install・helm install を pyinfra operations 化（`deploy_host.py` の新設）
- **GitOps への発展**: 単一ノード POC を越える場合、`apply -k` 部分を ArgoCD / Flux に委譲する選択肢の検討
- **CI 連携**: `validate-manifests`（kustomize build \| kubeconform）と同様に、pyinfra スクリプトの構文検証を CI に組み込む

## 10. 関連ドキュメント

- [デプロイ自動化の使い方](README.md)
- [環境構築ガイド（ホスト構築）](../SETUP.md)
- [Mitori 全体 README](../README.md)
- [DB スキーマ・初期セットアップ手順](../mariadb/schema.md)
- [セキュリティ評価・改善項目](../SECURITY.md)

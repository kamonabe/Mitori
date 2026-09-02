"""Mitori クラスタデプロイ（ミニマムスタート版）

このデプロイスクリプトがカバーする範囲:
  - namespace 作成（app / monitoring）
  - Helm リポジトリ登録・更新
  - Secret 作成（.env から値を読み込み）
  - MariaDB / 監視スタックの Helm デプロイ
  - アプリ CronJob / ConfigMap の kubectl apply -k

カバーしない範囲（ミニマムスタートのため対象外。手動 or 別途検討）:
  - ホスト構築（OS 初期設定・firewalld・k3s install・helm install）→ ../SETUP.md
  - DB 初期化 SQL の投入 → ../mariadb/schema.md
  - k3s クラスタ自体の作り直し

実行モデル（ミニマムスタート）:
  制御ノード上での @local 実行に限定する。REPO_ROOT（下記）は
  pyinfra 起動ホスト上の絶対パスとして評価され、それを server.shell の
  コマンドに埋め込む。起動ホストと実行ホストが同一（@local）でないと
  パスが一致せず失敗するため、SSH 越し実行は非対応（deploy-design.md 第3章）。

前提:
  - k3s 制御ノード自身で実行すること（リポジトリを clone 済み）
  - そのホストで kubectl / helm が利用可能で、kubeconfig が有効なこと
  - deploy/.env に Secret 値が埋まっていること（.env.example 参照）

実行例:
  cd deploy
  pyinfra @local deploy_cluster.py
  pyinfra @local deploy_cluster.py --dry   # 事前確認
"""

from pathlib import Path

from pyinfra.operations import server

# リポジトリルート（deploy/ の一つ上）。helm -f / kubectl apply -k の
# ファイル参照に使う。これは pyinfra 起動ホスト上の絶対パスであり、
# @local 実行（起動ホスト == 実行ホスト）を前提とする（docstring 参照）。
REPO_ROOT = Path(__file__).resolve().parent.parent


def load_env() -> dict:
    """deploy/.env を読み込んで dict で返す。

    値の欠落は後段の各処理で個別にチェックする（早期に全滅させない）。
    """
    env_path = Path(__file__).resolve().parent / ".env"
    values: dict[str, str] = {}
    if not env_path.exists():
        raise FileNotFoundError(
            f".env が見つかりません: {env_path}\n.env.example をコピーして値を埋めてください: cp .env.example .env"
        )
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        values[key.strip()] = val.strip()
    return values


ENV = load_env()


def require(key: str) -> str:
    """必須の環境変数を取り出す。未設定なら分かりやすく落とす。"""
    val = ENV.get(key, "").strip()
    if not val:
        raise ValueError(f".env の {key} が未設定です。値を埋めてから再実行してください。")
    return val


def sq(value: str) -> str:
    """シェル用にシングルクォートで安全に囲む。

    値内のシングルクォートは '\\'' に置換する（POSIX シェルの定石）。
    Secret 値をコマンドに埋める箇所すべてで使い、インジェクションを防ぐ。

    注意: --from-literal 等の引数に渡す以上、実行の一瞬は対象ホストの
    `ps` / /proc から値が見え得る（deploy-design.md 第5.2章 参照）。
    単一ノード POC 前提で許容し、将来は SOPS 等へ移行する。
    """
    escaped = value.replace("'", "'\\''")
    return f"'{escaped}'"


# ---------------------------------------------------------------------------
# 0. 前提コマンドの存在確認（fail fast）
# ---------------------------------------------------------------------------
server.shell(
    name="kubectl / helm の存在を確認",
    commands=[
        "command -v kubectl >/dev/null 2>&1 || { echo 'kubectl が見つかりません' >&2; exit 1; }",
        "command -v helm >/dev/null 2>&1 || { echo 'helm が見つかりません' >&2; exit 1; }",
    ],
)


# ---------------------------------------------------------------------------
# 1. Namespace
# ---------------------------------------------------------------------------
for ns in ("app", "monitoring"):
    server.shell(
        name=f"namespace {ns} を作成（存在すればスキップ）",
        commands=[f"kubectl get namespace {ns} >/dev/null 2>&1 || kubectl create namespace {ns}"],
    )


# ---------------------------------------------------------------------------
# 2. Helm リポジトリ登録・更新
# ---------------------------------------------------------------------------
helm_repos = {
    "bitnami": "https://charts.bitnami.com/bitnami",
    "prometheus-community": "https://prometheus-community.github.io/helm-charts",
    "grafana": "https://grafana.github.io/helm-charts",
}
for repo_name, repo_url in helm_repos.items():
    server.shell(
        name=f"Helm リポジトリ {repo_name} を登録",
        commands=[f"helm repo add {repo_name} {repo_url} --force-update"],
    )
server.shell(
    name="Helm リポジトリを更新",
    commands=["helm repo update"],
)


# ---------------------------------------------------------------------------
# 3. Secret 作成（.env の値から）
#    冪等化のため create --dry-run=client -o yaml | apply -f - パターンを使う。
#    既存 Secret があっても値を上書きできる。
# ---------------------------------------------------------------------------


def apply_generic_secret(name: str, literals: dict[str, str]) -> None:
    from_literals = " ".join(f"--from-literal={k}={sq(v)}" for k, v in literals.items())
    server.shell(
        name=f"Secret {name} を作成/更新",
        commands=[
            f"kubectl create secret generic {name} -n app {from_literals} --dry-run=client -o yaml | kubectl apply -f -"
        ],
    )


# DB 接続先の共通定数（稼働中クラスタの実態に準拠）
# host は FQDN が主流。DB ユーザーはサービス群ごとに分かれている。
MARIADB_FQDN = "mariadb.app.svc.cluster.local"

# MariaDB Helm 認証
apply_generic_secret(
    "mariadb-auth",
    {
        "mariadb-root-password": require("MARIADB_ROOT_PASSWORD"),
        "mariadb-password": require("MARIADB_HELM_APPUSER_PASSWORD"),
    },
)

# EOL Watch（eol_app / eol_watch）
apply_generic_secret(
    "eol-watch-db",
    {
        "host": MARIADB_FQDN,
        "username": "eol_app",
        "password": require("DB_EOL_APP_PASSWORD"),
        "database": "eol_watch",
    },
)
apply_generic_secret("eol-watch-slack", {"webhook-url": require("EOL_WATCH_SLACK_WEBHOOK")})

# MITRE ATT&CK（mitre_app / mitre_attack）
apply_generic_secret(
    "mitre-attack-db",
    {
        "host": MARIADB_FQDN,
        "username": "mitre_app",
        "password": require("DB_MITRE_APP_PASSWORD"),
        "database": "mitre_attack",
    },
)
apply_generic_secret("mitre-attack-slack", {"webhook-url": require("MITRE_ATTACK_SLACK_WEBHOOK")})

# EPEL ミラー監視（DB 不要、Slack のみ）
apply_generic_secret("mirror-check-slack", {"webhook-url": require("MIRROR_CHECK_SLACK_WEBHOOK")})

# Inventory Scan（inv_app / inventory_scan）
apply_generic_secret(
    "inventory-scan-db",
    {
        "host": MARIADB_FQDN,
        "username": "inv_app",
        "password": require("DB_INV_APP_PASSWORD"),
        "database": "inventory_scan",
    },
)
apply_generic_secret("inventory-scan-slack", {"webhook-url": require("INVENTORY_SCAN_SLACK_WEBHOOK")})

# CVE Watch / KEV（inv_app / inventory_scan を共用）
apply_generic_secret(
    "cve-watch-db",
    {
        "host": MARIADB_FQDN,
        "username": "inv_app",
        "password": require("DB_INV_APP_PASSWORD"),
        "database": "inventory_scan",
    },
)
apply_generic_secret("cve-watch-slack", {"webhook-url": require("CVE_WATCH_SLACK_WEBHOOK")})

# EPSS（inv_app / inventory_scan を共用。実態で host は短縮名だが FQDN で統一）
apply_generic_secret(
    "epss-db",
    {
        "host": MARIADB_FQDN,
        "username": "inv_app",
        "password": require("DB_INV_APP_PASSWORD"),
        "database": "inventory_scan",
    },
)
apply_generic_secret("epss-slack", {"webhook-url": require("EPSS_SLACK_WEBHOOK")})

# GHCR イメージ Pull 用（docker-registry 型）
server.shell(
    name="Secret ghcr-secret を作成/更新",
    commands=[
        "kubectl create secret docker-registry ghcr-secret -n app "
        f"--docker-server=ghcr.io "
        f"--docker-username={sq(require('GHCR_USERNAME'))} "
        f"--docker-password={sq(require('GHCR_PAT'))} "
        f"--docker-email={sq(require('GHCR_EMAIL'))} "
        "--dry-run=client -o yaml | kubectl apply -f -"
    ],
)


# ---------------------------------------------------------------------------
# 4. MariaDB / 監視スタック（Helm）
# ---------------------------------------------------------------------------
server.shell(
    name="MariaDB を Helm デプロイ",
    commands=[f"helm upgrade --install mariadb bitnami/mariadb -n app -f {REPO_ROOT}/mariadb/mariadb-values.yaml"],
)
server.shell(
    name="kube-prometheus-stack を Helm デプロイ",
    commands=[
        f"helm upgrade --install monitoring prometheus-community/kube-prometheus-stack "
        f"-n monitoring -f {REPO_ROOT}/monitoring/monitoring-values.yaml"
    ],
)
server.shell(
    name="Loki を Helm デプロイ",
    commands=[f"helm upgrade --install loki grafana/loki -n monitoring -f {REPO_ROOT}/monitoring/loki-values.yaml"],
)
server.shell(
    name="Grafana Alloy（k8s-monitoring）を Helm デプロイ",
    commands=[
        f"helm upgrade --install k8s-monitoring grafana/k8s-monitoring "
        f"-n monitoring -f {REPO_ROOT}/monitoring/k8s-monitoring-values.yaml"
    ],
)


# ---------------------------------------------------------------------------
# 5. アプリ CronJob / ConfigMap
# ---------------------------------------------------------------------------
server.shell(
    name="アプリ CronJob / ConfigMap を kustomize で適用",
    commands=[f"kubectl apply -k {REPO_ROOT}"],
)

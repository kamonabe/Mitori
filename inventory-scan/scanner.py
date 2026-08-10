"""inventory-scan: クラスター内コンポーネントのバージョンを収集しDBに記録する."""

import json
import os
import re
import subprocess
from datetime import datetime, timezone

import pymysql
import requests

DB_HOST = os.environ.get("DB_HOST", "")
DB_USER = os.environ.get("DB_USER", "")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "")
DB_NAME = os.environ.get("DB_NAME", "")
SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL", "")

NOTIFY_MAX_ITEMS = 5
CMD_TIMEOUT = 30


def get_conn():
    """MariaDB接続を取得する."""
    return pymysql.connect(
        host=DB_HOST,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
        charset="utf8mb4",
        autocommit=False,
        cursorclass=pymysql.cursors.DictCursor,
        connect_timeout=10,
        read_timeout=10,
    )


def ensure_table(conn):
    """inventoryテーブルが存在しなければ作成する."""
    ddl = """
    CREATE TABLE IF NOT EXISTS inventory (
        component VARCHAR(100) NOT NULL,
        category VARCHAR(50) NOT NULL,
        version VARCHAR(50) NOT NULL,
        source VARCHAR(10) NOT NULL DEFAULT 'auto',
        scanned_at DATETIME NOT NULL,
        prev_version VARCHAR(50) DEFAULT NULL,
        UNIQUE KEY uq_component_category (component, category)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """
    with conn.cursor() as cur:
        cur.execute(ddl)
    conn.commit()


def upsert_record(conn, component, category, version, source="auto"):
    """レコードをINSERT or UPDATE し、変更があったかどうかを返す."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    sql = """
    INSERT INTO inventory (component, category, version, source, scanned_at, prev_version)
    VALUES (%s, %s, %s, %s, %s, NULL)
    ON DUPLICATE KEY UPDATE
        prev_version = CASE WHEN version != VALUES(version) THEN version ELSE prev_version END,
        version = VALUES(version),
        source = VALUES(source),
        scanned_at = VALUES(scanned_at)
    """
    with conn.cursor() as cur:
        # まず既存レコードを確認
        cur.execute(
            "SELECT version FROM inventory WHERE component=%s AND category=%s",
            (component, category),
        )
        existing = cur.fetchone()
        cur.execute(sql, (component, category, version, source, now))
    conn.commit()

    if existing is None:
        # 新規レコード（初回）
        return None
    if existing["version"] != version:
        # バージョン変更あり
        return existing["version"]
    # 変更なし
    return False


def run_cmd(args, timeout=CMD_TIMEOUT):
    """外部コマンドを実行してstdoutを返す. 失敗時はNone."""
    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode != 0:
            print(f"エラー: コマンド失敗 {' '.join(args)}: {result.stderr.strip()}")
            return None
        return result.stdout
    except subprocess.TimeoutExpired:
        print(f"エラー: タイムアウト {' '.join(args)} ({timeout}秒)")
        return None
    except Exception as e:
        print(f"エラー: コマンド実行失敗 {' '.join(args)}: {e}")
        return None


def collect_k3s_version():
    """k3sバージョンを取得する."""
    output = run_cmd(["kubectl", "version", "-o", "json"])
    if output is None:
        return None
    try:
        data = json.loads(output)
        version = data.get("serverVersion", {}).get("gitVersion", "")
        if not version:
            print("エラー: k3s serverVersion.gitVersion が空")
            return None
        return version
    except json.JSONDecodeError as e:
        print(f"エラー: kubectl version JSONパース失敗: {e}")
        return None


def collect_mariadb_version(conn):
    """MariaDBバージョンをSQLで取得する."""
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT VERSION() AS ver")
            row = cur.fetchone()
            if not row or not row.get("ver"):
                print("エラー: SELECT VERSION() が空を返しました")
                return None
            return row["ver"]
    except pymysql.Error as e:
        print(f"エラー: MariaDBバージョン取得失敗: {e}")
        return None


def collect_helm_releases():
    """Helmリリース一覧を取得する."""
    output = run_cmd(["helm", "list", "-A", "-o", "json"])
    if output is None:
        return []
    try:
        releases = json.loads(output)
        if not isinstance(releases, list):
            print("エラー: helm list の出力がリストではありません")
            return []
        return releases
    except json.JSONDecodeError as e:
        print(f"エラー: helm list JSONパース失敗: {e}")
        return []


def extract_chart_version(chart_field):
    """chartフィールドからバージョン部分を抽出する (例: 'mariadb-22.0.3' → '22.0.3')."""
    match = re.search(r"-(\d+\.\d+\.\d+.*)$", chart_field)
    if match:
        return match.group(1)
    return chart_field


def collect_container_images():
    """全PodのコンテナイメージをGET /pods から収集する."""
    output = run_cmd(["kubectl", "get", "pods", "-A", "-o", "json"])
    if output is None:
        return []
    try:
        data = json.loads(output)
    except json.JSONDecodeError as e:
        print(f"エラー: kubectl get pods JSONパース失敗: {e}")
        return []

    images = set()
    for item in data.get("items", []):
        spec = item.get("spec", {})
        containers = spec.get("containers", []) + spec.get("initContainers", [])
        for container in containers:
            image = container.get("image", "")
            if image:
                images.add(image)
    return list(images)


def parse_image_ref(image):
    """イメージ参照をコンポーネント名とバージョンに分割する."""
    # digest形式: image@sha256:...
    if "@" in image:
        parts = image.split("@", 1)
        return parts[0], parts[1]
    # tag形式: image:tag
    if ":" in image:
        # ポート番号を含むレジストリに注意: registry:5000/repo:tag
        # 最後の : の後がタグ（ただし / を含まない）
        last_colon = image.rfind(":")
        after_colon = image[last_colon + 1 :]
        if "/" not in after_colon:
            return image[:last_colon], after_colon
    # タグなし
    return image, "latest"


def send_slack_notification(changes):
    """バージョン変更をSlackに通知する."""
    if not SLACK_WEBHOOK_URL:
        return
    if not changes:
        return

    count = len(changes)
    lines = []
    if count <= NOTIFY_MAX_ITEMS:
        lines.append(f"📦 inventory-scan: {count}件のバージョン変更を検知")
    else:
        lines.append(f"📦 inventory-scan: {count}件のバージョン変更を検知しました")

    lines.append("")
    for change in changes[:NOTIFY_MAX_ITEMS]:
        comp = change["component"]
        old = change["prev_version"] or "(新規)"
        new = change["version"]
        lines.append(f"  • {comp}: {old} → {new}")

    if count > NOTIFY_MAX_ITEMS:
        lines.append(f"  ... 他 {count - NOTIFY_MAX_ITEMS} 件")

    text = "\n".join(lines)
    try:
        requests.post(SLACK_WEBHOOK_URL, json={"text": text}, timeout=10)
    except requests.RequestException as e:
        print(f"エラー: Slack通知失敗: {e}")


def main():
    """メイン処理."""
    # DB接続
    try:
        conn = get_conn()
    except pymysql.Error as e:
        print(f"エラー: DB接続失敗: {e}")
        return
    except Exception as e:
        print(f"エラー: DB接続中に予期しないエラー: {e}")
        return

    ensure_table(conn)

    changes = []

    # 1. k3sバージョン収集
    print("--- k3sバージョン収集 ---")
    k3s_ver = collect_k3s_version()
    if k3s_ver:
        prev = upsert_record(conn, "k3s", "runtime", k3s_ver)
        if prev and prev is not False:
            changes.append({"component": "k3s", "prev_version": prev, "version": k3s_ver})
            print(f"  k3s: {prev} → {k3s_ver}")
        elif prev is None:
            changes.append({"component": "k3s", "prev_version": None, "version": k3s_ver})
            print(f"  k3s: (新規) {k3s_ver}")
        else:
            print(f"  k3s: {k3s_ver} (変更なし)")

    # 2. MariaDBバージョン収集
    print("--- MariaDBバージョン収集 ---")
    maria_ver = collect_mariadb_version(conn)
    if maria_ver:
        prev = upsert_record(conn, "mariadb", "database", maria_ver)
        if prev and prev is not False:
            changes.append({"component": "mariadb", "prev_version": prev, "version": maria_ver})
            print(f"  mariadb: {prev} → {maria_ver}")
        elif prev is None:
            changes.append({"component": "mariadb", "prev_version": None, "version": maria_ver})
            print(f"  mariadb: (新規) {maria_ver}")
        else:
            print(f"  mariadb: {maria_ver} (変更なし)")

    # 3. Helmチャートバージョン収集
    print("--- Helmチャートバージョン収集 ---")
    releases = collect_helm_releases()
    # 名前の重複チェック
    name_counts = {}
    for rel in releases:
        name = rel.get("name", "")
        name_counts[name] = name_counts.get(name, 0) + 1

    for rel in releases:
        name = rel.get("name", "")
        namespace = rel.get("namespace", "")
        app_version = rel.get("app_version", "")
        chart = rel.get("chart", "")

        if not name:
            continue

        # コンポーネント名の決定
        if name_counts.get(name, 0) > 1:
            component = f"{name}/{namespace}"
        else:
            component = name

        # バージョンの決定
        version = app_version if app_version else extract_chart_version(chart)
        if not version:
            continue

        prev = upsert_record(conn, component, "helm", version)
        if prev and prev is not False:
            changes.append({"component": component, "prev_version": prev, "version": version})
            print(f"  {component}: {prev} → {version}")
        elif prev is None:
            changes.append({"component": component, "prev_version": None, "version": version})
            print(f"  {component}: (新規) {version}")
        else:
            print(f"  {component}: {version} (変更なし)")

    # 4. コンテナイメージバージョン収集
    print("--- コンテナイメージバージョン収集 ---")
    images = collect_container_images()
    for image_ref in sorted(images):
        component, version = parse_image_ref(image_ref)
        if not component or not version:
            continue

        # コンポーネント名が長すぎる場合は切り詰め
        if len(component) > 100:
            component = component[:100]
        if len(version) > 50:
            version = version[:50]

        prev = upsert_record(conn, component, "container", version)
        if prev and prev is not False:
            changes.append({"component": component, "prev_version": prev, "version": version})
            print(f"  {component}: {prev} → {version}")
        elif prev is None:
            # 初回は変更通知しない（ノイズになるため）
            print(f"  {component}: (新規) {version}")
        else:
            print(f"  {component}: {version} (変更なし)")

    # 5. Slack通知（初回登録は除外し、バージョン変更のみ通知）
    actual_changes = [c for c in changes if c["prev_version"] is not None]
    if actual_changes:
        print(f"\n=== {len(actual_changes)}件のバージョン変更を検知 ===")
        send_slack_notification(actual_changes)
    else:
        print("\n=== バージョン変更なし ===")

    conn.close()
    print("完了")


if __name__ == "__main__":
    main()

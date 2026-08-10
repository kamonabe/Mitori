"""mitre-sync mini: MITRE ATT&CK の生データを正規化し、変更を Slack 通知する."""

import hashlib
import json
import os
from datetime import datetime, timedelta, timezone

import pymysql
import requests

COLLECTION_KEY = "enterprise-attack"
MIN_BACKOFF = 10
MAX_BACKOFF = 360
BACKOFF_STEP = 60
NOTIFY_MAX_ITEMS = 5

DB_HOST = os.environ["DB_HOST"]
DB_USER = os.environ["DB_USER"]
DB_PASSWORD = os.environ["DB_PASSWORD"]
DB_NAME = os.environ["DB_NAME"]
SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL", "")


def get_conn():
    return pymysql.connect(
        host=DB_HOST,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
        charset="utf8mb4",
        autocommit=False,
        cursorclass=pymysql.cursors.DictCursor,
    )


def fetch_unprocessed(conn):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, raw_json FROM mitre_raw_staging WHERE source=%s AND processed_at IS NULL",
            (COLLECTION_KEY,),
        )
        return cur.fetchall()


def get_mitre_external_id(obj):
    for ref in obj.get("external_references", []):
        if ref.get("source_name") == "mitre-attack":
            return ref.get("external_id")
    return None


def compute_hash(normalized: dict) -> str:
    serialized = json.dumps(normalized, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def parse_dt(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def normalize_tactic(obj):
    ext_id = get_mitre_external_id(obj)
    if not ext_id:
        return None
    return {
        "stix_id": obj["id"],
        "tactic_key": obj.get("x_mitre_shortname", ""),
        "external_id": ext_id,
        "name": obj.get("name", ""),
        "description": obj.get("description", ""),
        "is_deprecated": bool(obj.get("x_mitre_deprecated", False)),
        "stix_modified": obj.get("modified"),
    }


def normalize_technique(obj):
    ext_id = get_mitre_external_id(obj)
    if not ext_id:
        return None
    parent_ext_id = ext_id.split(".")[0] if "." in ext_id else None
    tactic_keys = sorted(
        set(kc["phase_name"] for kc in obj.get("kill_chain_phases", []) if kc.get("kill_chain_name") == "mitre-attack")
    )
    return {
        "stix_id": obj["id"],
        "external_id": ext_id,
        "parent_external_id": parent_ext_id,
        "name": obj.get("name", ""),
        "description": obj.get("description", ""),
        "is_subtechnique": bool(obj.get("x_mitre_is_subtechnique", False)),
        "is_deprecated": bool(obj.get("x_mitre_deprecated", False)),
        "is_revoked": bool(obj.get("revoked", False)),
        "stix_modified": obj.get("modified"),
        "tactic_keys": tactic_keys,
    }


def upsert_tactic(conn, n):
    content_hash = compute_hash(n)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, content_hash, is_deprecated FROM mitre_tactics WHERE stix_id=%s",
            (n["stix_id"],),
        )
        row = cur.fetchone()

        if row is None:
            cur.execute(
                """INSERT INTO mitre_tactics
                    (stix_id, tactic_key, external_id, name, description, is_deprecated, content_hash, stix_modified)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                (
                    n["stix_id"],
                    n["tactic_key"],
                    n["external_id"],
                    n["name"],
                    n["description"],
                    n["is_deprecated"],
                    content_hash,
                    parse_dt(n["stix_modified"]),
                ),
            )
            conn.commit()
            return {"type": "tactic", "action": "added", "external_id": n["external_id"], "name": n["name"]}

        if row["content_hash"] == content_hash:
            return None

        action = "deprecated" if (not row["is_deprecated"] and n["is_deprecated"]) else "updated"
        cur.execute(
            """UPDATE mitre_tactics
            SET tactic_key=%s, external_id=%s, name=%s, description=%s,
                is_deprecated=%s, content_hash=%s, stix_modified=%s
            WHERE stix_id=%s""",
            (
                n["tactic_key"],
                n["external_id"],
                n["name"],
                n["description"],
                n["is_deprecated"],
                content_hash,
                parse_dt(n["stix_modified"]),
                n["stix_id"],
            ),
        )
    conn.commit()
    return {"type": "tactic", "action": action, "external_id": n["external_id"], "name": n["name"]}


def upsert_technique(conn, n):
    content_hash = compute_hash({k: v for k, v in n.items() if k != "tactic_keys"})
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, content_hash, is_deprecated, is_revoked FROM mitre_techniques WHERE stix_id=%s",
            (n["stix_id"],),
        )
        row = cur.fetchone()

        action = None
        if row is None:
            cur.execute(
                """INSERT INTO mitre_techniques
                    (stix_id, external_id, parent_external_id, name, description,
                     is_subtechnique, is_deprecated, is_revoked, content_hash, stix_modified)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (
                    n["stix_id"],
                    n["external_id"],
                    n["parent_external_id"],
                    n["name"],
                    n["description"],
                    n["is_subtechnique"],
                    n["is_deprecated"],
                    n["is_revoked"],
                    content_hash,
                    parse_dt(n["stix_modified"]),
                ),
            )
            action = "added"
        elif row["content_hash"] != content_hash:
            cur.execute(
                """UPDATE mitre_techniques
                SET external_id=%s, parent_external_id=%s, name=%s, description=%s,
                    is_subtechnique=%s, is_deprecated=%s, is_revoked=%s, content_hash=%s, stix_modified=%s
                WHERE stix_id=%s""",
                (
                    n["external_id"],
                    n["parent_external_id"],
                    n["name"],
                    n["description"],
                    n["is_subtechnique"],
                    n["is_deprecated"],
                    n["is_revoked"],
                    content_hash,
                    parse_dt(n["stix_modified"]),
                    n["stix_id"],
                ),
            )
            if not row["is_deprecated"] and n["is_deprecated"]:
                action = "deprecated"
            elif not row["is_revoked"] and n["is_revoked"]:
                action = "revoked"
            else:
                action = "updated"

        cur.execute("SELECT id FROM mitre_techniques WHERE stix_id=%s", (n["stix_id"],))
        technique_id = cur.fetchone()["id"]

    conn.commit()
    sync_tactic_map(conn, technique_id, n["tactic_keys"])

    if action is None:
        return None
    return {"type": "technique", "action": action, "external_id": n["external_id"], "name": n["name"]}


def sync_tactic_map(conn, technique_id, tactic_keys):
    with conn.cursor() as cur:
        if not tactic_keys:
            cur.execute("DELETE FROM mitre_technique_tactic_map WHERE technique_id=%s", (technique_id,))
            conn.commit()
            return

        placeholders = ",".join(["%s"] * len(tactic_keys))
        cur.execute(
            f"SELECT id, tactic_key FROM mitre_tactics WHERE tactic_key IN ({placeholders})",
            tactic_keys,
        )
        tactic_id_map = {r["tactic_key"]: r["id"] for r in cur.fetchall()}
        tactic_ids = [tactic_id_map[k] for k in tactic_keys if k in tactic_id_map]

        cur.execute("DELETE FROM mitre_technique_tactic_map WHERE technique_id=%s", (technique_id,))
        for tid in tactic_ids:
            cur.execute(
                "INSERT IGNORE INTO mitre_technique_tactic_map (technique_id, tactic_id) VALUES (%s, %s)",
                (technique_id, tid),
            )
    conn.commit()


def build_category_block(label, events):
    total = len(events)
    lines = [f"{label} ({total}件)"]
    for e in events[:NOTIFY_MAX_ITEMS]:
        lines.append(f"  • {e['external_id']:<12} {e['name']}")
    if total > NOTIFY_MAX_ITEMS:
        lines.append(f"  上記も含め、{total}件の変更を検知しました")
    return "\n".join(lines)


def notify_slack(events):
    if not SLACK_WEBHOOK_URL:
        print("SLACK_WEBHOOK_URL が未設定のため通知をスキップします。")
        return
    if not events:
        return

    categorized = {"added": [], "updated": [], "deprecated": [], "revoked": []}
    for e in events:
        if e["action"] in categorized:
            categorized[e["action"]].append(e)

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    blocks = [f":bell: *MITRE ATT&CK 変更検知 ({today})*"]

    if categorized["added"]:
        blocks.append(build_category_block(":new: 新規追加", categorized["added"]))
    if categorized["updated"]:
        blocks.append(build_category_block(":pencil2: 更新", categorized["updated"]))
    if categorized["deprecated"]:
        blocks.append(build_category_block(":no_entry_sign: 廃止 (deprecated)", categorized["deprecated"]))
    if categorized["revoked"]:
        blocks.append(build_category_block(":wastebasket: 取り消し (revoked)", categorized["revoked"]))

    text = "\n\n".join(blocks)
    try:
        resp = requests.post(SLACK_WEBHOOK_URL, json={"text": text}, timeout=10)
        resp.raise_for_status()
        print(f"Slack通知送信完了 (合計{len(events)}件の変更)")
    except requests.RequestException as e:
        print(f"Slack通知失敗: {e}")


def mark_processed(conn, ids):
    if not ids:
        return
    with conn.cursor() as cur:
        cur.executemany(
            "UPDATE mitre_raw_staging SET processed_at=NOW() WHERE id=%s",
            [(i,) for i in ids],
        )
    conn.commit()


def cleanup_old_processed(conn):
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM mitre_raw_staging WHERE processed_at IS NOT NULL AND processed_at < NOW() - INTERVAL 7 DAY"
        )
        deleted = cur.rowcount
    conn.commit()
    if deleted > 0:
        print(f"Cleanup: {deleted}件の処理済みレコードを削除しました")


def update_schedule(conn, had_changes):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT backoff_minutes FROM mitre_taxii_cursor WHERE collection_id=%s",
            (COLLECTION_KEY,),
        )
        row = cur.fetchone()
        current_backoff = row["backoff_minutes"] if row and row["backoff_minutes"] else MIN_BACKOFF

    new_backoff = MIN_BACKOFF if had_changes else min(current_backoff + BACKOFF_STEP, MAX_BACKOFF)
    next_run = datetime.now(timezone.utc) + timedelta(minutes=new_backoff)

    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO mitre_taxii_cursor (collection_id, backoff_minutes, next_run_at)
            VALUES (%s, %s, %s)
            ON DUPLICATE KEY UPDATE backoff_minutes=%s, next_run_at=%s""",
            (COLLECTION_KEY, new_backoff, next_run, new_backoff, next_run),
        )
    conn.commit()


def main():
    """メイン処理."""
    conn = None
    try:
        conn = get_conn()
    except pymysql.Error as e:
        print(f"エラー: DB接続失敗: {e}")
        return
    except Exception as e:
        print(f"エラー: DB接続中に予期しないエラー: {e}")
        return

    rows = fetch_unprocessed(conn)
    if not rows:
        print("No unprocessed data. Exiting.")
        conn.close()
        return

    print(f"Found {len(rows)} unprocessed records. Normalizing...")

    had_changes = False
    type_counts = {}
    events = []

    parsed_rows = []
    for row in rows:
        obj = json.loads(row["raw_json"])
        obj_type = obj.get("type")
        type_counts[obj_type] = type_counts.get(obj_type, 0) + 1
        parsed_rows.append((row["id"], obj_type, obj))

    # Pass 1: tactic を先にすべて処理
    for row_id, obj_type, obj in parsed_rows:
        if obj_type == "x-mitre-tactic":
            n = normalize_tactic(obj)
            if n:
                event = upsert_tactic(conn, n)
                if event:
                    events.append(event)
                    had_changes = True

    # Pass 2: technique を処理
    for row_id, obj_type, obj in parsed_rows:
        if obj_type == "attack-pattern":
            n = normalize_technique(obj)
            if n:
                event = upsert_technique(conn, n)
                if event:
                    events.append(event)
                    had_changes = True

    processed_ids = [row_id for row_id, _, _ in parsed_rows]
    mark_processed(conn, processed_ids)
    cleanup_old_processed(conn)
    update_schedule(conn, had_changes)

    conn.close()
    print(f"Done. had_changes={had_changes}, events={len(events)}")
    print(f"Type breakdown: {type_counts}")

    notify_slack(events)


if __name__ == "__main__":
    main()

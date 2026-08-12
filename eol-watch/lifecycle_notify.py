"""lifecycle-notify: 自分が使っているコンポーネントのEOL接近を毎日Slack通知する。

eol-watchが収集したEOLデータと、my_componentsテーブルに登録した
自環境のバージョンを突き合わせ、EOLまでの残り日数が閾値以内のものを通知する。
通知を止めるには my_components のバージョンを更新済みのものに書き換える。
"""

import sys

sys.path.insert(0, "/common")

from datetime import date, datetime

import pymysql
from db import get_conn
from slack import send_slack


def fetch_approaching_eol(conn):
    """my_componentsとeol_snapshotsを突き合わせ、EOLが近いものを返す。"""
    query = """
        SELECT
            mc.product_slug,
            mc.version,
            mc.description,
            mc.notify_before_days,
            jt.eolFrom AS eol_date
        FROM my_components mc
        JOIN monitor_targets mt ON mc.product_slug = mt.product_slug
        JOIN eol_snapshots s ON s.target_id = mt.id
            AND s.collected_at = (
                SELECT MAX(collected_at)
                FROM eol_snapshots
                WHERE target_id = mt.id
            )
        JOIN JSON_TABLE(s.raw_json, '$.releases[*]' COLUMNS(
            name VARCHAR(50) PATH '$.name',
            eolFrom VARCHAR(20) PATH '$.eolFrom'
        )) AS jt ON jt.name COLLATE utf8mb4_uca1400_ai_ci = mc.version
        WHERE jt.eolFrom IS NOT NULL
          AND DATEDIFF(jt.eolFrom, CURDATE()) <= mc.notify_before_days
        ORDER BY DATEDIFF(jt.eolFrom, CURDATE()) ASC
    """
    with conn.cursor() as cur:
        cur.execute(query)
        return cur.fetchall()


def build_message(items):
    """Slack通知メッセージを組み立てる。"""
    today = date.today()
    lines = [f":clock3: *ライフサイクル通知*（{len(items)}件）"]
    for item in items:
        eol_date = datetime.strptime(item["eol_date"], "%Y-%m-%d").date()
        days_remaining = (eol_date - today).days
        desc = f" [{item['description']}]" if item["description"] else ""
        lines.append(
            f"• *{item['product_slug']}* {item['version']} — EOL {item['eol_date']}（残り{days_remaining}日）{desc}"
        )
    lines.append("")
    lines.append("→ 更新したら `my_components` のバージョンを書き換えてね")
    return "\n".join(lines)


def send_webhook(text):
    send_slack(text)


def main():
    try:
        conn = get_conn()
    except pymysql.Error as e:
        print(f"エラー: DB接続失敗: {e}")
        return

    try:
        items = fetch_approaching_eol(conn)
    except Exception as e:
        print(f"エラー: クエリ実行失敗: {e}")
        return
    finally:
        conn.close()

    # 同一 product_slug + version の重複を除去
    seen = set()
    unique_items = []
    for item in items:
        key = (item["product_slug"], item["version"])
        if key not in seen:
            seen.add(key)
            unique_items.append(item)
    items = unique_items

    if not items:
        print("通知対象なし: 全コンポーネントのEOLは十分先です。")
        return

    print(f"通知対象: {len(items)}件")
    for item in items:
        print(f"  - {item['product_slug']} {item['version']} (EOL: {item['eol_date']})")

    message = build_message(items)
    send_webhook(message)
    print("通知完了。")


if __name__ == "__main__":
    main()

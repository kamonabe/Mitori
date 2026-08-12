"""kev-notify: KEV カタログの新規追加を検知して Slack 通知する."""

import os
from datetime import datetime, timezone

import pymysql
import requests

DB_HOST = os.environ.get("DB_HOST", "")
DB_USER = os.environ.get("DB_USER", "")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "")
DB_NAME = os.environ.get("DB_NAME", "")
SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL", "")

NOTIFY_MAX_ITEMS = int(os.environ.get("NOTIFY_MAX_ITEMS", "5"))
KEV_BULK_THRESHOLD = int(os.environ.get("KEV_BULK_THRESHOLD", "50"))


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


def ensure_tables(conn):
    """通知ログテーブルが存在しなければ作成する."""
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS kev_notify_log (
                id INT AUTO_INCREMENT PRIMARY KEY,
                cve_id VARCHAR(50) NOT NULL,
                notified_at DATETIME NOT NULL,
                notification_type VARCHAR(30) NOT NULL DEFAULT 'new_kev',
                INDEX idx_cve_id (cve_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)
    conn.commit()


def get_unnotified_entries(conn):
    """未通知の KEV エントリを取得する."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT k.cve_id, k.vendor, k.product, k.vulnerability_name,
                   k.short_description, k.date_added, k.due_date,
                   k.known_ransomware_use
            FROM kev_catalog k
            LEFT JOIN kev_notify_log n ON k.cve_id = n.cve_id
            WHERE n.id IS NULL
            ORDER BY k.date_added DESC
        """)
        return cur.fetchall()


def is_first_run(conn):
    """初回実行かどうかを判定する（notify_log が空）."""
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS cnt FROM kev_notify_log")
        row = cur.fetchone()
        return row["cnt"] == 0


def mark_notified(conn, entries, notification_type="new_kev"):
    """通知済みとして記録する."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    with conn.cursor() as cur:
        for entry in entries:
            cur.execute(
                """INSERT INTO kev_notify_log (cve_id, notified_at, notification_type)
                VALUES (%s, %s, %s)""",
                (entry["cve_id"], now, notification_type),
            )
    conn.commit()


def send_slack_notification(entries):
    """Slack に KEV 新規追加を通知する."""
    if not SLACK_WEBHOOK_URL:
        print("SLACK_WEBHOOK_URL 未設定: 通知スキップ")
        return

    lines = [f"📋 KEV カタログ新規追加: {len(entries)}件", ""]

    for entry in entries[:NOTIFY_MAX_ITEMS]:
        cve_id = entry["cve_id"]
        date_added = entry["date_added"]
        vendor = entry["vendor"]
        product = entry["product"]
        desc = (entry["short_description"] or "")[:100]
        due_date = entry["due_date"] or "未設定"
        ransomware = entry["known_ransomware_use"] or "Unknown"

        lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        lines.append(f"■ {cve_id} (追加日: {date_added})")
        lines.append(f"  ベンダー: {vendor}")
        lines.append(f"  製品: {product}")
        lines.append(f"  概要: {desc}")
        lines.append(f"  対処期限: {due_date}")
        lines.append(f"  ランサムウェア悪用: {ransomware}")

    if len(entries) > NOTIFY_MAX_ITEMS:
        lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        lines.append(f"... 他 {len(entries) - NOTIFY_MAX_ITEMS} 件")

    text = "\n".join(lines)

    try:
        requests.post(SLACK_WEBHOOK_URL, json={"text": text}, timeout=10)
        print("Slack通知送信完了")
    except requests.RequestException as e:
        print(f"エラー: Slack通知失敗: {e}")


def main():
    """メイン処理."""
    try:
        conn = get_conn()
    except pymysql.Error as e:
        print(f"エラー: DB接続失敗: {e}")
        return

    try:
        ensure_tables(conn)
    except pymysql.Error as e:
        print(f"エラー: テーブル作成失敗: {e}")
        conn.close()
        return

    print("=== kev-notify: KEV 新規追加チェック ===\n")

    # 未通知エントリを取得
    unnotified = get_unnotified_entries(conn)

    if not unnotified:
        print("未通知エントリなし: 終了")
        conn.close()
        return

    print(f"未通知エントリ: {len(unnotified)}件")

    # 初回実行判定
    first_run = is_first_run(conn)

    if first_run and len(unnotified) > KEV_BULK_THRESHOLD:
        # 初回ロード: 通知せずに全件を notify_log に記録
        print(f"初回ロード検知 ({len(unnotified)}件 > 閾値{KEV_BULK_THRESHOLD}件): 通知スキップ")
        mark_notified(conn, unnotified, notification_type="initial_load")
        print(f"初期ロード完了: {len(unnotified)}件を notify_log に記録")
    else:
        # 通常運用: Slack通知
        send_slack_notification(unnotified)
        mark_notified(conn, unnotified, notification_type="new_kev")
        print(f"{len(unnotified)}件を通知済みとして記録")

    conn.close()
    print("完了")


if __name__ == "__main__":
    main()

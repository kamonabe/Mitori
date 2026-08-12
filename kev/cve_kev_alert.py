"""cve-kev-alert: cve-watch 検知済み CVE × KEV を突合して Slack 通知する."""

import os
import sys

sys.path.insert(0, "/common")

from datetime import datetime, timezone

import pymysql
from db import get_conn
from slack import send_slack

SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL", "")

NOTIFY_MAX_ITEMS = int(os.environ.get("NOTIFY_MAX_ITEMS", "5"))


def ensure_tables(conn):
    """通知ログテーブルが存在しなければ作成する."""
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS cve_kev_alert_log (
                id INT AUTO_INCREMENT PRIMARY KEY,
                cve_id VARCHAR(50) NOT NULL,
                component VARCHAR(100) NOT NULL,
                category VARCHAR(50) NOT NULL,
                notified_at DATETIME NOT NULL,
                UNIQUE KEY uq_cve_component (cve_id, component, category)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)
    conn.commit()


def get_unnotified_alerts(conn):
    """cve_entries × kev_catalog で未通知のものを取得する."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT ce.cve_id, ce.component, ce.category, ce.severity,
                   ce.summary, ce.fixed_version,
                   k.vendor, k.product, k.date_added, k.due_date,
                   k.known_ransomware_use
            FROM cve_entries ce
            INNER JOIN kev_catalog k ON ce.cve_id = k.cve_id
            LEFT JOIN cve_kev_alert_log a
              ON ce.cve_id = a.cve_id
              AND ce.component = a.component
              AND ce.category = a.category
            WHERE ce.status = 'open'
              AND a.id IS NULL
            ORDER BY k.date_added DESC
        """)
        return cur.fetchall()


def mark_notified(conn, alerts):
    """通知済みとして記録する."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    with conn.cursor() as cur:
        for alert in alerts:
            cur.execute(
                """INSERT IGNORE INTO cve_kev_alert_log
                (cve_id, component, category, notified_at)
                VALUES (%s, %s, %s, %s)""",
                (alert["cve_id"], alert["component"], alert["category"], now),
            )
    conn.commit()


def send_slack_notification(alerts):
    """Slack に CVE × KEV アラートを通知する."""
    if not SLACK_WEBHOOK_URL:
        print("SLACK_WEBHOOK_URL 未設定: 通知スキップ")
        return

    lines = [
        f"🚨 自環境CVE × KEV 該当: {len(alerts)}件",
        "",
        "以下のCVEは実際に悪用が確認されています。早急な対応を推奨します。",
        "",
    ]

    for alert in alerts[:NOTIFY_MAX_ITEMS]:
        cve_id = alert["cve_id"]
        severity = alert["severity"] or "UNKNOWN"
        component = alert["component"]
        summary = (alert["summary"] or "")[:100]
        date_added = alert["date_added"]
        due_date = alert["due_date"] or "未設定"
        ransomware = alert["known_ransomware_use"] or "Unknown"
        fixed = alert["fixed_version"]

        lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        lines.append(f"■ {cve_id} ({severity})")
        lines.append(f"  対象: {component}")
        lines.append(f"  概要: {summary}")
        if fixed:
            lines.append(f"  修正版: {fixed}")
        lines.append(f"  KEV追加日: {date_added}")
        lines.append(f"  対処期限: {due_date}")
        lines.append(f"  ランサムウェア悪用: {ransomware}")

    if len(alerts) > NOTIFY_MAX_ITEMS:
        lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        lines.append(f"... 他 {len(alerts) - NOTIFY_MAX_ITEMS} 件")

    text = "\n".join(lines)

    send_slack(text)
    print("Slack通知送信完了")


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

    print("=== cve-kev-alert: CVE × KEV 突合チェック ===\n")

    # 未通知アラートを取得
    alerts = get_unnotified_alerts(conn)

    if not alerts:
        print("該当なし: 終了")
        conn.close()
        return

    print(f"未通知アラート: {len(alerts)}件")

    # Slack通知
    send_slack_notification(alerts)

    # 通知済み記録
    mark_notified(conn, alerts)
    print(f"{len(alerts)}件を通知済みとして記録")

    conn.close()
    print("完了")


if __name__ == "__main__":
    main()

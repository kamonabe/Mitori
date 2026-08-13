"""cve-priority-notify: EPSS + KEV + CVSS で優先度判定し高優先CVEをSlack通知する."""

import os
import sys

sys.path.insert(0, "/common")

from datetime import datetime, timezone

import pymysql
from db import get_conn
from slack import send_slack

SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL", "")

EPSS_THRESHOLD_HIGH = float(os.environ.get("EPSS_THRESHOLD_HIGH", "0.7"))
EPSS_THRESHOLD_MEDIUM = float(os.environ.get("EPSS_THRESHOLD_MEDIUM", "0.4"))
NOTIFY_MAX_ITEMS = int(os.environ.get("NOTIFY_MAX_ITEMS", "5"))
PRIORITY_BULK_THRESHOLD = int(os.environ.get("PRIORITY_BULK_THRESHOLD", "10"))


def ensure_tables(conn):
    """テーブルが存在しなければ作成する."""
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS cve_priority_notify_log (
                id INT AUTO_INCREMENT PRIMARY KEY,
                cve_id VARCHAR(50) NOT NULL,
                component VARCHAR(100) NOT NULL,
                category VARCHAR(50) NOT NULL,
                priority_level VARCHAR(20) NOT NULL,
                notified_at DATETIME NOT NULL,
                UNIQUE KEY uq_cve_component (cve_id, component, category)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)
    conn.commit()


def get_unnotified_candidates(conn):
    """未通知の高優先候補を取得する."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT ce.cve_id, ce.osv_id, ce.component, ce.category,
                   ce.severity, ce.summary, ce.fixed_version,
                   es.epss_score, es.percentile,
                   k.cve_id AS kev_cve_id, k.date_added AS kev_date_added,
                   k.due_date AS kev_due_date,
                   k.known_ransomware_use
            FROM cve_entries ce
            LEFT JOIN epss_scores es ON ce.cve_id = es.cve_id
            LEFT JOIN kev_catalog k ON ce.cve_id = k.cve_id
            LEFT JOIN cve_priority_notify_log pn
              ON ce.cve_id = pn.cve_id
              AND ce.component = pn.component
              AND ce.category = pn.category
            WHERE ce.status = 'open'
              AND ce.cve_id != ''
              AND pn.id IS NULL
        """)
        return cur.fetchall()


def determine_priority(epss_score, severity, is_in_kev):
    """優先度レベルを判定する.

    Returns:
        str or None: 'critical', 'high', 'medium', or None (通知対象外)
    """
    if is_in_kev and epss_score is not None and float(epss_score) >= EPSS_THRESHOLD_HIGH:
        return "critical"
    if is_in_kev:
        return "high"
    if epss_score is not None and float(epss_score) >= EPSS_THRESHOLD_HIGH:
        return "high"
    if epss_score is not None and float(epss_score) >= EPSS_THRESHOLD_MEDIUM and severity in ("HIGH", "CRITICAL"):
        return "medium"
    return None


def build_reason(priority, epss_score, percentile, is_in_kev):
    """判定理由の文字列を組み立てる."""
    parts = []
    if is_in_kev and epss_score is not None and float(epss_score) >= EPSS_THRESHOLD_HIGH:
        pct = int(float(percentile) * 100) if percentile else 0
        parts.append(f"KEV掲載中 + EPSS上位{100 - pct}%")
    elif is_in_kev:
        parts.append("KEV掲載中（実際の悪用確認済み）")
    elif epss_score is not None and float(epss_score) >= EPSS_THRESHOLD_HIGH:
        pct = int(float(percentile) * 100) if percentile else 0
        score_pct = int(float(epss_score) * 100)
        parts.append(f"EPSS上位{100 - pct}% — 30日以内に悪用される確率{score_pct}%")
    elif epss_score is not None and float(epss_score) >= EPSS_THRESHOLD_MEDIUM:
        score_pct = int(float(epss_score) * 100)
        parts.append(f"EPSS中位 + 重大度HIGH以上 — 悪用確率{score_pct}%")
    return " / ".join(parts) if parts else ""


def mark_notified(conn, entries):
    """通知済みとして記録する."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    with conn.cursor() as cur:
        for entry in entries:
            cur.execute(
                """INSERT IGNORE INTO cve_priority_notify_log
                (cve_id, component, category, priority_level, notified_at)
                VALUES (%s, %s, %s, %s, %s)""",
                (
                    entry["cve_id"],
                    entry["component"],
                    entry["category"],
                    entry["priority"],
                    now,
                ),
            )
    conn.commit()


def is_first_run(conn):
    """初回実行かどうかを判定する."""
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS cnt FROM cve_priority_notify_log")
        row = cur.fetchone()
        return row["cnt"] == 0


def send_slack_notification(entries):
    """Slack に優先度レポートを通知する."""
    if not SLACK_WEBHOOK_URL:
        print("SLACK_WEBHOOK_URL 未設定: 通知スキップ")
        return

    # 優先度別に分類
    critical = [e for e in entries if e["priority"] == "critical"]
    high = [e for e in entries if e["priority"] == "high"]
    medium = [e for e in entries if e["priority"] == "medium"]

    lines = ["🎯 CVE優先度レポート", ""]

    # CRITICAL
    if critical:
        lines.append(f"━━━━━ CRITICAL (即対応推奨): {len(critical)}件 ━━━━━")
        lines.append("")
        for entry in critical[:NOTIFY_MAX_ITEMS]:
            lines.extend(_format_entry(entry))
        if len(critical) > NOTIFY_MAX_ITEMS:
            lines.append(f"... 他 {len(critical) - NOTIFY_MAX_ITEMS} 件")
        lines.append("")

    # HIGH
    if high:
        lines.append(f"━━━━━ HIGH (早期対応推奨): {len(high)}件 ━━━━━")
        lines.append("")
        for entry in high[:NOTIFY_MAX_ITEMS]:
            lines.extend(_format_entry(entry))
        if len(high) > NOTIFY_MAX_ITEMS:
            lines.append(f"... 他 {len(high) - NOTIFY_MAX_ITEMS} 件")
        lines.append("")

    # MEDIUM
    if medium:
        lines.append(f"━━━━━ MEDIUM (計画的対応): {len(medium)}件 ━━━━━")
        lines.append("")
        for entry in medium[:NOTIFY_MAX_ITEMS]:
            lines.extend(_format_entry(entry))
        if len(medium) > NOTIFY_MAX_ITEMS:
            lines.append(f"... 他 {len(medium) - NOTIFY_MAX_ITEMS} 件")
        lines.append("")

    # サマリ
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    total = len(critical) + len(high) + len(medium)
    lines.append(f"合計: {total}件")
    lines.append(f"  CRITICAL: {len(critical)}件 / HIGH: {len(high)}件 / MEDIUM: {len(medium)}件")

    text = "\n".join(lines)
    send_slack(text)
    print("Slack通知送信完了")


def send_bulk_notification(entries):
    """初回大量検知時のサマリ通知."""
    if not SLACK_WEBHOOK_URL:
        print("SLACK_WEBHOOK_URL 未設定: 通知スキップ")
        return

    critical = len([e for e in entries if e["priority"] == "critical"])
    high = len([e for e in entries if e["priority"] == "high"])
    medium = len([e for e in entries if e["priority"] == "medium"])

    lines = [
        "🎯 CVE優先度レポート（初回スキャン）",
        "",
        f"高優先CVEが {len(entries)}件 検出されました。",
        f"  CRITICAL: {critical}件 / HIGH: {high}件 / MEDIUM: {medium}件",
        "",
        "※ 次回以降は新たに高優先になったCVEのみ通知します",
    ]

    text = "\n".join(lines)
    send_slack(text)
    print("Slack通知送信完了（初回サマリ）")


def _format_entry(entry):
    """1件分の通知行を組み立てる."""
    lines = []
    cve_id = entry["cve_id"]
    epss = entry.get("epss_score")
    severity = entry.get("severity") or "UNKNOWN"
    is_kev = entry.get("is_in_kev", False)

    # ヘッダー行
    epss_str = f"EPSS: {float(epss):.2f}" if epss is not None else "EPSS: N/A"
    kev_str = "KEV: ✓" if is_kev else "KEV: -"
    lines.append(f"■ {cve_id} ({epss_str} | CVSS: {severity} | {kev_str})")

    # 対象
    component = entry["component"]
    category = entry.get("category", "")
    target_str = f"{component} ({category})" if category else component
    lines.append(f"  対象: {target_str}")

    # 概要
    summary = (entry.get("summary") or "")[:100]
    lines.append(f"  概要: {summary}")

    # 修正版
    fixed = entry.get("fixed_version")
    if fixed:
        lines.append(f"  修正版: {fixed}")
    else:
        lines.append("  修正版: なし")

    # KEV情報
    if is_kev:
        due_date = entry.get("kev_due_date") or "未設定"
        lines.append(f"  KEV対処期限: {due_date}")

    # 判定理由
    reason = entry.get("reason", "")
    if reason:
        lines.append(f"  理由: {reason}")

    lines.append("")
    return lines


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

    print("=== cve-priority-notify: CVE優先度判定 ===\n")

    # 未通知候補を取得
    candidates = get_unnotified_candidates(conn)
    if not candidates:
        print("未通知候補なし: 終了")
        conn.close()
        return

    print(f"未通知候補: {len(candidates)}件")

    # 優先度判定
    prioritized = []
    for row in candidates:
        epss_score = row.get("epss_score")
        severity = row.get("severity") or "UNKNOWN"
        is_in_kev = row.get("kev_cve_id") is not None

        priority = determine_priority(epss_score, severity, is_in_kev)
        if priority is None:
            continue

        reason = build_reason(priority, epss_score, row.get("percentile"), is_in_kev)

        prioritized.append(
            {
                "cve_id": row["cve_id"],
                "osv_id": row.get("osv_id", ""),
                "component": row["component"],
                "category": row["category"],
                "severity": severity,
                "summary": row.get("summary"),
                "fixed_version": row.get("fixed_version"),
                "epss_score": epss_score,
                "percentile": row.get("percentile"),
                "is_in_kev": is_in_kev,
                "kev_due_date": row.get("kev_due_date"),
                "priority": priority,
                "reason": reason,
            }
        )

    if not prioritized:
        print("高優先CVEなし: 終了")
        conn.close()
        return

    print(f"高優先CVE: {len(prioritized)}件")
    for entry in prioritized:
        print(f"  {entry['priority'].upper()}: {entry['cve_id']} ({entry['component']})")

    # 初回判定
    first_run = is_first_run(conn)

    if first_run and len(prioritized) > PRIORITY_BULK_THRESHOLD:
        # 初回大量検知: サマリ通知
        print(f"初回実行 + 大量検知({len(prioritized)}件): サマリ通知")
        send_bulk_notification(prioritized)
    else:
        # 通常通知
        send_slack_notification(prioritized)

    # 通知済み記録
    mark_notified(conn, prioritized)
    print(f"{len(prioritized)}件を通知済みとして記録")

    conn.close()
    print("完了")


if __name__ == "__main__":
    main()

"""kev-collector: CISA KEV カタログを取得して DB に格納する."""

import os
from datetime import datetime, timezone

import pymysql
import requests

DB_HOST = os.environ.get("DB_HOST", "")
DB_USER = os.environ.get("DB_USER", "")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "")
DB_NAME = os.environ.get("DB_NAME", "")

KEV_URL = "https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json"
KEV_TIMEOUT = 30


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
    """テーブルが存在しなければ作成する."""
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS kev_catalog (
                id INT AUTO_INCREMENT PRIMARY KEY,
                cve_id VARCHAR(50) NOT NULL UNIQUE,
                vendor VARCHAR(200) NOT NULL,
                product VARCHAR(200) NOT NULL,
                vulnerability_name VARCHAR(500) NOT NULL,
                short_description TEXT,
                required_action TEXT,
                date_added DATE NOT NULL,
                due_date DATE,
                known_ransomware_use VARCHAR(20) DEFAULT 'Unknown',
                cwes VARCHAR(500) DEFAULT NULL,
                notes TEXT,
                created_at DATETIME NOT NULL,
                INDEX idx_date_added (date_added),
                INDEX idx_cve_id (cve_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)
    conn.commit()


def fetch_kev_catalog():
    """CISA KEV カタログを取得する."""
    resp = requests.get(KEV_URL, timeout=KEV_TIMEOUT)
    resp.raise_for_status()
    return resp.json()


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

    print("=== kev-collector: CISA KEV カタログ取得 ===\n")

    try:
        data = fetch_kev_catalog()
    except requests.RequestException as e:
        print(f"エラー: KEV カタログ取得失敗: {e}")
        conn.close()
        return

    vulnerabilities = data.get("vulnerabilities", [])
    catalog_version = data.get("catalogVersion", "unknown")
    total = len(vulnerabilities)
    print(f"カタログバージョン: {catalog_version}")
    print(f"総エントリ数: {total}")

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    new_count = 0

    for vuln in vulnerabilities:
        cve_id = vuln.get("cveID", "")
        if not cve_id:
            continue

        vendor = vuln.get("vendorProject", "")[:200]
        product = vuln.get("product", "").strip()[:200]
        vulnerability_name = vuln.get("vulnerabilityName", "")[:500]
        short_description = vuln.get("shortDescription", "")
        required_action = vuln.get("requiredAction", "")
        date_added = vuln.get("dateAdded", "")
        due_date = vuln.get("dueDate", "") or None
        known_ransomware_use = vuln.get("knownRansomwareCampaignUse", "Unknown")[:20]
        cwes = ",".join(vuln.get("cwes", []))[:500] if vuln.get("cwes") else None
        notes = vuln.get("notes", "")

        try:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT IGNORE INTO kev_catalog
                    (cve_id, vendor, product, vulnerability_name, short_description,
                     required_action, date_added, due_date, known_ransomware_use,
                     cwes, notes, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                    (
                        cve_id,
                        vendor,
                        product,
                        vulnerability_name,
                        short_description,
                        required_action,
                        date_added,
                        due_date,
                        known_ransomware_use,
                        cwes,
                        notes,
                        now,
                    ),
                )
                if cur.rowcount > 0:
                    new_count += 1
            conn.commit()
        except pymysql.Error as e:
            print(f"  エラー: {cve_id} の挿入失敗: {e}")
            conn.rollback()

    print(f"\n結果: {total}件取得、{new_count}件が新規追加")
    conn.close()
    print("完了")


if __name__ == "__main__":
    main()

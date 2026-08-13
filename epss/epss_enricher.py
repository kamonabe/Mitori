"""epss-enricher: cve_entries の open CVE に EPSS スコアを日次で付加・更新する."""

import os
import sys

sys.path.insert(0, "/common")

from datetime import datetime, timezone

import pymysql
import requests
from db import get_conn

EPSS_API_URL = "https://api.first.org/data/v1/epss"
EPSS_API_TIMEOUT = int(os.environ.get("EPSS_API_TIMEOUT", "30"))
EPSS_BATCH_SIZE = int(os.environ.get("EPSS_BATCH_SIZE", "100"))


def ensure_tables(conn):
    """テーブルが存在しなければ作成する."""
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS epss_scores (
                id INT AUTO_INCREMENT PRIMARY KEY,
                cve_id VARCHAR(50) NOT NULL UNIQUE,
                epss_score DECIMAL(10,9) NOT NULL,
                percentile DECIMAL(10,9) NOT NULL,
                score_date DATE NOT NULL,
                updated_at DATETIME NOT NULL,
                INDEX idx_epss_score (epss_score DESC),
                INDEX idx_cve_id (cve_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)
    conn.commit()


def get_open_cve_ids(conn):
    """cve_entries から status='open' かつ cve_id が空でないものを取得する."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT DISTINCT cve_id
            FROM cve_entries
            WHERE status = 'open' AND cve_id != ''
        """)
        return [row["cve_id"] for row in cur.fetchall()]


def fetch_epss_batch(cve_ids):
    """FIRST EPSS API にバッチクエリしてスコアを取得する."""
    cve_param = ",".join(cve_ids)
    resp = requests.get(
        EPSS_API_URL,
        params={"cve": cve_param},
        timeout=EPSS_API_TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()
    return data.get("data", [])


def upsert_epss_score(conn, cve_id, epss_score, percentile, score_date):
    """epss_scores テーブルに UPSERT する."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO epss_scores (cve_id, epss_score, percentile, score_date, updated_at)
            VALUES (%s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                epss_score = VALUES(epss_score),
                percentile = VALUES(percentile),
                score_date = VALUES(score_date),
                updated_at = VALUES(updated_at)""",
            (cve_id, epss_score, percentile, score_date, now),
        )
    conn.commit()


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

    print("=== epss-enricher: EPSS スコア更新 ===\n")

    # open状態のCVE ID一覧を取得
    cve_ids = get_open_cve_ids(conn)
    if not cve_ids:
        print("対象CVEなし: 終了")
        conn.close()
        return

    print(f"対象CVE数: {len(cve_ids)}件")

    # バッチに分割してAPI呼び出し
    updated_count = 0
    skipped_count = 0

    for i in range(0, len(cve_ids), EPSS_BATCH_SIZE):
        batch = cve_ids[i : i + EPSS_BATCH_SIZE]
        batch_num = i // EPSS_BATCH_SIZE + 1
        print(f"\nバッチ {batch_num}: {len(batch)}件を問い合わせ中...")

        try:
            results = fetch_epss_batch(batch)
        except requests.RequestException as e:
            print(f"  エラー: EPSS API 呼び出し失敗: {e}")
            continue

        print(f"  API応答: {len(results)}件のスコア取得")

        for item in results:
            cve_id = item.get("cve", "")
            epss_score = item.get("epss")
            percentile = item.get("percentile")
            score_date = item.get("date", "")

            if not cve_id or epss_score is None or percentile is None:
                skipped_count += 1
                continue

            try:
                upsert_epss_score(conn, cve_id, epss_score, percentile, score_date)
                updated_count += 1
            except pymysql.Error as e:
                print(f"  エラー: {cve_id} の保存失敗: {e}")
                conn.rollback()

        # バッチ間の未登録CVE（APIにデータがないもの）
        returned_cves = {item.get("cve") for item in results}
        not_found = [cve for cve in batch if cve not in returned_cves]
        if not_found:
            skipped_count += len(not_found)

    print(f"\n結果: {updated_count}件更新、{skipped_count}件スキップ（APIにデータなし）")
    conn.close()
    print("完了")


if __name__ == "__main__":
    main()

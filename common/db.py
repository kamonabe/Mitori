"""共通DBコネクション."""

import os

import pymysql


def get_conn():
    """MariaDB接続を取得する.

    環境変数 DB_HOST / DB_USER / DB_PASSWORD / DB_NAME から接続情報を読み取る。
    """
    return pymysql.connect(
        host=os.environ.get("DB_HOST", ""),
        user=os.environ.get("DB_USER", ""),
        password=os.environ.get("DB_PASSWORD", ""),
        database=os.environ.get("DB_NAME", ""),
        charset="utf8mb4",
        autocommit=False,
        cursorclass=pymysql.cursors.DictCursor,
        connect_timeout=10,
        read_timeout=10,
    )

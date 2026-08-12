"""共通Slack通知ユーティリティ."""

import os

import requests

SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL", "")


def send_slack(text: str) -> None:
    """Slackにテキストメッセージを送信する.

    - SLACK_WEBHOOK_URL 未設定の場合はスキップ(エラーにしない)
    - 送信失敗時もログ出力のみ(エラーにしない)
    """
    if not SLACK_WEBHOOK_URL:
        print("SLACK_WEBHOOK_URL未設定: 通知スキップ")
        return
    try:
        r = requests.post(SLACK_WEBHOOK_URL, json={"text": text}, timeout=10)
        if r.status_code != 200:
            print(f"Slack応答: {r.status_code} {r.text}")
    except requests.RequestException as e:
        print(f"Slack送信失敗: {e}")

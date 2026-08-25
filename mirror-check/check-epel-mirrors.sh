#!/bin/sh
# check-epel-mirrors.sh
# EPELミラーリストに設定済みミラーが含まれているか確認し、
# 欠落数に応じてアラートレベルを出力する
#
# 使い方:
#   MIRROR_1=... MIRROR_2=... ./check-epel-mirrors.sh
#   REPO=epel-10 ARCH=aarch64 ./check-epel-mirrors.sh
#
# 終了コード:
#   0: 全件一致 (正常)
#   1: 1件欠落  (注意)
#   2: 2件欠落  (警戒)
#   3: 3件以上欠落 (緊急)

# ---------- 設定 ----------
REPO="${REPO:-epel-10}"
ARCH="${ARCH:-aarch64}"
MIRRORLIST_URL="https://mirrors.fedoraproject.org/mirrorlist?repo=${REPO}&arch=${ARCH}"

# 監視対象ミラーは環境変数 MIRROR_1〜MIRROR_N から取得
# （CronJobマニフェスト側で定義）

SLACK_WEBHOOK_URL="${SLACK_WEBHOOK_URL:-}"
# ---------- 設定ここまで ----------

log() { echo "$(date '+%Y-%m-%d %H:%M:%S') $*"; }

# mirrorlistを取得（コメント行・空行を除外）
MIRROR_LIST=$(curl -sf --max-time 10 "${MIRRORLIST_URL}" | grep -v '^#' | grep -v '^$')
if [ -z "${MIRROR_LIST}" ]; then
  log "[ERROR] mirrorlistの取得に失敗しました: ${MIRRORLIST_URL}"
  exit 3
fi

# MIRROR_1, MIRROR_2, ... から監視対象を収集
TOTAL=0
MISSING=0
MISSING_URLS=""

log "=== EPEL Mirror Check ==="
log "Repo  : ${REPO}"
log "Arch  : ${ARCH}"
log "URL   : ${MIRRORLIST_URL}"
log "-------------------------------"

i=1
while true; do
  eval "mirror=\${MIRROR_${i}:-}"
  [ -z "${mirror}" ] && break
  TOTAL=$((TOTAL + 1))

  # 末尾スラッシュを除去して正規化比較
  normalized=$(echo "${mirror}" | sed 's|/$||')
  if echo "${MIRROR_LIST}" | sed 's|/$||' | grep -qF "${normalized}"; then
    log "  [OK]  ${mirror}"
  else
    log "  [NG]  ${mirror}"
    MISSING=$((MISSING + 1))
    if [ -n "${MISSING_URLS}" ]; then
      MISSING_URLS="${MISSING_URLS}
${mirror}"
    else
      MISSING_URLS="${mirror}"
    fi
  fi

  i=$((i + 1))
done

log "-------------------------------"

if [ "${TOTAL}" -eq 0 ]; then
  log "[ERROR] 監視対象ミラーが設定されていません (MIRROR_1 が未定義)"
  exit 3
fi

# アラートレベル判定
case ${MISSING} in
  0)
    LEVEL="NORMAL"
    MSG="全${TOTAL}件のミラーがリストに存在します。異常なし。"
    EXIT_CODE=0
    ;;
  1)
    LEVEL="WARN"
    MSG="${MISSING}件のミラーがリストから消えています。注意: 次回棚卸し時に確認してください。"
    EXIT_CODE=1
    ;;
  2)
    LEVEL="ALERT"
    MSG="${MISSING}件のミラーがリストから消えています。警戒: 早めにミラーを差し替えてください。"
    EXIT_CODE=2
    ;;
  *)
    LEVEL="CRITICAL"
    MSG="${MISSING}件全てのミラーがリストから消えています。緊急: インストール不能の可能性があります。"
    EXIT_CODE=3
    ;;
esac

log "[${LEVEL}] ${MSG}"

# Slack通知（WEBHOOKが設定されていて、かつ正常以外の場合）
if [ -n "${SLACK_WEBHOOK_URL}" ] && [ "${EXIT_CODE}" -gt 0 ]; then
  MISSING_FORMATTED=$(echo "${MISSING_URLS}" | sed 's/^/  • /')
  PAYLOAD="{\"text\": \"*EPEL Mirror Check: ${LEVEL}*\n${MSG}\n\n欠落ミラー:\n${MISSING_FORMATTED}\"}"
  if curl -sf -X POST -H 'Content-type: application/json' \
    --data "${PAYLOAD}" "${SLACK_WEBHOOK_URL}" > /dev/null 2>&1; then
    log "Slack通知を送信しました。"
  else
    log "Slack通知に失敗しました。"
  fi
fi

exit ${EXIT_CODE}

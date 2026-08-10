#!/usr/bin/env bash
# check-epel-mirrors.sh
# EPELミラーリストに設定済みミラーが含まれているか確認し、
# 欠落数に応じてアラートレベルを出力する
#
# 使い方:
#   ./check-epel-mirrors.sh
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

# 監視対象として設定済みのミラー（末尾スラッシュは除去して比較するので有無は問わない）
CONFIGURED_MIRRORS=(
  "http://ftp.yz.yamagata-u.ac.jp/pub/linux/fedora-projects/epel/10.3/Everything/aarch64/"
  "http://ftp.iij.ad.jp/pub/linux/Fedora/epel/10.3/Everything/aarch64/"
  "https://ftp.kaist.ac.kr/pub/epel/10.3/Everything/aarch64/"
)

# Slack通知が必要な場合はURLを設定（不要なら空のまま）
SLACK_WEBHOOK_URL=""
# ---------- 設定ここまで ----------

# 色定義（TTYのみ有効）
if [ -t 1 ]; then
  C_GREEN="\033[0;32m"
  C_YELLOW="\033[1;33m"
  C_RED="\033[0;31m"
  C_BOLD="\033[1m"
  C_RESET="\033[0m"
else
  C_GREEN="" C_YELLOW="" C_RED="" C_BOLD="" C_RESET=""
fi

log() { echo -e "$(date '+%Y-%m-%d %H:%M:%S') $*"; }

# mirrorlistを取得（コメント行・空行を除外）
MIRROR_LIST=$(curl -sf --max-time 10 "${MIRRORLIST_URL}" | grep -v '^#' | grep -v '^$')
if [ -z "${MIRROR_LIST}" ]; then
  log "${C_RED}[ERROR]${C_RESET} mirrorlistの取得に失敗しました: ${MIRRORLIST_URL}"
  exit 3
fi

TOTAL=${#CONFIGURED_MIRRORS[@]}
MISSING=0
MISSING_URLS=()

log "${C_BOLD}=== EPEL Mirror Check ===${C_RESET}"
log "Repo  : ${REPO}"
log "Arch  : ${ARCH}"
log "URL   : ${MIRRORLIST_URL}"
log "-------------------------------"

for mirror in "${CONFIGURED_MIRRORS[@]}"; do
  # 末尾スラッシュを正規化して比較
  normalized="${mirror%/}"
  if echo "${MIRROR_LIST}" | sed 's|/$||' | grep -qF "${normalized}"; then
    log "  ${C_GREEN}[OK]${C_RESET}  ${mirror}"
  else
    log "  ${C_RED}[NG]${C_RESET}  ${mirror}"
    MISSING_URLS+=("${mirror}")
    (( MISSING++ ))
  fi
done

log "-------------------------------"

# アラートレベル判定
case ${MISSING} in
  0)
    LEVEL="NORMAL"
    LEVEL_LABEL="${C_GREEN}[NORMAL]${C_RESET}"
    MSG="全${TOTAL}件のミラーがリストに存在します。異常なし。"
    EXIT_CODE=0
    ;;
  1)
    LEVEL="WARN"
    LEVEL_LABEL="${C_YELLOW}[WARN]${C_RESET}"
    MSG="${MISSING}件のミラーがリストから消えています。注意: 次回棚卸し時に確認してください。"
    EXIT_CODE=1
    ;;
  2)
    LEVEL="ALERT"
    LEVEL_LABEL="${C_YELLOW}[ALERT]${C_RESET}"
    MSG="${MISSING}件のミラーがリストから消えています。警戒: 早めにミラーを差し替えてください。"
    EXIT_CODE=2
    ;;
  *)
    LEVEL="CRITICAL"
    LEVEL_LABEL="${C_RED}[CRITICAL]${C_RESET}"
    MSG="${MISSING}件全てのミラーがリストから消えています。緊急: インストール不能の可能性があります。"
    EXIT_CODE=3
    ;;
esac

log "${LEVEL_LABEL} ${MSG}"

# Slack通知（WEBHOOKが設定されていて、かつ正常以外の場合）
if [ -n "${SLACK_WEBHOOK_URL}" ] && [ "${EXIT_CODE}" -gt 0 ]; then
  MISSING_LIST=$(printf '%s\n' "${MISSING_URLS[@]}" | sed 's/^/  • /')
  PAYLOAD=$(cat <<EOF
{
  "text": "*EPEL Mirror Check: ${LEVEL}*\n${MSG}\n\n欠落ミラー:\n${MISSING_LIST}"
}
EOF
)
  curl -sf -X POST -H 'Content-type: application/json' \
    --data "${PAYLOAD}" "${SLACK_WEBHOOK_URL}" > /dev/null \
    && log "Slack通知を送信しました。" \
    || log "Slack通知に失敗しました。"
fi

exit ${EXIT_CODE}

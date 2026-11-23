#!/usr/bin/env bash
# 仅生成并安装合成或已获授权的日线回执，不启动采集、不访问麦蕊。
# 安装目标只能是临时目录或已确认的 aia_receipts 具名卷。
{ set +x; } 2>/dev/null
set -euo pipefail

IMAGE="alpine:3.21@sha256:bc21487101ae47172509130ee1092cc273a831968d64b617776d1f69c81e42ab"
DOCKER_SPEC="${AIA_DOCKER:-docker}"
read -r -a DOCKER <<< "$DOCKER_SPEC"

usage() {
  cat <<'USAGE'
用法：
  install-mairui-daily-receipts.sh (--volume-name NAME | --target-dir DIR) \
    --user-id UUID --licence-id UUID --receipt-id UUID \
    --not-before RFC3339 --expires-at RFC3339

目标只能二选一：已确认的具名 aia_receipts 卷，或临时目录。
脚本使用固定 alpine 镜像、root 用户和 --network none，仅写入两个回执文件。
USAGE
}

volume=""
target=""
user_id=""
licence_id=""
receipt_id=""
not_before=""
expires_at=""

while (($#)); do
  case "$1" in
    --volume-name|--target-dir|--user-id|--licence-id|--receipt-id|--not-before|--expires-at)
      (($# >= 2)) || { echo "缺少 $1 的值" >&2; usage >&2; exit 2; }
      key="$1"; value="$2"
      case "$key" in
        --volume-name) volume="$value" ;;
        --target-dir) target="$value" ;;
        --user-id) user_id="$value" ;;
        --licence-id) licence_id="$value" ;;
        --receipt-id) receipt_id="$value" ;;
        --not-before) not_before="$value" ;;
        --expires-at) expires_at="$value" ;;
      esac
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "未知参数：$1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if { [[ -n "$volume" && -n "$target" ]] || [[ -z "$volume" && -z "$target" ]]; }; then
  echo "必须且只能指定 --volume-name 或 --target-dir" >&2
  exit 2
fi

uuid() {
  [[ "$1" =~ ^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$ ]]
}
rfc3339() {
  [[ "$1" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}([Zz]|[+-][0-9]{2}:[0-9]{2})$ ]] || return 1
  date -u -d "$1" +%s >/dev/null 2>&1
}

uuid "$user_id" || { echo "user_id 必须是 UUID" >&2; exit 2; }
uuid "$licence_id" || { echo "licence_id 必须是 UUID" >&2; exit 2; }
uuid "$receipt_id" || { echo "receipt_id 必须是 UUID" >&2; exit 2; }
rfc3339 "$not_before" || { echo "not_before 必须是有效 RFC3339 时间" >&2; exit 2; }
rfc3339 "$expires_at" || { echo "expires_at 必须是有效 RFC3339 时间" >&2; exit 2; }
start_epoch="$(date -u -d "$not_before" +%s)"
end_epoch="$(date -u -d "$expires_at" +%s)"
((start_epoch < end_epoch)) || { echo "expires_at 必须晚于 not_before" >&2; exit 2; }

if [[ -n "$volume" ]]; then
  [[ "$volume" =~ ^[a-zA-Z0-9][a-zA-Z0-9_.-]*$ ]] || {
    echo "具名卷名称不合法" >&2
    exit 2
  }
  mount="$volume:/run/aia/receipts"
  destination="具名卷"
else
  [[ "$target" != "/" && ! -L "$target" ]] || { echo "临时目录不能是根目录或符号链接" >&2; exit 2; }
  [[ -d "$target" ]] || mkdir -p "$target"
  target="$(cd "$target" && pwd -P)"
  mount="$target:/run/aia/receipts"
  destination="临时目录"
fi

"${DOCKER[@]}" image inspect "$IMAGE" >/dev/null 2>&1 || {
  echo "固定演练镜像不存在，脚本不拉取镜像：$IMAGE" >&2
  exit 3
}

"${DOCKER[@]}" run --rm --network none --user 0 \
  --env "RECEIPT_USER_ID=$user_id" \
  --env "RECEIPT_LICENCE_ID=$licence_id" \
  --env "RECEIPT_ID=$receipt_id" \
  --env "RECEIPT_NOT_BEFORE=$not_before" \
  --env "RECEIPT_EXPIRES_AT=$expires_at" \
  --volume "$mount" \
  "$IMAGE" sh -ceu '
    dir=/run/aia/receipts
    bars="$dir/mairui-daily-bars.json"
    daily="$dir/mairui-daily.json"
    install -d -o root -g root -m 0755 "$dir"
    if [ -e "$bars" ] || [ -L "$bars" ] || [ -e "$daily" ] || [ -L "$daily" ]; then
      echo "拒绝安装：目标回执已存在，脚本不覆盖" >&2
      exit 3
    fi

    tmp_bars="$(mktemp "$dir/.mairui-daily-bars.XXXXXX")"
    tmp_daily="$(mktemp "$dir/.mairui-daily.XXXXXX")"
    created_bars=0
    created_daily=0
    cleanup() {
      rm -f "$tmp_bars" "$tmp_daily"
      if [ "$created_daily" = 0 ] && [ "$created_bars" = 1 ]; then
        rm -f "$bars"
      fi
    }
    trap cleanup EXIT

    printf "%s\n" "{\"kind\":\"mairui_daily_bars\",\"user_id\":\"$RECEIPT_USER_ID\",\"licence_id\":\"$RECEIPT_LICENCE_ID\",\"receipt_id\":\"$RECEIPT_ID\",\"not_before\":\"$RECEIPT_NOT_BEFORE\",\"expires_at\":\"$RECEIPT_EXPIRES_AT\"}" > "$tmp_bars"
    printf "%s\n" "{\"kind\":\"mairui_daily_snapshot\",\"user_id\":\"$RECEIPT_USER_ID\",\"licence_id\":\"$RECEIPT_LICENCE_ID\",\"receipt_id\":\"$RECEIPT_ID\",\"not_before\":\"$RECEIPT_NOT_BEFORE\",\"expires_at\":\"$RECEIPT_EXPIRES_AT\"}" > "$tmp_daily"
    chown root:root "$tmp_bars" "$tmp_daily"
    chmod 0444 "$tmp_bars" "$tmp_daily"

    ln "$tmp_bars" "$bars" || { echo "拒绝安装：日线回执在并发检查期间已存在" >&2; exit 3; }
    created_bars=1
    ln "$tmp_daily" "$daily" || { echo "拒绝安装：主回执在并发检查期间已存在" >&2; exit 3; }
    created_daily=1
    rm -f "$tmp_bars" "$tmp_daily"
    trap - EXIT
  '

echo "${destination}回执安装完成：root:root、0444；未启动采集。"

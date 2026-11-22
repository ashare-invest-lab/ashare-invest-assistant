#!/usr/bin/env bash
# 只读检查盘中行情快照的新鲜度。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CONFIG_FILE="$ROOT/config/realtime.yaml"
FROM_DIR=""
NOW="$(date +%s)"

usage() {
  echo "用法：$0 [--from-dir 目录] [--now 秒]" >&2
  exit 4
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --from-dir)
      [ "$#" -ge 2 ] || usage
      FROM_DIR="$2"
      shift 2
      ;;
    --now)
      [ "$#" -ge 2 ] || usage
      NOW="$2"
      shift 2
      ;;
    -h|--help)
      usage
      ;;
    *)
      usage
      ;;
  esac
done

emit() {
  local status="$1" code="$2" age="$3" threshold="$4" explanation="$5" stamp line
  stamp="$(TZ=CST-8 date -d "@${NOW}" '+%Y-%m-%dT%H:%M:%S%z')"
  line="${stamp} 状态=${status} 龄=${age}s 阈值=${threshold}s 说明=${explanation}"
  printf '%s\n' "$line"
  if [ -n "${QUOTES_FRESHNESS_LOG:-}" ]; then
    printf '%s\n' "$line" >> "$QUOTES_FRESHNESS_LOG"
  fi
  exit "$code"
}

case "${QUOTES_FRESHNESS_ENABLED:-false}" in
  1|true|TRUE|yes|YES|on|ON) ;;
  *) emit "未启用" 0 0 0 "QUOTES_FRESHNESS_ENABLED 未开启" ;;
esac

case "$NOW" in
  ''|*[!0-9]*) emit "配置错误" 4 0 0 "--now 必须是非负整数秒" ;;
esac

read_yaml_intervals() {
  awk '
    /^[[:space:]]*intervals:[[:space:]]*(#.*)?$/ { inside=1; next }
    inside && /^[^[:space:]#]/ { inside=0 }
    inside && /^[[:space:]]+quote_interval_s:[[:space:]]*/ {
      line=$0; sub(/^[^:]*:[[:space:]]*/, "", line); sub(/[[:space:]]+#.*/, "", line); gsub(/[[:space:]]/, "", line); quote=line
    }
    inside && /^[[:space:]]+stale_threshold_s:[[:space:]]*/ {
      line=$0; sub(/^[^:]*:[[:space:]]*/, "", line); sub(/[[:space:]]+#.*/, "", line); gsub(/[[:space:]]/, "", line); stale=line
    }
    END { print quote "\t" stale }
  ' "$CONFIG_FILE"
}

threshold=""
if [ "${QUOTES_STALE_S+x}" = x ]; then
  threshold="$QUOTES_STALE_S"
else
  [ -r "$CONFIG_FILE" ] || emit "配置错误" 4 0 0 "无法读取 config/realtime.yaml"
  IFS=$'\t' read -r quote_interval stale_threshold < <(read_yaml_intervals)
  case "$quote_interval" in ''|*[!0-9]*) emit "配置错误" 4 0 0 "quote_interval_s 不是正整数" ;; esac
  if [ "$quote_interval" -le 0 ]; then
    emit "配置错误" 4 0 0 "quote_interval_s 不是正整数"
  fi
  if [ "$stale_threshold" = null ]; then
    threshold=$((quote_interval * 2))
  elif [ -n "$stale_threshold" ]; then
    threshold="$stale_threshold"
  else
    emit "配置错误" 4 0 0 "stale_threshold_s 缺失"
  fi
fi
case "$threshold" in ''|*[!0-9]*) emit "配置错误" 4 0 0 "新鲜度阈值必须是正整数" ;; esac
[ "$threshold" -gt 0 ] || emit "配置错误" 4 0 0 "新鲜度阈值必须是正整数"

local_date="$(TZ=CST-8 date -d "@${NOW}" '+%Y-%m-%d')"
weekday="$(TZ=CST-8 date -d "@${NOW}" '+%u')"
clock="$(TZ=CST-8 date -d "@${NOW}" '+%H%M')"
if [ "$clock" -lt 930 ] || { [ "$clock" -ge 1130 ] && [ "$clock" -lt 1300 ]; } || [ "$clock" -ge 1500 ]; then
  emit "非交易时段" 0 0 "$threshold" "当前不在 09:30-11:30 或 13:00-15:00"
fi

max_ts=""
calendar_open=""
calendar_note=""
if [ -n "$FROM_DIR" ]; then
  if [ -r "$FROM_DIR/max_ts" ]; then max_ts="$(cat "$FROM_DIR/max_ts")"; fi
  if [ -r "$FROM_DIR/is_open" ]; then calendar_open="$(cat "$FROM_DIR/is_open")"; fi
else
  read -r -a DOCKER <<< "${AIA_DOCKER:-docker}"
  if [ -n "${AIA_PG_CONTAINER:-}" ]; then
    pg_container="$AIA_PG_CONTAINER"
  else
    project="${COMPOSE_PROJECT:-$("$ROOT/deploy/scripts/compose.sh" --get COMPOSE_PROJECT_NAME 2>/dev/null || true)}"
    [ -n "$project" ] || emit "配置错误" 4 0 "$threshold" "无法确定 compose 项目名（可设 COMPOSE_PROJECT）"
    pg_container="$("${DOCKER[@]}" ps --filter "label=com.docker.compose.project=$project" --filter label=com.docker.compose.service=postgres --format '{{.ID}}' | head -n 1)"
  fi
  [ -n "$pg_container" ] || emit "配置错误" 4 0 "$threshold" "找不到运行中的 postgres 容器"
  # 内层查询恒返回一行非空文本：空表/缺当日时 xpath 取空，避免 NULL 与空结果集让 xpath 报错
  sql="BEGIN READ ONLY;
SELECT
  CASE WHEN to_regclass('market.quotes_snapshot') IS NULL THEN '' ELSE COALESCE((xpath('/row/max/text()', query_to_xml('SELECT COALESCE(extract(epoch FROM max(ts))::bigint::text, '''') AS max FROM market.quotes_snapshot', false, true, '')))[1]::text, '') END
  || '|' ||
  CASE WHEN to_regclass('market.trading_calendar') IS NULL THEN '' ELSE COALESCE((xpath('/row/open/text()', query_to_xml('SELECT COALESCE((SELECT is_open::text FROM market.trading_calendar WHERE date = DATE ''${local_date}''), '''') AS open', false, true, '')))[1]::text, '') END;
COMMIT;"
  result="$(printf '%s\n' "$sql" | "${DOCKER[@]}" exec -i -e PGOPTIONS='-c default_transaction_read_only=on' "$pg_container" sh -c 'psql -X -q -At -v ON_ERROR_STOP=1 -U "${POSTGRES_USER:-postgres}" -d "${POSTGRES_DB:-postgres}"' 2>/dev/null)" \
    || emit "配置错误" 4 0 "$threshold" "只读查询失败"
  # 用 | 分隔：制表符属空白 IFS，首字段为空时会被吞掉
  IFS='|' read -r max_ts calendar_open <<< "$result"
fi

case "$calendar_open" in
  true|t|TRUE|1) ;;
  false|f|FALSE|0)
    emit "休市" 0 0 "$threshold" "交易日历标记为休市"
    ;;
  *)
    calendar_note="交易日历缺当日，按工作日推断（未验证）"
    if [ "$weekday" -gt 5 ]; then
      emit "休市" 0 0 "$threshold" "$calendar_note；周末"
    fi
    ;;
esac

case "$max_ts" in
  '' ) emit "无数据" 2 0 "$threshold" "quotes_snapshot 没有快照${calendar_note:+；$calendar_note}" ;;
  *[!0-9]* ) emit "配置错误" 4 0 "$threshold" "max_ts 不是整数秒" ;;
esac

age=$((NOW - max_ts))
[ "$age" -ge 0 ] || age=0
if [ "$age" -gt "$threshold" ]; then
  emit "过期" 2 "$age" "$threshold" "快照年龄超过阈值${calendar_note:+；$calendar_note}"
fi
emit "正常" 0 "$age" "$threshold" "快照年龄在阈值内${calendar_note:+；$calendar_note}"

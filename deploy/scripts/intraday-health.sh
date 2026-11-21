#!/bin/sh
# 盘中行情只读健康检查。默认 Redis 键名未验证，待 I4 定稿，可由环境变量覆盖。
# 时区用 POSIX 串 CST-8（=Asia/Shanghai，无夏令时）：redis alpine 镜像不带 tzdata，写地名会静默回落 UTC。
set -eu

heartbeat_key=${INTRADAY_HEARTBEAT_KEY:-intraday:heartbeat} # 未验证，待 I4 定稿
queue_key=${INTRADAY_QUEUE_KEY:-intraday:queue} # 未验证，待 I4 定稿
stale_after=${INTRADAY_STALE_AFTER_S:-120}
queue_zero_alert=${INTRADAY_QUEUE_ZERO_ALERT_S:-900}
health_log=${INTRADAY_HEALTH_LOG:-${AIA_RUNTIME:-/var/log/aia}/intraday-health.log}
health_dir=$(dirname "$health_log")
health_state=${INTRADAY_HEALTH_STATE:-$health_dir/intraday-health.state}
redis_url=${REDIS_URL:-redis://redis:6379/0}
from_dir=''
now_override=''

usage() {
    printf '%s\n' '用法：intraday-health.sh [--from-dir DIR] [--now EPOCH]' >&2
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --from-dir)
            [ "$#" -ge 2 ] || { usage; exit 2; }
            from_dir=$2
            shift 2
            ;;
        --now)
            [ "$#" -ge 2 ] || { usage; exit 2; }
            now_override=$2
            shift 2
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            usage
            exit 2
            ;;
    esac
done

is_uint() {
    case "$1" in
        ''|*[!0-9]*) return 1 ;;
        *) return 0 ;;
    esac
}

is_enabled() {
    case "${INTRADAY_ENABLED:-false}" in
        true|TRUE|True|1|yes|YES|Yes) return 0 ;;
        *) return 1 ;;
    esac
}

if [ -n "$now_override" ]; then
    is_uint "$now_override" || { printf '%s\n' '--now 必须是 epoch 秒' >&2; exit 2; }
    now=$now_override
else
    now=$(date +%s)
fi

format_time() {
    if [ -n "$now_override" ]; then
        TZ=CST-8 date -d "@$now" '+%Y-%m-%dT%H:%M:%S%z' 2>/dev/null \
            || TZ=CST-8 date -r "$now" '+%Y-%m-%dT%H:%M:%S%z'
    else
        TZ=CST-8 date '+%Y-%m-%dT%H:%M:%S%z'
    fi
}

emit() {
    line=$1
    mkdir -p "$health_dir"
    printf '%s\n' "$line"
    printf '%s\n' "$line" >> "$health_log"
}

if ! is_enabled; then
    emit "$(format_time) 状态=未启用 心跳龄=- 队列=- 说明=盘中采集未启用"
    exit 0
fi

# 交易日历不在部署侧判定，周末和时段外直接清除队列计时。
weekday=$(TZ=CST-8 date -d "@$now" '+%u' 2>/dev/null \
    || TZ=CST-8 date -r "$now" '+%u')
hour_minute=$(TZ=CST-8 date -d "@$now" '+%H%M' 2>/dev/null \
    || TZ=CST-8 date -r "$now" '+%H%M')
in_session=false
if [ "$weekday" -ge 1 ] && [ "$weekday" -le 5 ]; then
    if [ "$hour_minute" -ge 930 ] && [ "$hour_minute" -le 1130 ]; then
        in_session=true
    elif [ "$hour_minute" -ge 1300 ] && [ "$hour_minute" -le 1500 ]; then
        in_session=true
    fi
fi
if [ "$in_session" != true ]; then
    rm -f "$health_state"
    emit "$(format_time) 状态=非交易时段 心跳龄=- 队列=- 说明=节假日未判定"
    exit 0
fi

if ! is_uint "$stale_after" || ! is_uint "$queue_zero_alert"; then
    printf '%s\n' 'INTRADAY_STALE_AFTER_S 与 INTRADAY_QUEUE_ZERO_ALERT_S 必须是非负整数' >&2
    exit 2
fi

heartbeat=''
queue=''
if [ -n "$from_dir" ]; then
    if [ -f "$from_dir/heartbeat" ]; then
        heartbeat=$(cat "$from_dir/heartbeat") || heartbeat=''
    fi
    if [ -f "$from_dir/queue_len" ]; then
        queue=$(cat "$from_dir/queue_len") || queue=''
    fi
    if [ -z "$heartbeat" ] || ! is_uint "$heartbeat" || [ -z "$queue" ] || ! is_uint "$queue"; then
        emit "$(format_time) 状态=心跳缺失 心跳龄=- 队列=- 说明=心跳或队列数据缺失"
        exit 2
    fi
else
    if ! heartbeat=$(redis-cli -u "$redis_url" --no-auth-warning GET "$heartbeat_key" 2>/dev/null); then
        emit "$(format_time) 状态=心跳缺失 心跳龄=- 队列=- 说明=redis 不可达"
        exit 2
    fi
    if ! queue=$(redis-cli -u "$redis_url" --no-auth-warning LLEN "$queue_key" 2>/dev/null); then
        emit "$(format_time) 状态=心跳缺失 心跳龄=- 队列=- 说明=redis 不可达"
        exit 2
    fi
    heartbeat=$(printf '%s' "$heartbeat" | tr -d '\r\n')
    queue=$(printf '%s' "$queue" | tr -d '\r\n')
    if [ -z "$heartbeat" ] || ! is_uint "$heartbeat" || [ -z "$queue" ] || ! is_uint "$queue"; then
        emit "$(format_time) 状态=心跳缺失 心跳龄=- 队列=- 说明=redis 数据无效"
        exit 2
    fi
fi

heartbeat_age=$((now - heartbeat))
[ "$heartbeat_age" -lt 0 ] && heartbeat_age=0
if [ "$heartbeat_age" -gt "$stale_after" ]; then
    emit "$(format_time) 状态=心跳过期 心跳龄=${heartbeat_age} 队列=${queue} 说明=超过${stale_after}秒未更新"
    exit 2
fi

if [ "$queue" -eq 0 ]; then
    first_zero=''
    if [ -f "$health_state" ]; then
        first_zero=$(cat "$health_state" 2>/dev/null || true)
    fi
    if [ -z "$first_zero" ] || ! is_uint "$first_zero" || [ "$first_zero" -gt "$now" ]; then
        mkdir -p "$(dirname "$health_state")"
        printf '%s\n' "$now" > "$health_state"
        first_zero=$now
    fi
    zero_age=$((now - first_zero))
    if [ "$zero_age" -ge "$queue_zero_alert" ]; then
        emit "$(format_time) 状态=队列长期为0 心跳龄=${heartbeat_age} 队列=0 说明=队列为0已持续${zero_age}秒"
        exit 3
    fi
else
    rm -f "$health_state"
fi

emit "$(format_time) 状态=正常 心跳龄=${heartbeat_age} 队列=${queue} 说明=盘中心跳与队列正常"
exit 0

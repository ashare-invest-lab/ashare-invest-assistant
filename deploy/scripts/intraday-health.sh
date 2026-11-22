#!/bin/sh
# 盘中行情只读健康检查。队列键默认不接入，待 I4 定稿，可由环境变量覆盖。
# 行情时间戳由 ingest 写入 Redis，写入方待后端实现，未验证。
# INTRADAY_QUOTES_FUTURE_TOLERANCE_S 默认 5 秒为工程参数，未验证。
# 时区用 POSIX 串 CST-8（=Asia/Shanghai，无夏令时）：redis alpine 镜像不带 tzdata，写地名会静默回落 UTC。
set -eu
heartbeat_key=${INTRADAY_HEARTBEAT_KEY:-${INGEST_HEARTBEAT_KEY:-ingest:heartbeat}}
queue_key=${INTRADAY_QUEUE_KEY:-}
quotes_ts_key=${INTRADAY_QUOTES_TS_KEY:-}
trading_day_key=${INTRADAY_TRADING_DAY_KEY:-}
quotes_source=${REALTIME_QUOTES_SOURCE:-off}
realtime_config=${INTRADAY_REALTIME_CONFIG:-/app/config/realtime.yaml}
stale_after=${INTRADAY_STALE_AFTER_S:-120}
queue_zero_alert=${INTRADAY_QUEUE_ZERO_ALERT_S:-900}
quotes_future_tolerance=${INTRADAY_QUOTES_FUTURE_TOLERANCE_S:-5}
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
# 镜像只有 busybox：用 POSIX awk 完整校验 JSON，语义同 api/v1/health.py parse_heartbeat_ts（另拒负数）
extract_heartbeat_ts() {
    printf '%s' "$1" | awk '
    function ws(    c) { while (pos <= size) { c=substr(text,pos,1); if (c==" "||c=="\t"||c=="\n"||c=="\r") pos++; else return } }
    function digit(c) { return c ~ /^[0-9]$/ }
    function hex(c) { return c ~ /^[0-9A-Fa-f]$/ }
    function ctl(c,    k) { for (k=1;k<32;k++) if (c==sprintf("%c",k)) return 1; return 0 }
    function string(    c,e,j,v,out) {
        if (substr(text,pos,1)!="\"") return 0
        pos++; out=""
        while (pos<=size) {
            c=substr(text,pos,1)
            if (c=="\"") { pos++; string_value=out; return 1 }
            if (c!="\\") { if (ctl(c)) return 0; out=out c; pos++; continue }
            pos++; if (pos>size) return 0; e=substr(text,pos,1)
            if (e=="u") {
                if (pos+4>size) return 0; v=0
                for (j=1;j<=4;j++) { c=substr(text,pos+j,1); if (!hex(c)) return 0; v=v*16+index("0123456789abcdef",tolower(c))-1 }
                pos+=5; out=out (v>=32&&v<128?sprintf("%c",v):"?")
            } else if (e=="\""||e=="\\"||e=="/") { out=out e; pos++
            } else if (e=="b"||e=="f"||e=="n"||e=="r"||e=="t") {
                out=out sprintf("%c",e=="b"?8:e=="f"?12:e=="n"?10:e=="r"?13:9); pos++
            } else return 0
        }
        return 0
    }
    function number(    start,c,frac,expo) {
        start=pos; frac=0; expo=0; if (substr(text,pos,1)=="-") pos++
        if (substr(text,pos,1)=="0") { pos++; if (digit(substr(text,pos,1))) return 0
        } else if (substr(text,pos,1) ~ /^[1-9]$/) { while (digit(substr(text,pos,1))) pos++
        } else return 0
        if (substr(text,pos,1)==".") { frac=1; pos++; if (!digit(substr(text,pos,1))) return 0; while (digit(substr(text,pos,1))) pos++ }
        c=substr(text,pos,1)
        if (c=="e"||c=="E") { expo=1; pos++; c=substr(text,pos,1); if (c=="+"||c=="-") pos++; if (!digit(substr(text,pos,1))) return 0; while (digit(substr(text,pos,1))) pos++ }
        number_value=substr(text,start,pos-start); number_integer=!frac&&!expo&&(substr(number_value,1,1)!="-"||number_value=="-0"); return 1
    }
    function value(capture,    c) {
        c=substr(text,pos,1)
        if (c=="{") { if (!object(0)) return 0; if (capture) capture_integer=0; return 1 }
        if (c=="[") { if (!array()) return 0; if (capture) capture_integer=0; return 1 }
        if (c=="\"") { if (!string()) return 0; if (capture) capture_integer=0; return 1 }
        if (c=="t"&&substr(text,pos,4)=="true") { pos+=4; if (capture) capture_integer=0; return 1 }
        if (c=="f"&&substr(text,pos,5)=="false") { pos+=5; if (capture) capture_integer=0; return 1 }
        if (c=="n"&&substr(text,pos,4)=="null") { pos+=4; if (capture) capture_integer=0; return 1 }
        if (c=="-"||digit(c)) { if (!number()) return 0; if (capture) { capture_integer=number_integer; capture_value=number_value }; return 1 }
        return 0
    }
    function array() {
        if (substr(text,pos,1)!="[") return 0; pos++; ws(); if (substr(text,pos,1)=="]") { pos++; return 1 }
        while (1) { if (!value(0)) return 0; ws(); if (substr(text,pos,1)=="]") { pos++; return 1 }; if (substr(text,pos,1)!=",") return 0; pos++; ws() }
    }
    function object(top,    key) {
        if (substr(text,pos,1)!="{") return 0; pos++; ws(); if (substr(text,pos,1)=="}") { pos++; return 1 }
        while (1) {
            if (!string()) return 0; key=string_value; ws(); if (substr(text,pos,1)!=":") return 0; pos++; ws()
            if (top&&key=="ts") { capture_integer=0; capture_value=""; if (!value(1)) return 0; ts_found=1; ts_valid=capture_integer; ts_value=capture_value
            } else if (!value(0)) return 0
            ws(); if (substr(text,pos,1)=="}") { pos++; return 1 }; if (substr(text,pos,1)!=",") return 0; pos++; ws()
        }
    }
    { text=text (NR>1?"\n":"") $0 }
    END { pos=1; size=length(text); ws(); if (object(1)) { ws(); if (pos==size+1&&ts_found&&ts_valid) { print ts_value; exit 0 } }; exit 1 }'
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
trading_day=''
if [ -n "$from_dir" ]; then
    if [ -f "$from_dir/trading_day" ]; then
        trading_day=$(cat "$from_dir/trading_day") || trading_day=''
        trading_day=$(printf '%s' "$trading_day" | tr -d '\r\n')
    fi
elif [ -n "$trading_day_key" ]; then
    if ! trading_day=$(redis-cli -u "$redis_url" --no-auth-warning GET "$trading_day_key" 2>/dev/null); then
        emit "$(format_time) 状态=心跳缺失 心跳龄=- 队列=- 说明=redis 不可达"
        exit 2
    fi
    trading_day=$(printf '%s' "$trading_day" | tr -d '\r\n')
fi
if [ -n "$trading_day" ] && [ "$trading_day" != 0 ] && [ "$trading_day" != 1 ]; then
    emit "$(format_time) 状态=配置错误 心跳龄=- 队列=- 说明=交易日键必须是0或1"
    exit 2
fi
if [ "$trading_day" = 0 ]; then
    rm -f "$health_state"
    emit "$(format_time) 状态=非交易时段 心跳龄=- 队列=- 说明=非交易日"
    exit 0
fi
if [ "$trading_day" = 1 ] || { [ -z "$trading_day" ] && [ "$weekday" -ge 1 ] && [ "$weekday" -le 5 ]; }; then
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
if ! is_uint "$stale_after" || ! is_uint "$queue_zero_alert" || ! is_uint "$quotes_future_tolerance"; then
    emit "$(format_time) 状态=配置错误 心跳龄=- 队列=- 说明=INTRADAY_STALE_AFTER_S、INTRADAY_QUEUE_ZERO_ALERT_S 与 INTRADAY_QUOTES_FUTURE_TOLERANCE_S 必须是非负整数"
    exit 2
fi
heartbeat=''
queue=''
quotes_ts=''
quotes_connected=false
queue_check=false
queue_display=未接入
if [ -n "$from_dir" ]; then
    if [ -f "$from_dir/heartbeat" ]; then
        heartbeat=$(cat "$from_dir/heartbeat") || heartbeat=''
    fi
    if [ -n "$queue_key" ] && [ -f "$from_dir/queue_len" ]; then
        queue=$(cat "$from_dir/queue_len") || queue=''
        queue_check=true
    fi
    if [ -f "$from_dir/quotes_ts" ]; then
        quotes_ts=$(cat "$from_dir/quotes_ts") || quotes_ts=''
        quotes_connected=true
    fi
else
    if ! heartbeat=$(redis-cli -u "$redis_url" --no-auth-warning GET "$heartbeat_key" 2>/dev/null); then
        emit "$(format_time) 状态=心跳缺失 心跳龄=- 队列=- 说明=redis 不可达"
        exit 2
    fi
    if [ -n "$queue_key" ]; then
        if ! queue=$(redis-cli -u "$redis_url" --no-auth-warning LLEN "$queue_key" 2>/dev/null); then
            emit "$(format_time) 状态=心跳缺失 心跳龄=- 队列=- 说明=redis 不可达"
            exit 2
        fi
        queue_check=true
    fi
    if [ -n "$quotes_ts_key" ]; then
        if ! quotes_ts=$(redis-cli -u "$redis_url" --no-auth-warning GET "$quotes_ts_key" 2>/dev/null); then
            emit "$(format_time) 状态=心跳缺失 心跳龄=- 队列=- 说明=redis 不可达"
            exit 2
        fi
        quotes_connected=true
    fi
fi
if ! heartbeat_ts=$(extract_heartbeat_ts "$heartbeat"); then
    emit "$(format_time) 状态=心跳缺失 心跳龄=- 队列=- 说明=心跳格式无效"
    exit 2
fi
if [ "$queue_check" = true ]; then
    queue=$(printf '%s' "$queue" | tr -d '\r\n')
    if [ -z "$queue" ] || ! is_uint "$queue"; then
        emit "$(format_time) 状态=心跳缺失 心跳龄=- 队列=- 说明=redis 数据无效"
        exit 2
    fi
    queue_display=$queue
fi
heartbeat_age=$((now - heartbeat_ts))
[ "$heartbeat_age" -lt 0 ] && heartbeat_age=0
if [ "$heartbeat_age" -gt "$stale_after" ]; then
    emit "$(format_time) 状态=心跳过期 心跳龄=${heartbeat_age} 队列=${queue_display} 说明=超过${stale_after}秒未更新"
    exit 2
fi
quote_state=未接入
quote_age='-'
quote_stale_after='-'
if [ "$quotes_source" = off ]; then
    quote_state=采集未启用
elif [ "$quotes_source" != fake ] && [ "$quotes_source" != mairui ]; then
    emit "$(format_time) 状态=配置错误 心跳龄=${heartbeat_age} 队列=${queue_display} 说明=REALTIME_QUOTES_SOURCE 无效"
    exit 2
elif [ -z "$quotes_ts_key" ]; then
    emit "$(format_time) 状态=行情未接入 心跳龄=${heartbeat_age} 队列=${queue_display} 说明=行情时间戳键未配置"
    exit 2
elif [ "$quotes_connected" = true ]; then
    quotes_ts=$(printf '%s' "$quotes_ts" | tr -d '\r\n')
    if ! is_uint "$quotes_ts"; then
        emit "$(format_time) 状态=行情过期 心跳龄=${heartbeat_age} 队列=${queue_display} 说明=行情时间戳缺失或无效"
        exit 2
    fi
    if [ -n "${INTRADAY_QUOTES_STALE_S:-}" ]; then
        quote_stale_after=$INTRADAY_QUOTES_STALE_S
        if ! is_uint "$quote_stale_after"; then
            emit "$(format_time) 状态=配置错误 心跳龄=${heartbeat_age} 队列=${queue_display} 说明=INTRADAY_QUOTES_STALE_S 必须是非负整数"
            exit 2
        fi
    elif [ ! -r "$realtime_config" ]; then
        emit "$(format_time) 状态=配置错误 心跳龄=${heartbeat_age} 队列=${queue_display} 说明=实时行情配置不可读"
        exit 2
    else
        if ! config_values=$(awk '
            /^[[:space:]]*intervals:[[:space:]]*$/ { section=1; next }
            section && /^[^[:space:]]/ { section=0 }
            section && /^[[:space:]]+quote_interval_s:[[:space:]]*/ {
                value=$0; sub(/^[^:]*:[[:space:]]*/, "", value); sub(/[[:space:]]*#.*/, "", value); gsub(/[[:space:]]/, "", value); quote=value
            }
            section && /^[[:space:]]+stale_threshold_s:[[:space:]]*/ {
                value=$0; sub(/^[^:]*:[[:space:]]*/, "", value); sub(/[[:space:]]*#.*/, "", value); gsub(/[[:space:]]/, "", value); stale=value; stale_seen=1
            }
            END {
                if (quote !~ /^[0-9]+$/ || quote == 0 || !stale_seen) exit 1
                if (stale != "null" && stale !~ /^[0-9]+$/) exit 1
                print quote, stale
            }
        ' "$realtime_config"); then
            emit "$(format_time) 状态=配置错误 心跳龄=${heartbeat_age} 队列=${queue_display} 说明=实时行情配置无效"
            exit 2
        fi
        quote_interval=${config_values%% *}
        config_stale=${config_values#* }
        if [ "$config_stale" = null ]; then quote_stale_after=$((quote_interval * 2)); else quote_stale_after=$config_stale; fi
    fi
    quote_age=$((now - quotes_ts))
    if [ "$quote_age" -lt "-$quotes_future_tolerance" ]; then quote_state=时间异常
    elif [ "$quote_age" -lt 0 ]; then quote_age=0; quote_state=正常
    elif [ "$quote_age" -gt "$quote_stale_after" ]; then quote_state=过期
    else quote_state=正常
    fi
fi
if [ "$queue_check" = true ] && [ "$queue" -eq 0 ]; then
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
if [ "$quote_state" = 过期 ]; then
    emit "$(format_time) 状态=行情过期 心跳龄=${heartbeat_age} 队列=${queue_display} 说明=行情龄=${quote_age}秒 阈值=${quote_stale_after}秒"
    exit 2
fi
if [ "$quote_state" = 时间异常 ]; then
    emit "$(format_time) 状态=行情时间异常 心跳龄=${heartbeat_age} 队列=${queue_display} 说明=行情时间差=${quote_age}秒（未来时间戳）"
    exit 2
fi
if [ "$queue_check" = true ]; then
    queue_note='盘中心跳与队列正常'
else
    queue_note='盘中心跳正常；队列检查未接入（待 I4 定稿）'
fi
case "$quote_state" in
    正常) quote_note="行情龄=${quote_age}秒 阈值=${quote_stale_after}秒" ;;
    采集未启用) quote_note='行情采集未启用' ;;
    未接入) quote_note='行情新鲜度未接入' ;;
esac
emit "$(format_time) 状态=正常 心跳龄=${heartbeat_age} 队列=${queue_display} 说明=${queue_note}；${quote_note}"
exit 0

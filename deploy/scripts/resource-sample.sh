#!/usr/bin/env bash
# 只读采样指定 Compose 项目的容器资源使用情况。
set -euo pipefail

SAMPLES="${SAMPLES:-5}"
INTERVAL_S="${INTERVAL_S:-60}"
PROJECT="${COMPOSE_PROJECT:-}"
OUT="-"

usage() {
  echo "用法：$0 [--samples 次数] [--interval 秒] [--project 项目] [--out 文件]" >&2
  exit 2
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --samples)
      [ "$#" -ge 2 ] || usage
      SAMPLES="$2"
      shift 2
      ;;
    --interval)
      [ "$#" -ge 2 ] || usage
      INTERVAL_S="$2"
      shift 2
      ;;
    --project)
      [ "$#" -ge 2 ] || usage
      PROJECT="$2"
      shift 2
      ;;
    --out)
      [ "$#" -ge 2 ] || usage
      OUT="$2"
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

case "$SAMPLES" in ''|*[!0-9]*) usage ;; esac
case "$INTERVAL_S" in ''|*[!0-9]*) usage ;; esac
# 项目名必须显式给出（--project 或 COMPOSE_PROJECT）；不调用 compose 封装入口，避免生成 .env 或密钥。
[ -n "$PROJECT" ] || usage

read -r -a DOCKER <<< "${AIA_DOCKER:-docker}"
if [ "$OUT" = - ]; then
  exec 3>&1
else
  exec 3>"$OUT"
fi
printf 'ts,container,cpu_pct,mem_usage,mem_limit,mem_pct,pids\n' >&3

declare -A CPU_PEAK MEM_PEAK SEEN
containers=()

record_peak() {
  local name="$1" cpu="$2" mem="$3"
  local cpu_num="${cpu%%%}" mem_num="${mem%%%}"
  if [[ "$cpu_num" =~ ^[0-9]+([.][0-9]+)?$ ]]; then
    if [ -z "${CPU_PEAK[$name]+x}" ] || awk -v a="$cpu_num" -v b="${CPU_PEAK[$name]}" 'BEGIN { exit !(a > b) }'; then
      CPU_PEAK["$name"]="$cpu"
    fi
  fi
  if [[ "$mem_num" =~ ^[0-9]+([.][0-9]+)?$ ]]; then
    if [ -z "${MEM_PEAK[$name]+x}" ] || awk -v a="$mem_num" -v b="${MEM_PEAK[$name]}" 'BEGIN { sub(/%$/, "", b); exit !(a > b) }'; then
      MEM_PEAK["$name"]="$mem"
    fi
  fi
  if [ -z "${SEEN[$name]+x}" ]; then
    SEEN["$name"]=1
    containers+=("$name")
  fi
}

sample_index=0
while [ "$sample_index" -lt "$SAMPLES" ]; do
  ids="$("${DOCKER[@]}" ps --filter "label=com.docker.compose.project=${PROJECT}" --format '{{.ID}}')"
  if [ -n "$ids" ]; then
    mapfile -t id_list < <(printf '%s\n' "$ids" | sed '/^$/d')
    stats="$("${DOCKER[@]}" stats --no-stream --format '{{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.MemPerc}}\t{{.PIDs}}' "${id_list[@]}")"
    stamp="$(TZ=CST-8 date '+%Y-%m-%dT%H:%M:%S%z')"
    while IFS=$'\t' read -r name cpu mem mem_pct pids; do
      [ -n "$name" ] || continue
      usage="$mem"
      limit="$mem"
      if [[ "$mem" == *" / "* ]]; then
        usage="${mem%% / *}"
        limit="${mem#* / }"
      fi
      printf '%s,%s,%s,%s,%s,%s,%s\n' "$stamp" "$name" "$cpu" "$usage" "$limit" "$mem_pct" "$pids" >&3
      record_peak "$name" "$cpu" "$mem_pct"
    done <<< "$stats"
  fi
  sample_index=$((sample_index + 1))
  if [ "$sample_index" -lt "$SAMPLES" ] && [ "$INTERVAL_S" -gt 0 ]; then
    sleep "$INTERVAL_S"
  fi
done
exec 3>&-

for name in "${containers[@]}"; do
  printf '汇总 容器=%s cpu_pct峰值=%s mem_pct峰值=%s\n' "$name" "${CPU_PEAK[$name]:--}" "${MEM_PEAK[$name]:--}"
done

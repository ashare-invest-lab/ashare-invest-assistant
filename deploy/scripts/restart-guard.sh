#!/usr/bin/env bash
# Check backfill locks before restarting, rebuilding or taking down a local stack.
{ set +x; } 2>/dev/null
set -euo pipefail

lock_dir="${AIA_RUNTIME_LOCK_DIR:-/workspace/team/runtime}"
then_command=''

usage() {
  printf '%s\n' '用法：restart-guard.sh [--lock-dir 目录] [--then "命令"]'
}

while (($#)); do
  case "$1" in
    --lock-dir|--then)
      if (($# < 2)) || [[ -z "$2" ]]; then
        usage >&2
        exit 2
      fi
      if [[ "$1" == --lock-dir ]]; then lock_dir="$2"; else then_command="$2"; fi
      shift 2
      ;;
    -h|--help) usage; exit 0 ;;
    *) usage >&2; exit 2 ;;
  esac
done

# Never follow a lock or metadata symlink into unrelated files.
first_line() {
  local line=''
  if [[ -f "$1" && ! -L "$1" ]]; then
    { IFS= read -r line < "$1"; } 2>/dev/null || true
  fi
  line="${line%$'\r'}"
  printf '%s' "${line:-未知}"
}

if [[ ! -e "$lock_dir" && ! -L "$lock_dir" ]]; then
  printf '警告：锁目录不存在：%s\n' "$lock_dir" >&2
elif [[ ! -d "$lock_dir" || ! -r "$lock_dir" || ! -x "$lock_dir" ]]; then
  printf '无法检查锁目录：%s，拒绝执行\n' "$lock_dir" >&2
  exit 2
else
  shopt -s nullglob dotglob
  locks=("$lock_dir"/*.lock)
  for lock in "${locks[@]}"; do
    owner='未知'
    if [[ ! -L "$lock" ]]; then
      if [[ -d "$lock" ]]; then
        for metadata in owner info; do
          owner="$(first_line "$lock/$metadata")"
          [[ "$owner" == '未知' ]] || break
        done
      else
        owner="$(first_line "$lock")"
      fi
    fi
    modified="$(stat -c '%y' -- "$lock" 2>/dev/null || stat -f '%Sm' -t '%Y-%m-%d %H:%M:%S %z' -- "$lock" 2>/dev/null || printf '未知')"
    printf '锁：%s | 持锁任务：%s | 修改时间：%s\n' "${lock##*/}" "$owner" "$modified"
  done
  if ((${#locks[@]})); then
    printf '%s\n' '存在回填锁，拒绝重启、重建或 down' >&2
    exit 3
  fi
fi

printf '%s\n' '无回填锁，可以重启'
if [[ -n "$then_command" ]]; then
  exec bash -c "$then_command"
fi

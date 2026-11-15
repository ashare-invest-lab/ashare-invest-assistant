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
lock_metadata() {
  [[ -f "$1" && ! -L "$1" ]] || return 0
  # Only selected metadata is displayed; never evaluate lock contents as shell.
  python3 - "$1" <<'PY' 2>/dev/null || true
import json
import re
import sys

with open(sys.argv[1], encoding="utf-8-sig") as source:
    text = source.read()

def value(item):
    return " ".join(item.split()) if isinstance(item, str) else ""

try:
    fields = json.loads(text)
except ValueError:
    fields = {}
if not isinstance(fields, dict):
    fields = {}
if not text.lstrip().startswith(("{", "[")):
    for match in re.finditer(
        r'''(?:^|\s)(task|owner|status|state)\s*=\s*(?:"([^"\r\n]*)"|'([^'\r\n]*)'|([^\s]+))''', text
    ):
        fields.setdefault(match[1], next(part for part in match.groups()[1:] if part is not None))
owner = value(fields.get("task")) or value(fields.get("owner"))
first = text.splitlines()[0] if text.splitlines() else ""
if not owner and not text.lstrip().startswith(("{", "[")) and "=" not in first:
    owner = value(first)
status = value(fields.get("status")) or value(fields.get("state"))
print(owner or "未知")
print(status or "未知")
PY
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
    status='未知'
    if [[ ! -L "$lock" ]]; then
      if [[ -d "$lock" ]]; then
        for metadata in owner info; do
          details="$(lock_metadata "$lock/$metadata")"
          parsed_owner="${details%%$'\n'*}"
          parsed_status="${details#*$'\n'}"
          [[ "$owner" != '未知' || -z "$parsed_owner" ]] || owner="$parsed_owner"
          [[ "$status" != '未知' || -z "$parsed_status" ]] || status="$parsed_status"
        done
      else
        details="$(lock_metadata "$lock")"
        owner="${details%%$'\n'*}"
        status="${details#*$'\n'}"
      fi
    fi
    modified="$(stat -c '%y' -- "$lock" 2>/dev/null || stat -f '%Sm' -t '%Y-%m-%d %H:%M:%S %z' -- "$lock" 2>/dev/null || printf '未知')"
    printf '锁：%s | 持锁任务：%s | 修改时间：%s | 状态：%s\n' "${lock##*/}" "${owner:-未知}" "$modified" "${status:-未知}"
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

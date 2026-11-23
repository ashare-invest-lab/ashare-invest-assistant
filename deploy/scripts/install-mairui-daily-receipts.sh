#!/bin/sh
# Install the two operator authorization receipts used by daily delivery.
# This script only writes JSON receipts. It never reads credentials and never
# starts collection or any Docker service.
set -eu
umask 022

TARGET_DIR=${AIA_RECEIPTS_DIR:-/run/aia/receipts}
USER_ID=
LICENCE_ID=
NOT_BEFORE=
EXPIRES_AT=
DAILY_RECEIPT_ID=
DAILY_BARS_RECEIPT_ID=

usage() {
  cat >&2 <<'EOF'
Usage: install-mairui-daily-receipts.sh \
  --user-id UUID --licence-id UUID \
  --not-before ISO8601 --expires-at ISO8601 \
  [--daily-receipt-id UUID] [--daily-bars-receipt-id UUID] \
  [--target-dir ABSOLUTE_PATH]

The command installs mairui-daily.json and mairui-daily-bars.json as root:root
0444 files. It does not contact Mairui or start a worker.
EOF
  exit 2
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --target-dir)
      [ "$#" -ge 2 ] || usage
      TARGET_DIR=$2
      shift 2
      ;;
    --user-id)
      [ "$#" -ge 2 ] || usage
      USER_ID=$2
      shift 2
      ;;
    --licence-id)
      [ "$#" -ge 2 ] || usage
      LICENCE_ID=$2
      shift 2
      ;;
    --not-before)
      [ "$#" -ge 2 ] || usage
      NOT_BEFORE=$2
      shift 2
      ;;
    --expires-at)
      [ "$#" -ge 2 ] || usage
      EXPIRES_AT=$2
      shift 2
      ;;
    --daily-receipt-id)
      [ "$#" -ge 2 ] || usage
      DAILY_RECEIPT_ID=$2
      shift 2
      ;;
    --daily-bars-receipt-id)
      [ "$#" -ge 2 ] || usage
      DAILY_BARS_RECEIPT_ID=$2
      shift 2
      ;;
    --help|-h)
      usage
      ;;
    *)
      echo "unknown option: $1" >&2
      usage
      ;;
  esac
done

[ "$(id -u)" -eq 0 ] || {
  echo "must run as root to install root-owned receipts" >&2
  exit 3
}

case "$TARGET_DIR" in
  /*) ;;
  *) echo "target directory must be an absolute path" >&2; exit 2 ;;
esac
[ "$TARGET_DIR" != "/" ] || {
  echo "refusing to use / as the receipt directory" >&2
  exit 2
}

uuid_ok() {
  printf '%s\n' "$1" | grep -Eq '^[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[1-5][0-9A-Fa-f]{3}-[89AaBb][0-9A-Fa-f]{3}-[0-9A-Fa-f]{12}$'
}

iso_ok() {
  printf '%s\n' "$1" | grep -Eq '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(Z|[+-][0-9]{2}:[0-9]{2})$'
}

[ -n "$USER_ID" ] && uuid_ok "$USER_ID" || { echo "invalid --user-id" >&2; exit 2; }
[ -n "$LICENCE_ID" ] && uuid_ok "$LICENCE_ID" || { echo "invalid --licence-id" >&2; exit 2; }
[ -n "$NOT_BEFORE" ] && iso_ok "$NOT_BEFORE" || { echo "invalid --not-before" >&2; exit 2; }
[ -n "$EXPIRES_AT" ] && iso_ok "$EXPIRES_AT" || { echo "invalid --expires-at" >&2; exit 2; }
python3 - "$NOT_BEFORE" "$EXPIRES_AT" <<'PY'
import datetime as dt
import sys

start, end = (dt.datetime.fromisoformat(value.replace("Z", "+00:00")) for value in sys.argv[1:])
if start.tzinfo is None or end.tzinfo is None or start >= end:
    raise SystemExit("not-before must be earlier than expires-at and both must include a timezone")
PY

if [ -z "$DAILY_RECEIPT_ID" ]; then
  DAILY_RECEIPT_ID=$(cat /proc/sys/kernel/random/uuid 2>/dev/null || uuidgen)
fi
if [ -z "$DAILY_BARS_RECEIPT_ID" ]; then
  DAILY_BARS_RECEIPT_ID=$(cat /proc/sys/kernel/random/uuid 2>/dev/null || uuidgen)
fi
uuid_ok "$DAILY_RECEIPT_ID" || { echo "invalid daily receipt id" >&2; exit 2; }
uuid_ok "$DAILY_BARS_RECEIPT_ID" || { echo "invalid daily-bars receipt id" >&2; exit 2; }

mkdir -p -- "$TARGET_DIR"
[ ! -L "$TARGET_DIR" ] || { echo "target directory must not be a symlink" >&2; exit 3; }

mode=$(stat -c '%a' -- "$TARGET_DIR")
owner=$(stat -c '%u' -- "$TARGET_DIR")
mode_num=$((0$mode))
[ "$owner" -eq 0 ] || { echo "target directory must be root-owned" >&2; exit 3; }
[ $((mode_num & 18)) -eq 0 ] || { echo "target directory must not be group/other writable" >&2; exit 3; }

DAILY_PATH=$TARGET_DIR/mairui-daily.json
DAILY_BARS_PATH=$TARGET_DIR/mairui-daily-bars.json
[ ! -e "$DAILY_PATH" ] && [ ! -L "$DAILY_PATH" ] || { echo "refusing to overwrite mairui-daily.json" >&2; exit 3; }
[ ! -e "$DAILY_BARS_PATH" ] && [ ! -L "$DAILY_BARS_PATH" ] || { echo "refusing to overwrite mairui-daily-bars.json" >&2; exit 3; }

STAGING=$(mktemp -d "$TARGET_DIR/.mairui-daily-receipts.XXXXXX")
INSTALLED_DAILY=0
INSTALLED_DAILY_BARS=0
cleanup() {
  if [ "$INSTALLED_DAILY" -eq 1 ]; then
    rm -f -- "$DAILY_PATH"
  fi
  if [ "$INSTALLED_DAILY_BARS" -eq 1 ]; then
    rm -f -- "$DAILY_BARS_PATH"
  fi
  rm -f -- "$STAGING/mairui-daily.json" "$STAGING/mairui-daily-bars.json"
  rmdir -- "$STAGING" 2>/dev/null || true
}
trap cleanup EXIT HUP INT TERM

cat > "$STAGING/mairui-daily.json" <<EOF
{"kind":"mairui_daily_snapshot","user_id":"$USER_ID","licence_id":"$LICENCE_ID","receipt_id":"$DAILY_RECEIPT_ID","not_before":"$NOT_BEFORE","expires_at":"$EXPIRES_AT"}
EOF
cat > "$STAGING/mairui-daily-bars.json" <<EOF
{"kind":"mairui_daily_bars","user_id":"$USER_ID","licence_id":"$LICENCE_ID","receipt_id":"$DAILY_BARS_RECEIPT_ID","not_before":"$NOT_BEFORE","expires_at":"$EXPIRES_AT"}
EOF

chown root:root -- "$STAGING/mairui-daily.json" "$STAGING/mairui-daily-bars.json"
chmod 0444 -- "$STAGING/mairui-daily.json" "$STAGING/mairui-daily-bars.json"
mv -- "$STAGING/mairui-daily.json" "$DAILY_PATH"
INSTALLED_DAILY=1
mv -- "$STAGING/mairui-daily-bars.json" "$DAILY_BARS_PATH"
INSTALLED_DAILY_BARS=1

trap - EXIT HUP INT TERM
rmdir -- "$STAGING"
printf '%s\n' "installed root-owned 0444 daily authorization receipts in $TARGET_DIR"

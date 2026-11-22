#!/usr/bin/env bash
set -euo pipefail

# 隔离的迁移演练。只创建本脚本命名的临时容器和临时数据库，不接触用户栈。

usage() {
  printf '%s\n' '用法：milestone-sync-drill.sh [--from REF] [--to REF] [--keep]'
}

from_ref="2dbfdee"
to_ref="origin/main"
keep=0

export_safe_runtime_env() {
  export APP_ENV=test MAIRUI_MODE=replay DAILY_BARS_SOURCE=off INTRADAY_ENABLED=false
}

while (($#)); do
  case "$1" in
    --from)
      (($# >= 2)) || { usage >&2; exit 2; }
      from_ref="$2"
      shift 2
      ;;
    --to)
      (($# >= 2)) || { usage >&2; exit 2; }
      to_ref="$2"
      shift 2
      ;;
    --keep)
      keep=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      usage >&2
      exit 2
      ;;
  esac
done

if [[ "${DRILL_SELFTEST_ENV:-0}" == 1 ]]; then
  export_safe_runtime_env
  printf 'export APP_ENV=%s\n' "$APP_ENV"
  printf 'export MAIRUI_MODE=%s\n' "$MAIRUI_MODE"
  printf 'export DAILY_BARS_SOURCE=%s\n' "$DAILY_BARS_SOURCE"
  printf 'export INTRADAY_ENABLED=%s\n' "$INTRADAY_ENABLED"
  exit 0
fi

command -v git >/dev/null 2>&1 || { echo '缺少 git' >&2; exit 2; }
command -v docker >/dev/null 2>&1 || { echo '缺少 docker' >&2; exit 2; }
command -v tar >/dev/null 2>&1 || { echo '缺少 tar' >&2; exit 2; }
command -v uv >/dev/null 2>&1 || { echo '缺少 uv' >&2; exit 2; }
command -v python3 >/dev/null 2>&1 || { echo '缺少 python3' >&2; exit 2; }

repo_root="$(git rev-parse --show-toplevel)"
work_root="$(mktemp -d "${TMPDIR:-/tmp}/aia-o131-drill.XXXXXX")"
from_dir="$work_root/from"
to_dir="$work_root/to"
mkdir -p "$from_dir" "$to_dir"

drill_out="${DRILL_OUT:-/workspace/team/runtime/T-O131}"
mkdir -p "$drill_out"
log_stamp="$(date -u +%Y%m%dT%H%M%SZ)"
log_file="$drill_out/drill-$log_stamp.log"
exec > >(tee "$log_file") 2>&1
printf '完整日志：%s\n' "$log_file"

container="aia-o131-drill-$$"
container_created=0
db_user="aia"
db_name="aia"
db_password="$(od -An -N24 -tx1 /dev/urandom | tr -d '[:space:]')"
dump_file="$work_root/from.dump"
dump_in="/tmp/aia-o131-drill-$$.dump"
restore_db="aia_o131_restore_$$"
restore_err="$work_root/restore.stderr"

from_head=""
to_head=""
failed_step=""
declare -A step_seconds=()
declare -A step_results=()

cleanup() {
  if [[ "$keep" -eq 0 && "$container_created" -eq 1 && "$container" == aia-o131-drill-* ]]; then
    docker rm -f "$container" >/dev/null 2>&1 || true
  fi
  if [[ -n "${work_root:-}" ]]; then
    rm -rf -- "$work_root"
  fi
}
trap cleanup EXIT

announce_keep() {
  if [[ "$keep" -eq 1 && "$container_created" -eq 1 ]]; then
    printf '保留容器：%s\n' "$container"
  fi
}

summary() {
  printf '{"from_head":"%s","to_head":"%s","steps":{' "$from_head" "$to_head"
  local key first=1
  for key in from_upgrade fake_data pg_dump backup_verify to_upgrade rollback_a rollback_b; do
    ((first)) || printf ','
    first=0
    printf '"%s":{"seconds":%s,"result":"%s"}' \
      "$key" "${step_seconds[$key]:-0}" "${step_results[$key]:-not_run}"
  done
  printf '}}\n'
}

fail_phase() {
  printf '准备阶段失败：%s\n' "$1" >&2
  announce_keep
  summary
  exit 1
}

archive_backend() {
  local ref="$1" dest="$2"
  git -C "$repo_root" rev-parse --verify "${ref}^{commit}" >/dev/null \
    || return 1
  git -C "$repo_root" archive --format=tar "${ref}:src/backend" \
    | tar -xf - -C "$dest"
}

archive_backend "$from_ref" "$from_dir" || fail_phase "无法导出 from=$from_ref 的 src/backend"
archive_backend "$to_ref" "$to_dir" || fail_phase "无法导出 to=$to_ref 的 src/backend"

uv_cache_dir="${UV_CACHE_DIR:-/tmp/uv-cache-o131}"
printf '导出完成：from=%s，to=%s\n' "$from_ref" "$to_ref"
printf '按 CI migrations job 执行 uv sync --frozen。\n'
(cd "$from_dir" && UV_CACHE_DIR="$uv_cache_dir" uv sync --frozen) \
  || fail_phase 'from 依赖准备失败'
(cd "$to_dir" && UV_CACHE_DIR="$uv_cache_dir" uv sync --frozen) \
  || fail_phase 'to 依赖准备失败'

pg_image='timescale/timescaledb:2.31.0-pg16@sha256:322ae364eca3321cf2a48f1ef31213b87843413b3cf8feeebf54e999a26bb731'
host_port="$(python3 - <<'PY'
import socket

with socket.socket() as sock:
    sock.bind(("127.0.0.1", 0))
    print(sock.getsockname()[1])
PY
)"
[[ "$host_port" =~ ^[0-9]+$ ]] || fail_phase '未能取得随机宿主端口'
printf '启动隔离容器：%s\n' "$container"
docker run -d --name "$container" \
  --network host --env PGPORT="$host_port" \
  --env POSTGRES_USER="$db_user" \
  --env POSTGRES_PASSWORD="$db_password" \
  --env POSTGRES_DB="$db_name" \
  "$pg_image" -c "port=${host_port}" -c listen_addresses=127.0.0.1 >/dev/null \
  || fail_phase '隔离 TimescaleDB 容器启动失败'
container_created=1

ready=0
for _ in $(seq 1 60); do
  if docker exec "$container" pg_isready -U "$db_user" -d "$db_name" >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 1
done
[[ "$ready" -eq 1 ]] || fail_phase '隔离数据库未就绪'

database_url="postgresql://$db_user:$db_password@127.0.0.1:$host_port/$db_name"
export DATABASE_URL="$database_url"
export_safe_runtime_env

db_psql() {
  docker exec -i -e PGPASSWORD="$db_password" "$container" \
    psql -X -v ON_ERROR_STOP=1 -U "$db_user" "$@"
}

db_psql -d "$db_name" -c 'CREATE EXTENSION IF NOT EXISTS timescaledb' \
  || fail_phase '隔离库 TimescaleDB 扩展准备失败'

run_alembic() {
  local dir="$1"
  shift
  (cd "$dir" && DATABASE_URL="$database_url" uv run --frozen alembic "$@")
}

alembic_head() {
  local dir="$1"
  (cd "$dir" && DATABASE_URL="$database_url" uv run --frozen alembic heads \
    | awk 'NF { print $1; exit }')
}

from_head="$(alembic_head "$from_dir")" || fail_phase '读取 from Alembic 头失败'
to_head="$(alembic_head "$to_dir")" || fail_phase '读取 to Alembic 头失败'
[[ "$from_head" =~ ^[0-9a-fA-F]+$ ]] || fail_phase "from Alembic 头格式异常：$from_head"
[[ "$to_head" =~ ^[0-9a-fA-F]+$ ]] || fail_phase "to Alembic 头格式异常：$to_head"
printf '迁移头：from=%s，to=%s；CI job 不先跑 db-apply-timescale.sh。\n' "$from_head" "$to_head"

assert_version() {
  local database="$1" expected="$2" actual
  actual="$(db_psql -d "$database" -Atqc 'SELECT version_num FROM public.alembic_version')" \
    || return 1
  [[ "$actual" == "$expected" ]] || {
    printf '版本断言失败：数据库=%s，实际=%s，期望=%s\n' "$database" "$actual" "$expected" >&2
    return 1
  }
}

assert_fixture() {
  local database="$1" drill_count business_count
  drill_count="$(db_psql -d "$database" -Atqc \
    "SELECT count(*) FROM public.t_o131_drill WHERE note LIKE 'synthetic O131 drill %'")" \
    || return 1
  business_count="$(db_psql -d "$database" -Atqc \
    "SELECT count(*) FROM app.dimension_definitions WHERE key = 'technical' AND name = 'o131 synthetic drill'")" \
    || return 1
  [[ "$drill_count" == 3 && "$business_count" == 1 ]] || {
    printf '虚构数据断言失败：drill=%s，business=%s\n' "$drill_count" "$business_count" >&2
    return 1
  }
}

step_from_upgrade() {
  run_alembic "$from_dir" upgrade head || return 1
  assert_version "$db_name" "$from_head"
}

step_fake_data() {
  db_psql -d "$db_name" <<'SQL' || return 1
CREATE TABLE public.t_o131_drill (id integer PRIMARY KEY, note text NOT NULL);
INSERT INTO public.t_o131_drill (id, note) VALUES
  (1, 'synthetic O131 drill 1'),
  (2, 'synthetic O131 drill 2'),
  (3, 'synthetic O131 drill 3');
INSERT INTO app.dimension_definitions (key, name, description)
VALUES ('technical', 'o131 synthetic drill', 'synthetic fixture only');
SQL
  printf '业务表夹具：app.dimension_definitions；仅使用虚构值。\n'
  assert_fixture "$db_name"
}

step_pg_dump() {
  docker exec -e PGPASSWORD="$db_password" "$container" \
    pg_dump -U "$db_user" -d "$db_name" -Fc -Z 6 > "$dump_file" \
    || return 1
  [[ -s "$dump_file" ]] || {
    echo 'pg_dump 产物为空' >&2
    return 1
  }
  chmod 600 "$dump_file"
  printf 'pg_dump -Fc 已写入临时目录。\n'
}

copy_dump_to_container() {
  docker cp "$dump_file" "$container:$dump_in" >/dev/null || return 1
  docker exec -e PGPASSWORD="$db_password" "$container" chmod 644 "$dump_in"
}

restore_dump_to_db() {
  local target_db="$1" restore_rc=0 unexpected
  db_psql -d "$target_db" -c 'SELECT timescaledb_pre_restore()' || return 1
  docker exec -e PGPASSWORD="$db_password" "$container" \
    pg_restore -U "$db_user" -d "$target_db" -j 1 --no-password "$dump_in" \
    2>"$restore_err" || restore_rc=$?
  unexpected="$(grep -E 'error:' "$restore_err" \
    | grep -vE 'extension "timescaledb" already exists|COMMENT ON EXTENSION' || true)"
  if [[ -n "$unexpected" || ("$restore_rc" -ne 0 && ! -s "$restore_err") ]]; then
    cat "$restore_err" >&2
    printf 'pg_restore 失败，rc=%s\n' "$restore_rc" >&2
    return 1
  fi
  [[ "$restore_rc" -eq 0 ]] || echo 'pg_restore 仅报告预创建 TimescaleDB 扩展的已知告警。'
  db_psql -d "$target_db" -c 'SELECT timescaledb_post_restore()' || return 1
  db_psql -d "$target_db" -q -c 'ANALYZE' || return 1
}

step_backup_verify() {
  copy_dump_to_container || return 1
  docker exec -e PGPASSWORD="$db_password" "$container" \
    pg_restore --list "$dump_in" >/dev/null || return 1
  local verify_db="aia_o131_verify_$$" verify_rc=0
  db_psql -d postgres -c "CREATE DATABASE \"$verify_db\"" || return 1
  db_psql -d "$verify_db" -c 'CREATE EXTENSION IF NOT EXISTS timescaledb' || verify_rc=1
  if [[ "$verify_rc" -eq 0 ]]; then
    restore_dump_to_db "$verify_db" || verify_rc=1
  fi
  if [[ "$verify_rc" -eq 0 ]]; then
    assert_version "$verify_db" "$from_head" || verify_rc=1
    assert_fixture "$verify_db" || verify_rc=1
  fi
  db_psql -d postgres -c "DROP DATABASE IF EXISTS \"$verify_db\"" || verify_rc=1
  return "$verify_rc"
}

step_to_upgrade() {
  run_alembic "$to_dir" upgrade head || return 1
  assert_version "$db_name" "$to_head" || return 1
  assert_fixture "$db_name"
}

step_rollback_a() {
  run_alembic "$to_dir" downgrade "$from_head" || return 1
  assert_version "$db_name" "$from_head" || return 1
  assert_fixture "$db_name" || return 1
  run_alembic "$to_dir" upgrade head || return 1
  assert_version "$db_name" "$to_head"
}

step_rollback_b() {
  db_psql -d postgres -c "CREATE DATABASE \"$restore_db\"" || return 1
  db_psql -d "$restore_db" -c 'CREATE EXTENSION IF NOT EXISTS timescaledb' || return 1
  copy_dump_to_container || return 1
  restore_dump_to_db "$restore_db" || return 1
  assert_version "$restore_db" "$from_head" || return 1
  assert_fixture "$restore_db"
}

run_step() {
  local key="$1" label="$2"
  shift 2
  local started finished rc
  started="$(date +%s)"
  printf '步骤 %s 开始。\n' "$label"
  set +e
  "$@"
  rc=$?
  set -e
  finished="$(date +%s)"
  step_seconds["$key"]=$((finished - started))
  if [[ "$rc" -eq 0 ]]; then
    step_results["$key"]='ok'
    printf '步骤 %s 完成，用时 %ss。\n' "$label" "${step_seconds[$key]}"
  else
    step_results["$key"]='failed'
    failed_step="$label"
    printf '步骤失败：%s（用时 %ss）。\n' "$label" "${step_seconds[$key]}" >&2
    announce_keep
    summary
    exit "$rc"
  fi
}

run_step from_upgrade '① from 代码 upgrade head' step_from_upgrade
run_step fake_data '② 写入虚构数据' step_fake_data
run_step pg_dump '③ pg_dump -Fc 备份' step_pg_dump
run_step backup_verify '④ 备份可恢复性校验' step_backup_verify
run_step to_upgrade '⑤ to 代码 upgrade head' step_to_upgrade
run_step rollback_a '⑥ 回滚 A：downgrade 到 from 后再 upgrade' step_rollback_a
run_step rollback_b '⑦ 回滚 B：新库 pg_restore 备份' step_rollback_b

printf '演练完成。\n'
announce_keep
summary

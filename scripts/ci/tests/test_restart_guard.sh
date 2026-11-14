#!/usr/bin/env bash
# Only synthetic locks and marker commands; never invokes Docker or network APIs.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
guard="$here/../../../deploy/scripts/restart-guard.sh"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
export AIA_RUNTIME_LOCK_DIR="$tmp/runtime with spaces"
export GUARD_TEST_MARKER="$tmp/then-marker"
mkdir -p "$AIA_RUNTIME_LOCK_DIR"
passed=0

fail() { printf 'FAIL: %s\n' "$*" >&2; exit 1; }
ok() { passed=$((passed + 1)); printf 'ok - %s\n' "$*"; }
run_guard() {
  rc=0
  output="$(bash "$guard" "$@" 2>&1)" || rc=$?
}
expect_rc() { [[ "$rc" == "$1" ]] || fail "退出码 $rc，预期 $1：$output"; }

run_guard --then 'printf executed > "$GUARD_TEST_MARKER"'
expect_rc 0
[[ -f "$GUARD_TEST_MARKER" && "$output" == *'无回填锁，可以重启'* ]] || fail '空目录未放行'
rm "$GUARD_TEST_MARKER"
ok '无锁退出 0 且执行 --then'

printf 'T-B84\nDO_NOT_PRINT_SECOND_LINE\n' > "$AIA_RUNTIME_LOCK_DIR/mairui-backfill.lock"
run_guard --then 'printf executed > "$GUARD_TEST_MARKER"'
expect_rc 3
[[ ! -e "$GUARD_TEST_MARKER" ]] || fail '有锁仍执行 --then'
[[ "$output" == *'mairui-backfill.lock | 持锁任务：T-B84 | 修改时间：'* ]] || fail '缺少锁信息'
[[ "$output" =~ 修改时间：[0-9]{4}-[0-9]{2}-[0-9]{2} ]] || fail '未显示修改时间'
[[ "$output" != *DO_NOT_PRINT_SECOND_LINE* ]] || fail '读取了第二行'
ok '回填文件锁退出 3 且阻止 --then，仅输出首行和修改时间'

mkdir "$AIA_RUNTIME_LOCK_DIR/owner.lock" "$AIA_RUNTIME_LOCK_DIR/info.lock" "$AIA_RUNTIME_LOCK_DIR/empty.lock"
printf 'T-OWNER\r\nDO_NOT_PRINT_SECOND_LINE\n' > "$AIA_RUNTIME_LOCK_DIR/owner.lock/owner"
printf 'T-INFO' > "$AIA_RUNTIME_LOCK_DIR/info.lock/info"
printf 'T-HIDDEN' > "$AIA_RUNTIME_LOCK_DIR/.hidden.lock"
printf 'DO_NOT_PRINT_UNRELATED\n' > "$AIA_RUNTIME_LOCK_DIR/unrelated.txt"
printf 'DO_NOT_PRINT_UNRELATED\n' > "$AIA_RUNTIME_LOCK_DIR/empty.lock/other"
run_guard
expect_rc 3
for expected in 'owner.lock | 持锁任务：T-OWNER' 'info.lock | 持锁任务：T-INFO' 'empty.lock | 持锁任务：未知' '.hidden.lock | 持锁任务：T-HIDDEN' 'mairui-backfill.lock'; do
  [[ "$output" == *"$expected"* ]] || fail "未列出 $expected"
done
[[ "$output" != *DO_NOT_PRINT* && "$output" != *unrelated.txt* ]] || fail '泄露了非首行或无关文件'
ok '所有锁、owner/info、未知、隐藏锁和不以换行结尾的首行'

mkdir "$tmp/clear"
run_guard --lock-dir "$tmp/clear" --then 'printf executed > "$GUARD_TEST_MARKER"'
expect_rc 0
[[ -f "$GUARD_TEST_MARKER" ]] || fail '--lock-dir 未覆盖环境变量'
rm "$GUARD_TEST_MARKER"
ok '参数优先于环境变量'

run_guard --lock-dir "$tmp/missing" --then 'printf executed > "$GUARD_TEST_MARKER"'
expect_rc 0
[[ "$output" == *警告* && "$output" == *'无回填锁，可以重启'* && -f "$GUARD_TEST_MARKER" ]] || fail '不存在目录未警告或未放行'
rm "$GUARD_TEST_MARKER"
ok '锁目录不存在：警告、退出 0 且执行 --then'

mkdir "$tmp/links" "$tmp/links/metadata.lock" "$tmp/external-dir"
printf 'DO_NOT_PRINT_EXTERNAL\n' > "$tmp/external-file"
printf 'DO_NOT_PRINT_EXTERNAL\n' > "$tmp/external-dir/owner"
ln -s "$tmp/external-file" "$tmp/links/file.lock"
ln -s "$tmp/external-dir" "$tmp/links/directory.lock"
ln -s "$tmp/external-file" "$tmp/links/metadata.lock/owner"
ln -s "$tmp/nonexistent" "$tmp/links/dangling.lock"
run_guard --lock-dir "$tmp/links" --then 'printf executed > "$GUARD_TEST_MARKER"'
expect_rc 3
[[ "$output" != *DO_NOT_PRINT* && ! -e "$GUARD_TEST_MARKER" ]] || fail '符号链接泄露或放行'
for expected in file.lock directory.lock metadata.lock dangling.lock; do
  [[ "$output" == *"$expected | 持锁任务：未知"* ]] || fail "符号链接未作为锁：$expected"
done
ok '符号链接只报告未知，不读取锁外文件'

run_guard --lock-dir "$tmp/clear" --then 'exit 17'
expect_rc 17
ok '--then 透传失败退出码'

run_guard --lock-dir "$tmp/external-file" --then 'printf executed > "$GUARD_TEST_MARKER"'
expect_rc 2
[[ ! -e "$GUARD_TEST_MARKER" ]] || fail '无效目录仍执行 --then'
ok '锁路径不是目录时拒绝执行'

for argument in --then --lock-dir --unknown; do
  run_guard "$argument"
  expect_rc 2
done
ok '无效参数退出 2'
printf 'restart guard selftest: %s passed\n' "$passed"

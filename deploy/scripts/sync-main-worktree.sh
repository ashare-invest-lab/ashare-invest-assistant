#!/usr/bin/env bash
# 把用户本地栈同步到最新 origin/main。
# 用法（在 WSL 中，仓库默认 /mnt/f/ashare-invest-assistant）：
#   bash deploy/scripts/sync-main-worktree.sh
#   bash deploy/scripts/sync-main-worktree.sh --apply
# 默认 dry-run。--apply 才 fetch、建 worktree、备份、迁移/重建/启动、校验。
# 复用 deploy/scripts/wrapup/{backup,start-stack,halt-check,verify,rollback}.sh。
# 红线：不 down -v、不 prune、不调麦蕊、不解 HALT、不改外网出口、不导入正式卡。
# shellcheck disable=SC1091
{ set +x; } 2>/dev/null
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WRAPUP_DIR="${AIA_SYNC_WRAPUP_DIR:-$SCRIPT_DIR/wrapup}"

usage() {
  cat <<'EOF'
用法：deploy/scripts/sync-main-worktree.sh [--apply] [wrapup 公共选项]
  默认 dry-run：只打印将要执行的步骤，不 fetch、不建 worktree、不写备份、不启栈。
  --apply：git fetch origin；在 <仓库>/.worktrees/<origin/main 短哈希> 新建 worktree；
           先 backup.sh，再在新工作树 start-stack.sh（迁移/重建/启动），再 halt-check（不 --repair）
           与 verify.sh；任一步失败则 rollback.sh --apply --backup-dir <本轮 DEST> --rollback-head <同步前 HEAD>（不传源库 --db）后退出。
  仓库根：AIA_SYNC_ROOT，或本脚本向上三级，或已存在的 /mnt/f/ashare-invest-assistant。
  Windows：在 WSL 里执行，不要用 cmd.exe。不要 down -v。
EOF
}

# 拒绝任何形式的 down -v / compose down -v（本脚本永不调用 down.sh）。
for a in "$@"; do
  case "$a" in
    -v|--volumes|--down-v)
      echo "ERROR: 拒绝 $a。同步脚本禁止 down -v / 删数据卷。" >&2
      exit 2
      ;;
  esac
done
# 整段参数里也不允许拼出 down -v
joined=" $* "
if printf '%s' "$joined" | grep -Eq -- '(^|[[:space:]])down[[:space:]]+-v([[:space:]]|$)|compose[[:space:]]+down[[:space:]]+-v'; then
  echo "ERROR: 拒绝 down -v。同步脚本禁止删除数据卷。" >&2
  exit 2
fi

APPLY=0
PASSTHRU=()
while [ $# -gt 0 ]; do
  case "$1" in
    -h|--help) usage; exit 0 ;;
    --apply) APPLY=1; PASSTHRU+=("$1"); shift ;;
    --backup-dir|--target|--rollback-head|--volume-prefix|--container|--db|--volume|--out-dir)
      PASSTHRU+=("$1" "$2"); shift 2 ;;
    --repair)
      echo "ERROR: 拒绝 --repair（不解 HALT，不改 halt 目录）。" >&2
      exit 2
      ;;
    --)
      shift
      PASSTHRU+=("$@")
      break
      ;;
    -*)
      echo "ERROR: 未知参数：$1（见 --help）" >&2
      exit 2
      ;;
    *)
      echo "ERROR: 未知参数：$1（见 --help）" >&2
      exit 2
      ;;
  esac
done

log() { printf '[%s] %s\n' "$(date +'%Y-%m-%d %H:%M:%S %Z')" "$*" >&2; }

die() {
  log "ERROR: $*"
  log "失败。不要 down -v，不要 prune，不要调麦蕊，不要解除 HALT，不要改外网出口，不要导入正式卡。"
  exit 1
}

resolve_root() {
  if [ -n "${AIA_SYNC_ROOT:-}" ]; then
    printf '%s\n' "$AIA_SYNC_ROOT"
    return 0
  fi
  local cand
  cand="$(cd "$SCRIPT_DIR/../.." && pwd)"
  if git -C "$cand" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    printf '%s\n' "$cand"
    return 0
  fi
  if [ -d /mnt/f/ashare-invest-assistant/.git ] || git -C /mnt/f/ashare-invest-assistant rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    printf '%s\n' "/mnt/f/ashare-invest-assistant"
    return 0
  fi
  die "找不到仓库根。请设置 AIA_SYNC_ROOT，或在仓库内执行本脚本。"
}

ROOT="$(resolve_root)"
git -C "$ROOT" rev-parse --is-inside-work-tree >/dev/null 2>&1 || die "不是 git 仓库：$ROOT"
[ -x "$WRAPUP_DIR/backup.sh" ] && [ -x "$WRAPUP_DIR/start-stack.sh" ] && [ -x "$WRAPUP_DIR/rollback.sh" ] \
  && [ -x "$WRAPUP_DIR/halt-check.sh" ] && [ -x "$WRAPUP_DIR/verify.sh" ] \
  || die "找不到 wrapup 子脚本（$WRAPUP_DIR）"

# 确保永不调用 down.sh / down -v
assert_no_down_v() {
  # 给测试和自检：本脚本源码与本次参数不得安排 down -v
  :
}

mode=dry-run
[ "$APPLY" -eq 1 ] && mode=apply
log "模式=$mode。仓库 $ROOT。不 down -v，保留数据卷。"
log "将：git fetch origin → 在 $ROOT/.worktrees/<origin/main 短哈希> 新建 worktree → backup → 新树 start-stack（迁移/重建/启动）→ halt-check（不 repair）→ verify；失败则 rollback。"
log "不调用麦蕊、不解除 HALT、不改外网出口、不跑 master-bootstrap、不导入正式卡。"

if [ "$APPLY" -eq 0 ]; then
  if git -C "$ROOT" rev-parse --verify -q origin/main >/dev/null; then
    local_main="$(git -C "$ROOT" rev-parse origin/main)"
    short="$(git -C "$ROOT" rev-parse --short=7 origin/main)"
    log "dry-run：当前本地 origin/main=$local_main ；--apply 时仍以 fetch 后的原点为准。计划 worktree=$ROOT/.worktrees/$short"
  else
    log "dry-run：本地还没有 origin/main，--apply 时会先 fetch 再解析短哈希。"
  fi
  log "dry-run：将调用（不加写入）："
  log "  $WRAPUP_DIR/backup.sh ${PASSTHRU[*]-}"
  log "  <新工作树>/deploy/scripts/wrapup/start-stack.sh --apply --backup-dir <DEST>"
  log "  <新工作树>/deploy/scripts/wrapup/halt-check.sh（无 --repair）"
  log "  <新工作树>/deploy/scripts/wrapup/verify.sh ${PASSTHRU[*]-}"
  log "失败则：$WRAPUP_DIR/rollback.sh --apply --backup-dir <DEST>"
  # 仍把子脚本的 dry-run 跑一遍（不传 --apply），便于看到 backup/start 计划
  "$WRAPUP_DIR/backup.sh" ${PASSTHRU[@]+"${PASSTHRU[@]}"} || die "backup.sh dry-run 失败"
  "$WRAPUP_DIR/start-stack.sh" ${PASSTHRU[@]+"${PASSTHRU[@]}"} || die "start-stack.sh dry-run 失败"
  log "dry-run 结束，未 fetch、未建 worktree、未写备份、未启栈。"
  exit 0
fi

# 回滚目标必须是同步前的原工作区 HEAD，不能用 wrapup 默认的旧 team-b 头。
ORIGINAL_HEAD="$(git -C "$ROOT" rev-parse HEAD)"
log "同步前 HEAD=$ORIGINAL_HEAD"

log "apply: git fetch origin"
git -C "$ROOT" fetch origin
git -C "$ROOT" rev-parse --verify origin/main >/dev/null 2>&1 || die "fetch 后没有 origin/main"
TARGET="$(git -C "$ROOT" rev-parse origin/main)"
SHORT="$(git -C "$ROOT" rev-parse --short=7 origin/main)"
WT="$ROOT/.worktrees/$SHORT"
log "目标 origin/main=$TARGET 短哈希=$SHORT 工作树=$WT"

if [ -e "$WT" ]; then
  if git -C "$WT" rev-parse --is-inside-work-tree >/dev/null 2>&1 \
    && [ "$(git -C "$WT" rev-parse HEAD)" = "$TARGET" ]; then
    log "工作树已存在且 HEAD 已是 $TARGET，复用。"
  else
    die "路径已存在但不是指向 $TARGET 的 worktree：$WT"
  fi
else
  mkdir -p "$ROOT/.worktrees"
  log "新建 worktree（detach，不移动已有分支）"
  git -C "$ROOT" worktree add --detach "$WT" "$TARGET"
fi

# 沿用原树 deploy/env（含项目名与卷前缀），不打印 .env 内容
if [ -e "$ROOT/deploy/env" ] && [ ! -e "$WT/deploy/env" ]; then
  ln -s "$ROOT/deploy/env" "$WT/deploy/env"
  log "已把新工作树 deploy/env 符号链接到原仓库（不打印内容，以沿用 COMPOSE_PROJECT_NAME / AIA_VOLUME_PREFIX）"
fi

log "先备份"
# start_args 给 backup/start-stack；rollback_args 不含 --db
# （rollback.sh 的 --db 表示恢复到的新库名，不能沿用源库名）。
# 强制 --rollback-head 为同步前 HEAD。
start_args=()
rollback_args=()
skip=0
pending_db=0
for a in "${PASSTHRU[@]}"; do
  if [ "$skip" -eq 1 ]; then
    skip=0
    continue
  fi
  case "$a" in
    --apply) continue ;;
    --backup-dir|--out-dir|--rollback-head) skip=1; continue ;;
    --db)
      pending_db=1
      start_args+=("$a")
      continue
      ;;
    *)
      if [ "$pending_db" -eq 1 ]; then
        start_args+=("$a")
        pending_db=0
      else
        start_args+=("$a")
        rollback_args+=("$a")
      fi
      ;;
  esac
done

# 若用户传了 --backup-dir，仍转给 backup（父目录）；本轮 DEST 以 stdout 为准。
backup_in=()
skip=0
for a in "${PASSTHRU[@]}"; do
  if [ "$skip" -eq 1 ]; then
    backup_in+=("$a")
    skip=0
    continue
  fi
  case "$a" in
    --apply|--rollback-head) 
      if [ "$a" = "--rollback-head" ]; then skip=1; fi
      continue
      ;;
    --backup-dir|--out-dir) backup_in+=("$a"); skip=1; continue ;;
    *)
      ;;
  esac
done

DEST="$("$WRAPUP_DIR/backup.sh" --apply --rollback-head "$ORIGINAL_HEAD" ${backup_in[@]+"${backup_in[@]}"} ${start_args[@]+"${start_args[@]}"} )"
DEST="$(printf '%s\n' "$DEST" | tail -n 1)"
[ -n "$DEST" ] || die "backup.sh 未在标准输出打印本轮 DEST"
case "$DEST" in
  /*) ;;
  *) die "backup.sh 打印的 DEST 不是绝对路径：$DEST" ;;
esac
log "本轮 DEST=$DEST"

rolled=0
rollback_once() {
  if [ "$rolled" -eq 1 ]; then
    return 0
  fi
  rolled=1
  log "失败，开始 rollback.sh --apply --backup-dir $DEST --rollback-head $ORIGINAL_HEAD（不 down -v，不把源库 --db 传给 rollback）"
  "$WRAPUP_DIR/rollback.sh" --apply --backup-dir "$DEST" --rollback-head "$ORIGINAL_HEAD" \
    ${rollback_args[@]+"${rollback_args[@]}"} \
    || log "rollback.sh 也失败；停手，不要 down -v，必须问编排者。"
}

# 不用 if !( set -e; ... )：条件上下文会关掉 set -e，前面的失败会被后面的成功盖掉。
run_new_stack() {
  "$WT/deploy/scripts/wrapup/start-stack.sh" --apply --backup-dir "$DEST" ${start_args[@]+"${start_args[@]}"} || return 1
  "$WT/deploy/scripts/wrapup/halt-check.sh" ${rollback_args[@]+"${rollback_args[@]}"} || return 1
  "$WT/deploy/scripts/wrapup/verify.sh" --apply --backup-dir "$DEST" ${start_args[@]+"${start_args[@]}"} || return 1
  return 0
}
if ! run_new_stack; then
  rollback_once
  die "启动或校验失败，已尝试回滚。新工作树仍在 $WT，数据卷未删。"
fi

log "同步完成。新工作树 $WT HEAD=$(git -C "$WT" rev-parse HEAD)。请在该树使用原项目名与卷前缀。"

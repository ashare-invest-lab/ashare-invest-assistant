#!/bin/bash
# 自动合并队列（编排者 11-14，用户 t1130u：DS 不该干等审合）。每 3 分钟一轮，无模型参与。
# 条件：当前 head 获白名单「可合入 @短哈希」批准；净增 >800 须有有效豁免；base=main；每个检查名至少一次 SUCCESS 且无在跑（push 全历史扫描红已裁定豁免）；
# 无敏感路径；main 最新 CI 已完成且绿、且对应当前 main。一次只合一个，合完等 main CI 跑完再合下一个。
export TZ=America/Denver

RT="${MQ_RT:-/workspace/team/runtime}"
mkdir -p "$RT"
L="$RT/mergeq.log"
HB="$RT/mergeq.heartbeat"
MF="$RT/mergeq.mainfix"
GH_TIMEOUT="${MQ_GH_TIMEOUT:-90}"
MQ_SLEEP="${MQ_SLEEP:-180}"
MQ_ONCE="${MQ_ONCE:-0}"
WAIT_LOG_MIN="${MQ_WAIT_LOG_MIN:-30}"
GAP_WARN="${MQ_GAP_WARN:-300}"

exec 9>"$RT/mergeq.lock"
if ! flock -n 9; then
  printf '%s 已有实例，退出\n' "$(date '+%F %T')" >>"$L"
  exit 0
fi

GH_REPO="${GH_REPO:?请通过环境变量 GH_REPO 指定仓库}"
R="$GH_REPO"
last=""
wait_since=0
wait_last_log=0
hb_stage=""
hb_since=0
BAD='(\.env|secret|cred|\.key$|\.pem$|\.p12$|\.csv$|\.xlsx?$|broker_statement|holding|licen[cs]e.*\.(json|ya?ml)$)'

is_timeout_rc(){ [ "$1" -eq 124 ] || [ "$1" -eq 137 ]; }

log_gh_result(){
  local stage="$1" rc="$2" errf="$3" errline suffix=""
  if is_timeout_rc "$rc"; then
    printf '%s GH-TIMEOUT %s rc=%s\n' "$(date '+%F %T')" "$stage" "$rc" >>"$L"
  elif [ "$rc" -ne 0 ] && ! { [ "$rc" -eq 1 ] && [[ "$stage" == 合并门禁* ]]; }; then
    # 门禁 rc=1 是正常拒绝（merge-approved.sh deny），不记 GH-FAIL
    errline=$(sed -n '1p' "$errf" 2>/dev/null | tr -d '\r\n' | cut -c1-200)
    [ -n "$errline" ] && suffix=" $errline"
    printf '%s GH-FAIL %s rc=%s%s\n' "$(date '+%F %T')" "$stage" "$rc" "$suffix" >>"$L"
  fi
}

run_timed(){
  local stage="$1"; shift
  local errf rc
  errf=$(mktemp "${TMPDIR:-/tmp}/mergeq-gh.XXXXXX")
  timeout -k 10 "$GH_TIMEOUT" "$@" 2>"$errf"
  rc=$?
  log_gh_result "$stage" "$rc" "$errf"
  rm -f "$errf"
  return "$rc"
}

run_timed_log(){
  local stage="$1"; shift
  local errf rc
  errf=$(mktemp "${TMPDIR:-/tmp}/mergeq-gh.XXXXXX")
  timeout -k 10 "$GH_TIMEOUT" "$@" 2>"$errf"
  rc=$?
  cat "$errf" >>"$L"
  log_gh_result "$stage" "$rc" "$errf"
  rm -f "$errf"
  return "$rc"
}

hb(){
  local stage="$1"; local explanation="${2:-}"; local now
  now=$(date +%s)
  if [ "$stage" != "$hb_stage" ]; then
    hb_stage="$stage"
    hb_since="$now"
  fi
  printf '%s pid=%s 阶段=%s 说明=%s 开始于=%s\n' \
    "$(date '+%F %T')" "$$" "$stage" "$explanation" "$hb_since" >"$HB"
}

note(){
  local reason="$1" now elapsed mins
  now=$(date +%s)
  if [ "$reason" != "$last" ]; then
    printf '%s 状态：%s\n' "$(date '+%F %T')" "$reason" >>"$L"
    last="$reason"
    wait_since="$now"
    wait_last_log="$now"
  else
    elapsed=$((now - wait_since))
    if [ "$elapsed" -ge $((WAIT_LOG_MIN * 60)) ] && [ $((now - wait_last_log)) -ge 1800 ]; then
      mins=$((elapsed / 60))
      printf '%s 仍在：%s（已 %s 分钟）\n' "$(date '+%F %T')" "$reason" "$mins" >>"$L"
      wait_last_log="$now"
    fi
  fi
}

end_round(){
  local stage="${1:-sleep}" explanation="${2:-}";
  hb "$stage" "$explanation"
  sleep "$MQ_SLEEP"
  [ "$MQ_ONCE" = 1 ] && exit 0
}

previous_round=0
while true; do
  round_start=$(date +%s)
  if [ "$previous_round" -gt 0 ]; then
    gap=$((round_start - previous_round))
    if [ "$gap" -gt $((MQ_SLEEP + GAP_WARN)) ]; then
      printf '%s GAP 上一轮 %s 到本轮 %s 间隔 %s 秒（进程被挂起或阻塞）\n' \
        "$(date '+%F %T')" "$(date -d "@$previous_round" '+%F %T')" \
        "$(date -d "@$round_start" '+%F %T')" "$gap" >>"$L"
    fi
  fi
  previous_round="$round_start"
  hb "轮开始" "轮开始=$round_start"
  if [ -f "$RT/mergeq.STOP" ]; then
    printf '%s STOP\n' "$(date '+%F %T')" >>"$L"
    exit 0
  fi

  hb "取 main" "仓库=$R"
  main=$(run_timed "取 main" gh api "repos/$R/commits/main" -q .sha)
  rc=$?
  if is_timeout_rc "$rc"; then
    end_round "sleep" "GH-TIMEOUT 取 main"
    continue
  fi
  if [ "$rc" -ne 0 ]; then
    end_round "sleep" "GH-FAIL 取 main rc=$rc"
    continue
  fi
  if ! [[ "$main" =~ ^[0-9a-fA-F]{40}$ ]]; then
    printf '%s GH-FAIL 取 main rc=0 空/无效\n' "$(date '+%F %T')" >>"$L"
    end_round "sleep" "GH-FAIL 取 main rc=0"
    continue
  fi

  hb "取 run" "main=${main:0:7}"
  run=$(run_timed "取 run" gh run list -R "$R" --branch main --workflow ci --limit 1 --json headSha,status,conclusion -q '.[0]|.headSha+" "+.status+" "+(.conclusion//"")')
  rc=$?
  if is_timeout_rc "$rc"; then
    end_round "sleep" "GH-TIMEOUT 取 run"
    continue
  fi
  if [ "$rc" -ne 0 ]; then
    end_round "sleep" "GH-FAIL 取 run rc=$rc"
    continue
  fi

  fixonly=0
  if [ "$run" != "$main completed success" ]; then
    if [[ "$run" == "$main completed "* ]]; then
      fixonly=1
      note "main CI 红（$run），只放行修主线单"
    else
      note "等 main CI（main=${main:0:7} run=${run:-取不到}）"
      end_round "等 main CI" "main=${main:0:7} run=${run:-取不到}"
      continue
    fi
  fi

  hb "列 PR" "main=${main:0:7}"
  open_raw=$(run_timed "列 PR" gh pr list -R "$R" --state open --base main --limit 50 --json number -q '.[].number')
  rc=$?
  if is_timeout_rc "$rc"; then
    end_round "sleep" "GH-TIMEOUT 列 PR"
    continue
  fi
  if [ "$rc" -ne 0 ]; then
    end_round "sleep" "GH-FAIL 列 PR rc=$rc"
    continue
  fi
  open=$(printf '%s\n' "$open_raw" | sort -n)

  # 优先表（编排者 11-15）：runtime/mergeq.priority 每行一个 PR 号，排在最前；其余按号升序
  pri=$( [ -f "$RT/mergeq.priority" ] && grep -Eo '^[0-9]+' "$RT/mergeq.priority" | while read -r p; do echo "$open" | grep -qx "$p" && echo "$p"; done )
  merged=0
  round_abort=0
  round_abort_kind=""
  round_abort_stage=""
  skipped=""
  for n in $pri $(echo "$open" | grep -vxF -f <(echo "${pri:-__none__}")); do
    hb "检查 PR #$n" "main=${main:0:7}"
    j=$(run_timed "检查 PR #$n" gh pr view "$n" -R "$R" --json headRefOid,headRefName,baseRefName,isDraft,comments,statusCheckRollup,files,mergeable)
    rc=$?
    if is_timeout_rc "$rc"; then
      round_abort=1
      round_abort_kind="GH-TIMEOUT"
      round_abort_stage="检查 PR #$n"
      break
    fi
    if [ "$rc" -ne 0 ]; then
      round_abort=1
      round_abort_kind="GH-FAIL"
      round_abort_stage="检查 PR #$n"
      break
    fi
    if [ "$fixonly" = 1 ] && ! { echo "$j" | jq -r .headRefName | grep -qi 'main-fix' || grep -qx "$n" "$MF" 2>/dev/null; }; then continue; fi
    ok=$(echo "$j" | jq -r '
      (.baseRefName=="main") and (.isDraft|not) and (.mergeable!="CONFLICTING") and
      ((.statusCheckRollup|length)>0) and
      ([.statusCheckRollup[]|{n:.name,c:(.conclusion//.status)}]|group_by(.n)|all((any(.[];.c=="SUCCESS") or all(.[];.c=="SKIPPED" or .c=="NEUTRAL")) and all(.[];.c!="IN_PROGRESS" and .c!="QUEUED" and .c!="PENDING") and ((.[0].n|test("gitleaks";"i")) or all(.[];.c!="FAILURE" and .c!="CANCELLED" and .c!="TIMED_OUT"))))')
    [ "$ok" = "true" ] || { skipped="$skipped #$n"; continue; }
    if echo "$j" | jq -r '.files[].path' | grep -Eiq "$BAD"; then
      printf '%s #%s 敏感路径，跳过待人工\n' "$(date '+%F %T')" "$n" >>"$L"
      continue
    fi
    hb "合并前" "PR=#$n"
    sha=$(run_timed_log "合并门禁 #$n" bash "$(dirname "$0")/merge-approved.sh" "$n")
    rc=$?
    if is_timeout_rc "$rc"; then
      round_abort=1
      round_abort_kind="GH-TIMEOUT"
      round_abort_stage="合并门禁 #$n"
      break
    fi
    if [ "$rc" -eq 1 ]; then
      printf '%s #%s 合并门禁拒绝（批准或净增行数），跳过\n' "$(date '+%F %T')" "$n" >>"$L"
      continue
    fi
    if [ "$rc" -ne 0 ]; then
      round_abort=1
      round_abort_kind="GH-FAIL"
      round_abort_stage="合并门禁 #$n"
      break
    fi
    hb "合并前" "PR=#$n head=${sha:0:7}"
    merge_output=$(run_timed_log "合并 #$n" gh pr merge "$n" -R "$R" --merge --match-head-commit "$sha")
    rc=$?
    [ -n "$merge_output" ] && printf '%s\n' "$merge_output" >>"$L"
    if is_timeout_rc "$rc"; then
      round_abort=1
      round_abort_kind="GH-TIMEOUT"
      round_abort_stage="合并 #$n"
      break
    fi
    if [ "$rc" -eq 0 ]; then
      mc_raw=$(run_timed "合并后查询 #$n" gh pr view "$n" -R "$R" --json mergeCommit -q .mergeCommit.oid)
      rc_view=$?
      mc=""
      [ "$rc_view" -eq 0 ] && mc=$(printf '%s' "$mc_raw" | cut -c1-7)
      [ -n "$mc" ] || mc="未知"
      run_timed "合并后评论 #$n" gh pr comment "$n" -R "$R" -b "已合入 $mc（自动合并队列）" >/dev/null
      printf '%s MERGED #%s -> %s\n' "$(date '+%F %T')" "$n" "$mc" >>"$L"
      merged=1
    else
      printf '%s #%s merge 命令失败\n' "$(date '+%F %T')" "$n" >>"$L"
    fi
    break
  done

  if [ "$round_abort" = 1 ]; then
    end_round "sleep" "本轮因 $round_abort_kind 放弃（$round_abort_stage）"
    continue
  fi
  [ "$merged" = 1 ] || note "本轮无可合（fixonly=$fixonly，检查未过 $(echo "$skipped" | wc -w) 个）"
  end_round "sleep" "本轮结束 merged=$merged"
done


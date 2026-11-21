#!/bin/bash
# 合并队列卡单早报（用户 t1218u 同意，11-14 23:30 MST）：「可合入」评论超过 30 分钟仍未合的 open PR，逐个写明卡点。
export TZ=America/Denver

RT="${MQ_RT:-/workspace/team/runtime}"
GH_REPO="${GH_REPO:-ashare-invest-lab/ashare-invest-assistant}"
R="$GH_REPO"
GH_TIMEOUT="${MQ_GH_TIMEOUT:-90}"
now=$(date +%s)
hb="$RT/mergeq.heartbeat"
stall_log="$RT/mergeq.log"

is_timeout_rc(){ [ "$1" -eq 124 ] || [ "$1" -eq 137 ]; }
run_timed(){
  local stage="$1"; shift
  timeout -k 10 "$GH_TIMEOUT" "$@" 2>/dev/null
  local rc=$?
  if is_timeout_rc "$rc"; then
    printf '%s GH-TIMEOUT %s rc=%s\n' "$(date '+%F %T')" "$stage" "$rc" >>"$stall_log"
  fi
  return "$rc"
}

hb_line=""
phase="未知"
hb_desc=""
hb_since=0
if [ -f "$hb" ]; then
  hb_line=$(tail -n 1 "$hb")
  phase=$(printf '%s\n' "$hb_line" | sed -n 's/.*阶段=\(.*\) 说明=.*/\1/p')
  hb_desc=$(printf '%s\n' "$hb_line" | sed -n 's/.*说明=\(.*\)/\1/p')
  hb_since=$(printf '%s\n' "$hb_line" | sed -n 's/.*开始于=\([0-9][0-9]*\).*/\1/p')
  [ -n "$hb_since" ] || hb_since=0
fi

hb_age=999999
[ -f "$hb" ] && hb_age=$((now - $(stat -c %Y "$hb")))
if [ ! -f "$hb" ] || [ "$hb_age" -gt 600 ]; then
  echo "MERGEQ-HEARTBEAT 超 10 分钟没心跳：查进程或手动合"
  pids=$(pgrep -f '(^|/)mergeq\.sh([[:space:]]|$)' || true)
  if [ -z "$pids" ]; then
    echo "MERGEQ-DEAD"
  else
    for pid in $pids; do
      [ "$pid" = "$$" ] && continue
      proc=$(ps -p "$pid" -o pid=,etimes=,args= 2>/dev/null)
      [ -n "$proc" ] && echo "MERGEQ-PROCESS $proc"
      children=$(ps --ppid "$pid" -o pid=,etimes=,args= 2>/dev/null)
      if [ -n "$children" ]; then
        while IFS= read -r child; do echo "MERGEQ-CHILD $child"; done <<<"$children"
      else
        echo "MERGEQ-CHILD none pid=$pid"
      fi
    done
  fi
  echo "MERGEQ-PHASE ${phase:-未知}"
fi

main_sha=$(run_timed "取 main" gh api "repos/$R/commits/main" -q .sha)
main_rc=$?
run=""
if ! is_timeout_rc "$main_rc"; then
  run=$(run_timed "取 run" gh run list -R "$R" --branch main --workflow ci --limit 1 --json headSha,status,conclusion -q '.[0]|.headSha+" "+.status+" "+(.conclusion//"")')
  run_rc=$?
else
  run_rc=$main_rc
fi

if [ "$hb_age" -le 600 ] && [ "$phase" = "等 main CI" ] && [ "$run" = "$main_sha completed success" ] && [ "$hb_since" -gt 0 ] && [ $((now - hb_since)) -gt 600 ]; then
  current_short=${main_sha:0:7}
  if [[ "$hb_desc" == *"main=$current_short"* ]]; then
    echo "MERGEQ-FAKE-WAIT main CI 已绿且 main=$current_short，仍在等 main CI 超 10 分钟"
  fi
fi

list_json=$(run_timed "列 PR" gh pr list -R "$R" --state open --base main --limit 50 --json number,isDraft,mergeable,comments,statusCheckRollup,files)
list_rc=$?
if is_timeout_rc "$list_rc"; then
  exit 0
fi
printf '%s\n' "$list_json" | jq -r --argjson now "$now" --arg mainok "$([ "$run" = "$main_sha completed success" ] && echo 1 || echo 0)" '
 .[] | ([.comments[]|select(.body|test("可合入"))|.createdAt|fromdateiso8601]|min) as $t | select($t!=null and ($now-$t)>1800) |
 ([.statusCheckRollup[]|{n:.name,c:(.conclusion//.status)}]|group_by(.n)) as $g |
 ( if .isDraft then "草稿"
   elif .mergeable=="CONFLICTING" then "有冲突"
   elif ([.files[].path|select(test("(\\.env|secret|cred|\\.key$|\\.pem$|\\.p12$|\\.csv$|\\.xlsx?$|broker_statement|holding)";"i"))]|length>0) then "敏感路径待人工"
   elif ($g|any(any(.[];.c=="IN_PROGRESS" or .c=="QUEUED" or .c=="PENDING"))) then "PR 检查在跑"
   elif ($g|any((.[0].n|test("gitleaks";"i")|not) and any(.[];.c=="FAILURE" or .c=="CANCELLED" or .c=="TIMED_OUT"))) then "PR 检查失败"
   elif $mainok=="0" then "main CI 未绿或在跑"
   else "条件看似满足，查 mergeq.log" end ) as $why |
 "STALL #\(.number) 可合入已 \((($now-$t)/60)|floor) 分钟：\($why)"'


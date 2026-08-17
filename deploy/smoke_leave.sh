#!/usr/bin/env bash
# 蓝队业务管理系统 · 考勤（休假/外勤）生产冒烟
# 验证闭环：员工申请 → 主管批准 → 定时生效（用户状态自动切休假/外勤）→ 到期自动恢复在职 → 申请完成
#
# 用法：bash deploy/smoke_leave.sh [base_url]  默认 https://localhost
# 说明：把申请的 start_at/end_at 直接改成过去来模拟「时间到点」，再手动触发切换服务，
#      不等待真实轮询（生产轮询间隔 5 分钟），保证确定性。
set -uo pipefail

BASE="${1:-https://localhost}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE="docker compose -p blueteam --env-file $ROOT/deploy/.env.prod -f $ROOT/deploy/docker-compose.prod.yml"
PSQL() { $COMPOSE exec -T postgres psql -U blueteam -d blueteam -t -A -c "$1"; }

PASS=0; FAIL=0
ok()  { PASS=$((PASS+1)); echo "  ✓ $1"; }
bad() { FAIL=$((FAIL+1)); echo "  ✗ $1"; }
check() { if eval "$2"; then ok "$1"; else bad "$1"; fi }

jcurl() { curl -kfsS -H 'Content-Type: application/json' -H 'X-Requested-With: XMLHttpRequest' "$@"; }

get_captcha() {
  local cap cap_id code
  cap="$(jcurl "$BASE/api/v1/auth/captcha")"
  cap_id="$(echo "$cap" | grep -oE '"captcha_id":"[a-f0-9]+"' | head -1 | cut -d'"' -f4)"
  code="$($COMPOSE exec -T redis redis-cli GET "captcha:$cap_id" 2>/dev/null | tr -d '\r\n')"
  printf '%s %s' "$cap_id" "$code"
}

login() {
  local u="$1" cid code resp
  read -r cid code <<< "$(get_captcha)"
  resp="$(jcurl -X POST "$BASE/api/v1/auth/login" \
    -d "{\"username\":\"$u\",\"password\":\"Bt@123456\",\"captcha_id\":\"$cid\",\"captcha_code\":\"$code\"}")"
  echo "$resp" | grep -oE '"access_token":"[^"]+"' | head -1 | cut -d'"' -f4
}

trigger_switch() {
  $COMPOSE exec -T backend python -c "
import asyncio
from app.services.leave_status import _switch_due_leave_statuses
from app.db.session import AsyncSessionLocal
async def main():
    async with AsyncSessionLocal() as s:
        started, ended = await _switch_due_leave_statuses(s)
        print(started, ended)
asyncio.run(main())
" 2>/dev/null | tr -d '\r\n'
}

# 未来时间窗（UTC ISO，避开毫秒与重叠）
START_ISO="$(date -u -d '+1 day' +"%Y-%m-%dT%H:00:00Z")"
END_ISO="$(date -u -d '+2 days' +"%Y-%m-%dT%H:00:00Z")"

echo "== 考勤闭环：申请 → 审批 → 自动生效 → 到期恢复 =="
ANALYST_T="$(login analyst01)"
check "analyst01 登录拿到 token" "[ -n \"$ANALYST_T\" ]"
MANAGER_T="$(login manager01)"
check "manager01 登录拿到 token" "[ -n \"$MANAGER_T\" ]"

printf '{"leave_type":"on_leave","start_at":"%s","end_at":"%s","reason":"生产考勤冒烟测试"}' "$START_ISO" "$END_ISO" > "$ROOT/deploy/smoke_leave.json"
create="$(jcurl -X POST -H "Authorization: Bearer $ANALYST_T" "$BASE/api/v1/leaves" -d @"$ROOT/deploy/smoke_leave.json")"
check "提交休假申请成功" "echo '$create' | grep -qE '\"code\":0'"
LID="$(echo "$create" | grep -oE '"id":[0-9]+' | head -1 | grep -oE '[0-9]+')"
check "拿到申请 id" "[ -n \"$LID\" ]"

review="$(jcurl -H "Authorization: Bearer $MANAGER_T" "$BASE/api/v1/leaves?status=pending")"
check "审批中心可见该待审批申请" "echo '$review' | grep -q \"\\\"id\\\":$LID\""

approve="$(jcurl -X POST -H "Authorization: Bearer $MANAGER_T" "$BASE/api/v1/leaves/$LID/approve" -d '{}')"
check "主管批准成功" "echo '$approve' | grep -qE '\"status\":\"approved\"'"

# 模拟开始时间到达 → 触发定时切换
PSQL "UPDATE leave_requests SET start_at = now() - interval '1 hour' WHERE id = $LID;" >/dev/null 2>&1
sw="$(trigger_switch)"
check "切换服务生效 1 条" "echo '$sw' | grep -qE '^1 0\$'"
user_st="$(PSQL "SELECT status FROM users WHERE username='analyst01';" | tr -d '\r\n ')"
check "analyst01 状态已自动切为休假" "[ \"$user_st\" = on_leave ]"
lr_st="$(PSQL "SELECT status FROM leave_requests WHERE id = $LID;" | tr -d '\r\n ')"
check "申请状态为生效中" "[ \"$lr_st\" = in_progress ]"

# 模拟结束时间到达 → 触发定时切换
PSQL "UPDATE leave_requests SET end_at = now() - interval '30 minutes' WHERE id = $LID;" >/dev/null 2>&1
sw2="$(trigger_switch)"
check "切换服务恢复 1 条" "echo '$sw2' | grep -qE '^0 1\$'"
user_st2="$(PSQL "SELECT status FROM users WHERE username='analyst01';" | tr -d '\r\n ')"
check "analyst01 状态已自动恢复在职" "[ \"$user_st2\" = active ]"
lr_st2="$(PSQL "SELECT status FROM leave_requests WHERE id = $LID;" | tr -d '\r\n ')"
check "申请状态为已完成" "[ \"$lr_st2\" = completed ]"

mine="$(jcurl -H "Authorization: Bearer $ANALYST_T" "$BASE/api/v1/leaves/mine")"
check "我的申请列表中该条已完成" "echo '$mine' | grep -q \"\\\"id\\\":$LID\" && echo '$mine' | grep -q '\"status\":\"completed\"'"

# 清理：删除测试申请（leave_requests 无防删除规则）
PSQL "DELETE FROM leave_requests WHERE id = $LID;" >/dev/null 2>&1
left="$(PSQL "SELECT count(*) FROM leave_requests WHERE id = $LID;" | tr -d '\r\n ')"
check "测试申请已清理" "[ \"$left\" = 0 ]"

rm -f "$ROOT/deploy/smoke_leave.json"
echo ""
echo "== 结果：$PASS 通过 / $FAIL 失败 =="
[ "$FAIL" = 0 ] && echo "考勤生产冒烟通过 ✅" || echo "存在失败项，请检查 ❌"
exit "$FAIL"

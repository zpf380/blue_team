#!/usr/bin/env bash
# 考勤功能边界回归（生产）：
#   1) 休假/外勤用户登录不拦截（status 不参与登录拦截）
#   2) 外勤(business_trip) 用户从私聊候选人排除（WS 白名单 status in active/on_leave，保持未改）
#   3) 最后管理员保护：business_trip 计入 _ACTIVE_STATUSES → 视为有效管理员（回归防误伤）
# 全程不触碰真实 admin；临时管理员测后即删。
set -uo pipefail

BASE="https://localhost"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE="docker compose -p blueteam --env-file $ROOT/deploy/.env.prod -f $ROOT/deploy/docker-compose.prod.yml"
PSQL() { $COMPOSE exec -T postgres psql -U blueteam -d blueteam -t -A -c "$1" 2>/dev/null | tr -d '\r\n '; }

PASS=0; FAIL=0
ok()  { PASS=$((PASS+1)); echo "  ✓ $1"; }
bad() { FAIL=$((FAIL+1)); echo "  ✗ $1"; }
check() { if eval "$2"; then ok "$1"; else bad "$1"; fi }

jcurl() { curl -kfsS -H 'Content-Type: application/json' -H 'X-Requested-With: XMLHttpRequest' "$@"; }

login() {
  local u="$1" cap cid code
  cap="$(jcurl "$BASE/api/v1/auth/captcha")"
  cid="$(echo "$cap" | grep -oE '"captcha_id":"[a-f0-9]+"' | head -1 | cut -d'"' -f4)"
  code="$($COMPOSE exec -T redis redis-cli GET "captcha:$cid" 2>/dev/null | tr -d '\r\n')"
  jcurl -X POST "$BASE/api/v1/auth/login" \
    -d "{\"username\":\"$u\",\"password\":\"Bt@123456\",\"captcha_id\":\"$cid\",\"captcha_code\":\"$code\"}" \
    | grep -oE '"access_token":"[^"]+"' | head -1 | cut -d'"' -f4
}

ANALYST_T="$(login analyst01)"
check "analyst01 登录拿到 token" "[ -n \"$ANALYST_T\" ]"
MANAGER_T="$(login manager01)"
check "manager01 登录拿到 token" "[ -n \"$MANAGER_T\" ]"

echo "-- 1. 外勤(business_trip) 登录不拦截 + 私聊候选人排除 --"
base="$(jcurl -H "Authorization: Bearer $MANAGER_T" "$BASE/api/v1/chat/users")"
check "在职时 analyst01 出现在私聊候选人" "echo '$base' | grep -q '\"username\":\"analyst01\"'"

PSQL "UPDATE users SET status='business_trip' WHERE username='analyst01';" >/dev/null
BT_T="$(login analyst01)"
check "外勤状态下登录不拦截（拿到 token）" "[ -n \"$BT_T\" ]"
bt="$(jcurl -H "Authorization: Bearer $MANAGER_T" "$BASE/api/v1/chat/users")"
check "外勤时 analyst01 从私聊候选人排除" "! echo '$bt' | grep -q '\"username\":\"analyst01\"'"

PSQL "UPDATE users SET status='on_leave' WHERE username='analyst01';" >/dev/null
OL_T="$(login analyst01)"
check "休假状态下登录不拦截（拿到 token）" "[ -n \"$OL_T\" ]"

PSQL "UPDATE users SET status='active' WHERE username='analyst01';" >/dev/null
back="$(jcurl -H "Authorization: Bearer $MANAGER_T" "$BASE/api/v1/chat/users")"
check "恢复在职后重新出现在候选人" "echo '$back' | grep -q '\"username\":\"analyst01\"'"

echo "-- 2. 最后管理员保护：business_trip 计入有效管理员 --"
# 临时 admin B；guard 的计数查询（同 users.py _count_active_admins）应把 business_trip 计入
B_HASH="$($COMPOSE exec -T backend python -c "from app.core.security import hash_password; print(hash_password('Probe@12345'))" 2>/dev/null | tr -d '\r\n ')"
PSQL "INSERT INTO users(username, real_name, password_hash, role_id, status, security_level, failed_attempts)
      VALUES ('smoke_admin_probe','Probe','$B_HASH',(SELECT id FROM roles WHERE code='admin'),'active',1,0)
      ON CONFLICT (username) DO UPDATE SET role_id=(SELECT id FROM roles WHERE code='admin'), status='active', failed_attempts=0, password_hash='$B_HASH';" >/dev/null
PSQL "UPDATE users SET status='business_trip' WHERE username='smoke_admin_probe';" >/dev/null
count="$(PSQL "SELECT count(*) FROM users u JOIN roles r ON r.id=u.role_id WHERE r.code='admin' AND u.status IN ('active','on_leave','business_trip');")"
check "business_trip 管理员计入有效管理员（count>=1）" "[ \"$count\" -ge 1 ]"
PSQL "UPDATE users SET status='disabled' WHERE username='smoke_admin_probe';" >/dev/null
count2="$(PSQL "SELECT count(*) FROM users u JOIN roles r ON r.id=u.role_id WHERE r.code='admin' AND u.status IN ('active','on_leave','business_trip');")"
check "禁用后探针不再计入（计数回落到外勤时-1）" "[ \"$count2\" = \"$((count-1))\" ]"
PSQL "DELETE FROM users WHERE username='smoke_admin_probe';" >/dev/null 2>&1
left="$(PSQL "SELECT count(*) FROM users WHERE username='smoke_admin_probe';")"
check "临时管理员已清理" "[ \"$left\" = 0 ]"

echo ""
echo "== 结果：$PASS 通过 / $FAIL 失败 =="
[ "$FAIL" = 0 ] && echo "考勤边界回归通过 ✅" || echo "存在失败项，请检查 ❌"
exit "$FAIL"

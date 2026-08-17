#!/usr/bin/env bash
# 设备巡检 + 数据范围生产冒烟：
#   1) 容器内执行一轮真实 nmap 巡检（patrol_all_subnets）→ device_patrols 落行、设备状态被刷新
#   2) GET /monitor/patrols 可见，dept 角色（analyst→攻防实验室）仅见本部门子网巡检
#   3) 告警/扫描报告部门数据范围：analyst 仅见本部门设备关联记录，全局/跨部门不可见
#   4) 设备列表响应带 offline_since 字段
# 说明：巡检会按特征真实刷新设备状态（docker 内网无主机响应 → 多为 offline），
#      这是功能的预期行为；临时告警/报告测后即删，巡检行保留供追溯。
set -uo pipefail

BASE="https://localhost"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE="docker compose -p blueteam --env-file $ROOT/deploy/.env.prod -f $ROOT/deploy/docker-compose.prod.yml"
PSQL() { $COMPOSE exec -T postgres psql -U blueteam -d blueteam -t -A -c "$1" 2>/dev/null | tr -d '\r\n '; }
# INSERT...RETURNING 输出含 "id"+"INSERT 0 1" 两行，取首个整数作为返回 id
ID() { $COMPOSE exec -T postgres psql -U blueteam -d blueteam -t -A -q -c "$1" 2>/dev/null | grep -oE '[0-9]+' | head -1; }

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

MANAGER_T="$(login manager01)"
check "manager01 登录拿到 token" "[ -n \"$MANAGER_T\" ]"
ANALYST_T="$(login analyst01)"
check "analyst01 登录拿到 token" "[ -n \"$ANALYST_T\" ]"

echo "-- 1. 真实 nmap 巡检一轮（patrol_all_subnets）--"
before="$(PSQL "SELECT count(*) FROM device_patrols;")"
stats="$($COMPOSE exec -T backend python -c "
import asyncio, json
from app.services.patrol import patrol_all_subnets
print(json.dumps(asyncio.run(patrol_all_subnets())))
" 2>/dev/null | tr -d '\r\n')"
check "巡检函数执行完成（返回 stats JSON）" "echo '$stats' | grep -qE '\"subnets\"'"
check "巡检覆盖到子网（subnets>=1）" "echo '$stats' | grep -qE '\"subnets\": ?[1-9]'"
after="$(PSQL "SELECT count(*) FROM device_patrols;")"
check "device_patrols 落行（新增 >=1）" "[ \"$after\" -gt \"$before\" ]"
done_rows="$(PSQL "SELECT count(*) FROM device_patrols WHERE scan_status IN ('completed','failed');")"
check "巡检行有 completed/failed 终态" "[ \"$done_rows\" -ge 1 ]"

echo "-- 2. 巡检历史 API + 部门数据范围 --"
patrols_m="$(curl -kfsS -H "Authorization: Bearer $MANAGER_T" "$BASE/api/v1/monitor/patrols")"
check "manager 可见巡检历史" "echo '$patrols_m' | grep -qE '\"online_count\"'"
m_nets="$(echo "$patrols_m" | grep -oE '\"network\":\"[0-9./]+\"' | sort -u)"
check "manager 巡检含业务网 10.0.10.0/24" "echo '$m_nets' | grep -q '10.0.10.0/24'"
patrols_a="$(curl -kfsS -H "Authorization: Bearer $ANALYST_T" "$BASE/api/v1/monitor/patrols")"
check "analyst 巡检历史仅本部门子网" "! echo '$patrols_a' | grep -qE '\"network\":\"10.0.0.0/24\"'"
check "analyst 巡检历史含业务网" "echo '$patrols_a' | grep -qE '\"network\":\"10.0.10.0/24\"'"

echo "-- 3. 设备列表带 offline_since 字段 --"
devs="$(curl -kfsS -H "Authorization: Bearer $MANAGER_T" "$BASE/api/v1/monitor/devices")"
check "设备列表含 offline_since 字段" "echo '$devs' | grep -qE '\"offline_since\"'"

echo "-- 4. 告警部门数据范围（临时告警测后即删）--"
DB_ID="$(PSQL "SELECT id FROM devices WHERE name='db-01';")"    # 攻防实验室
WEB_ID="$(PSQL "SELECT id FROM devices WHERE name='web-01';")"   # 安全运营部
TAG="$(date +%s)"
AL1="$(curl -kfsS -H "Authorization: Bearer $ANALYST_T" -X POST -H 'Content-Type: application/json' \
  -d "{\"title\":\"smoke-dept-$TAG\",\"severity\":\"high\",\"alert_type\":\"abnormal\",\"device_id\":$DB_ID,\"description\":\"dept alert\"}" \
  "$BASE/api/v1/monitor/alerts" 2>/dev/null || echo '{"code":-1}')"
check "创建 db-01 告警成功（analyst 本部门）" "echo '$AL1' | grep -qE '\"code\":0'"
curl -kfsS -H "Authorization: Bearer $MANAGER_T" -X POST -H 'Content-Type: application/json' \
  -d "{\"title\":\"smoke-other-$TAG\",\"severity\":\"high\",\"alert_type\":\"abnormal\",\"device_id\":$WEB_ID,\"description\":\"other dept\"}" \
  "$BASE/api/v1/monitor/alerts" >/dev/null 2>&1
curl -kfsS -H "Authorization: Bearer $MANAGER_T" -X POST -H 'Content-Type: application/json' \
  -d "{\"title\":\"smoke-global-$TAG\",\"severity\":\"low\",\"alert_type\":\"abnormal\",\"description\":\"global\"}" \
  "$BASE/api/v1/monitor/alerts" >/dev/null 2>&1
a_list="$(curl -kfsS -H "Authorization: Bearer $ANALYST_T" "$BASE/api/v1/monitor/alerts?size=100")"
check "analyst 见本部门告警" "echo '$a_list' | grep -q \"smoke-dept-$TAG\""
check "analyst 不见跨部门告警" "! echo '$a_list' | grep -q \"smoke-other-$TAG\""
check "analyst 不见全局告警" "! echo '$a_list' | grep -q \"smoke-global-$TAG\""
m_list="$(curl -kfsS -H "Authorization: Bearer $MANAGER_T" "$BASE/api/v1/monitor/alerts?size=100")"
check "manager 三条都可见" "echo '$m_list' | grep -q \"smoke-other-$TAG\" && echo '$m_list' | grep -q \"smoke-global-$TAG\" && echo '$m_list' | grep -q \"smoke-dept-$TAG\""

echo "-- 5. 扫描报告部门数据范围（临时报告测后即删）--"
R1="$(ID "INSERT INTO scan_reports(target_ip, device_id, report_type, scan_status, status, generated_by) VALUES ('10.0.10.12', $DB_ID, 'on_demand', 'completed', 'pending_review', 1) RETURNING id;")"
R2="$(ID "INSERT INTO scan_reports(target_ip, device_id, report_type, scan_status, status, generated_by) VALUES ('10.0.10.11', $WEB_ID, 'on_demand', 'completed', 'pending_review', 1) RETURNING id;")"
R3="$(ID "INSERT INTO scan_reports(target_ip, device_id, report_type, scan_status, status, generated_by) VALUES ('10.99.99.99', NULL, 'on_demand', 'completed', 'pending_review', 1) RETURNING id;")"
s_list="$(curl -kfsS -H "Authorization: Bearer $ANALYST_T" "$BASE/api/v1/monitor/scans/reports?size=100")"
check "analyst 见本部门报告" "echo '$s_list' | grep -q '\"id\":$R1'"
check "analyst 不见跨部门报告" "! echo '$s_list' | grep -q '\"id\":$R2'"
check "analyst 不见全局报告" "! echo '$s_list' | grep -q '\"id\":$R3'"
m_s="$(curl -kfsS -H "Authorization: Bearer $MANAGER_T" "$BASE/api/v1/monitor/scans/reports?size=100")"
check "manager 三条报告都可见" "echo '$m_s' | grep -q '\"id\":$R1' && echo '$m_s' | grep -q '\"id\":$R2' && echo '$m_s' | grep -q '\"id\":$R3'"

# 清理临时告警与报告
PSQL "DELETE FROM scan_reports WHERE id IN ($R1,$R2,$R3);" >/dev/null
PSQL "DELETE FROM alerts WHERE title LIKE 'smoke-%';" >/dev/null
left="$(PSQL "SELECT count(*) FROM alerts WHERE title LIKE 'smoke-%';")"
check "临时告警已清理" "[ \"$left\" = 0 ]"
leftr="$(PSQL "SELECT count(*) FROM scan_reports WHERE id IN ($R1,$R2,$R3);")"
check "临时报告已清理" "[ \"$leftr\" = 0 ]"

echo ""
echo "== 结果：$PASS 通过 / $FAIL 失败 =="
[ "$FAIL" = 0 ] && echo "巡检冒烟通过 ✅" || echo "存在失败项，请检查 ❌"
exit "$FAIL"

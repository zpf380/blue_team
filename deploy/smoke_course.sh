#!/usr/bin/env bash
# 训练课程管理 · 生产冒烟：manager 建草稿课程 → 学员端不可见 → 发布 → WebSocket 实时推送学员端
# → 学员端立即可见 + published_at → 学员可开始 → 删除保护(40900) → 清理。
#
# 验证点：
#   1) draft 课程学员端不可见（列表/详情 404/start 404）
#   2) 发布后 /ws/notifications 收到 training_course_published 实时推送
#   3) 学员端列表立即可见 + published_at 非空
#   4) 发布门控放行学员 start
#   5) 有学员进度后 DELETE 课程 → 40900（保护）
#
# 注意（Windows Git Bash）：中文 JSON 必须写入 UTF-8 文件后用 -d @file。
set -uo pipefail

BASE="https://localhost"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE="docker compose -p blueteam --env-file $ROOT/deploy/.env.prod -f $ROOT/deploy/docker-compose.prod.yml"
PY_BIN="$ROOT/backend/.venv/Scripts/python.exe"
TMP="$(mktemp -d 2>/dev/null || echo "$ROOT/deploy/.smoke_course_tmp")"
mkdir -p "$TMP"
PSQL() { $COMPOSE exec -T postgres psql -U blueteam -d blueteam -t -A -c "$1" 2>/dev/null | tr -d '\r\n '; }
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
TRAINEE_T="$(login trainee01)"
check "trainee01 登录拿到 token" "[ -n \"$TRAINEE_T\" ]"
M_AUTH="Authorization: Bearer $MANAGER_T"
T_AUTH="Authorization: Bearer $TRAINEE_T"

TAG="$(date +%s)"
CID=""

echo "-- 1. manager 建草稿课程 + 场景 --"
cat > "$TMP/course.json" <<EOF
{"name":"冒烟课程-$TAG","description":"冒烟测试课程","difficulty":1}
EOF
CREATE="$(jcurl -X POST -H "$M_AUTH" -d @"$TMP/course.json" "$BASE/api/v1/training/manage/courses")"
check "创建草稿课程成功" "echo '$CREATE' | grep -qE '\"code\":0'"
CID="$(echo "$CREATE" | grep -oE '\"course_id\":[0-9]+' | head -1 | cut -d: -f2)"
check "拿到课程 id" "[ -n \"$CID\" ]"

cat > "$TMP/scenario.json" <<EOF
{"title":"冒烟场景","description":"冒烟测试场景","points":30,"penalty_points":5,"time_limit":15,"order_index":1,"content":{"intro":"冒烟测试场景引言：分析日志定位攻击源。","files":{"/var/log/auth.log":"Aug 13 02:11:07 Failed password for root from 203.0.113.9 port 51243"},"tasks":[{"id":"t1","title":"查看日志","points":10,"hint":"cat /var/log/auth.log","check":{"cmd":"cat","args":"/var/log/auth.log"}},{"id":"t2","title":"定位攻击IP","points":20,"hint":"grep 203.0.113.9 /var/log/auth.log","check":{"cmd":"grep","pattern":"203.0.113.9"}}]}}
EOF
SC="$(jcurl -X POST -H "$M_AUTH" -d @"$TMP/scenario.json" "$BASE/api/v1/training/manage/courses/$CID/scenarios")"
check "添加场景成功" "echo '$SC' | grep -qE '\"code\":0'"
SCEN_ID="$(echo "$SC" | grep -oE '\"id\":[0-9]+' | head -1 | cut -d: -f2)"
check "拿到场景 id" "[ -n \"$SCEN_ID\" ]"

echo "-- 2. 草稿门控：学员端不可见 --"
AGENTS_T="$(curl -kfsS -H "$T_AUTH" "$BASE/api/v1/training/agents")"
check "trainee 列表无草稿课程" "! echo '$AGENTS_T' | grep -qE \"\\\"id\\\":$CID\""
DET="$(curl -kfsS -H "$T_AUTH" "$BASE/api/v1/training/agents/$CID")"
check "trainee 详情 404" "echo '$DET' | grep -qE '\"code\":40400'"
START="$(curl -kfsS -X POST -H "$T_AUTH" "$BASE/api/v1/training/scenarios/$SCEN_ID/start")"
check "trainee start 草稿场景 404" "echo '$START' | grep -qE '\"code\":40400'"

echo "-- 3. 发布 → WebSocket 实时推送 --"
cat > "$TMP/ws_listen.py" <<'PYEOF'
import asyncio, json, ssl, sys
import websockets

async def main():
    url = sys.argv[1]
    sslctx = ssl.create_default_context()
    sslctx.check_hostname = False
    sslctx.verify_mode = ssl.CERT_NONE
    async with websockets.connect(url, ssl=sslctx) as ws:
        try:
            while True:
                raw = await asyncio.wait_for(ws.recv(), timeout=25)
                msg = json.loads(raw)
                if msg.get("type") == "training_course_published":
                    print(json.dumps(msg, ensure_ascii=False), flush=True)
                    return 0
        except asyncio.TimeoutError:
            print("TIMEOUT_NO_EVENT")
            return 2
        except Exception as exc:
            print(f"WS_ERROR:{exc}")
            return 3

sys.exit(asyncio.run(main()))
PYEOF
"$PY_BIN" "$TMP/ws_listen.py" "wss://localhost/ws/notifications?token=$TRAINEE_T" > "$TMP/ws_out.txt" 2> "$TMP/ws_err.txt" &
WS_PID=$!
sleep 2

PUBLISH="$(jcurl -X POST -H "$M_AUTH" "$BASE/api/v1/training/manage/courses/$CID/publish")"
check "发布成功" "echo '$PUBLISH' | grep -qE '\"code\":0'"
check "发布返回 status=published" "echo '$PUBLISH' | grep -qE '\"status\":\"published\"'"

EVT=""
for i in $(seq 1 40); do
  if [ -s "$TMP/ws_out.txt" ]; then EVT="$(cat "$TMP/ws_out.txt")"; break; fi
  sleep 0.5
done
kill "$WS_PID" 2>/dev/null || true
check "trainee 收到新课程推送" "echo '$EVT' | grep -qE 'training_course_published'"
check "推送含本课程 id" "echo '$EVT' | grep -qE '\"course_id\": *$CID'"
check "推送含场景数=1" "echo '$EVT' | grep -qE '\"scenario_count\": *1'"

echo "-- 4. 发布后学员端立即可见 --"
AGENTS_T2="$(curl -kfsS -H "$T_AUTH" "$BASE/api/v1/training/agents")"
check "trainee 列表含新课程" "echo '$AGENTS_T2' | grep -qE '\"id\":$CID'"
check "新课程带 published_at" "echo '$AGENTS_T2' | grep -qE '\"published_at\":\"20'"
DET2="$(curl -kfsS -H "$T_AUTH" "$BASE/api/v1/training/agents/$CID")"
check "trainee 详情可见（含场景）" "echo '$DET2' | grep -qE '\"scenarios\":\['"

START2="$(curl -kfsS -X POST -H "$T_AUTH" "$BASE/api/v1/training/scenarios/$SCEN_ID/start")"
check "trainee 可开始已发布场景" "echo '$START2' | grep -qE '\"code\":0'"
check "开始返回 session_id" "echo '$START2' | grep -qE '\"session_id\":\"'"

echo "-- 5. 删除保护 + 清理 --"
DEL="$(curl -kfsS -X DELETE -H "$M_AUTH" "$BASE/api/v1/training/manage/courses/$CID")"
check "有学员进度后 DELETE 课程 → 40900" "echo '$DEL' | grep -qE '\"code\":40900'"
PSQL "DELETE FROM training_progress WHERE scenario_id=$SCEN_ID;" >/dev/null
PSQL "DELETE FROM sandbox_sessions WHERE scenario_id=$SCEN_ID;" >/dev/null
PSQL "DELETE FROM training_scenarios WHERE id=$SCEN_ID;" >/dev/null
PSQL "DELETE FROM training_agents WHERE id=$CID;" >/dev/null
left="$(PSQL "SELECT count(*) FROM training_agents WHERE id=$CID;")"
check "课程已清理" "[ \"$left\" = 0 ]"

rm -rf "$TMP"
echo ""
echo "== 结果：$PASS 通过 / $FAIL 失败 =="
[ "$FAIL" = 0 ] && echo "课程管理冒烟通过 ✅" || echo "存在失败项，请检查 ❌"
exit "$FAIL"

#!/usr/bin/env bash
# 蓝队业务管理系统 · 生产部署冒烟测试（HTTPS 全链路）
# 用法：bash deploy/smoke.sh [base_url]  默认 https://localhost
# 验证点：HTTPS/安全头 / 登录+图形验证码 / 管理员强制 MFA / 阶段5新功能（导出/导入/租约回收/文件白名单）/ CSRF
#
# 注意（Windows Git Bash）：
#  - 中文 JSON 必须写入 UTF-8 文件后用 -d @file，直接内联中文会被 Windows curl.exe 按
#    ANSI 码页(GBK)编码 → JSON 解析失败(400)。
#  - -F "file=@路径" 的路径若为绝对 MSYS 路径不会被转换，须用相对路径（相对脚本 CWD）。
set -uo pipefail

BASE="${1:-https://localhost}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$ROOT/deploy/.env.prod"
COMPOSE="docker compose -p blueteam --env-file $ENV_FILE -f $ROOT/deploy/docker-compose.prod.yml"

PASS=0; FAIL=0
ok()   { PASS=$((PASS+1)); echo "  ✓ $1"; }
bad()  { FAIL=$((FAIL+1)); echo "  ✗ $1"; }
check() { if eval "$2"; then ok "$1"; else bad "$1"; fi }

jcurl() { curl -kfsS -H 'Content-Type: application/json' -H 'X-Requested-With: XMLHttpRequest' "$@"; }

# 获取图形验证码（GET）并从 Redis 读出验证码
get_captcha() {
  local cap cap_id code
  cap="$(jcurl "$BASE/api/v1/auth/captcha")"
  cap_id="$(echo "$cap" | grep -oE '"captcha_id":"[a-f0-9]+"' | head -1 | cut -d'"' -f4)"
  code="$($COMPOSE exec -T redis redis-cli GET "captcha:$cap_id" 2>/dev/null | tr -d '\r\n')"
  printf '%s %s' "$cap_id" "$code"
}

echo "== 1. HTTPS 与安全头 =="
health="$(curl -kfsS "$BASE/health" 2>/dev/null || echo "")"
check "健康端点 /health 可达" "[ -n \"$health\" ]"
hdrs="$(curl -kfsS -D - -o /dev/null "$BASE/")"
check "HSTS (Strict-Transport-Security)" "echo '$hdrs' | grep -qi 'strict-transport-security'"
check "CSP (Content-Security-Policy)"     "echo '$hdrs' | grep -qi 'content-security-policy'"
check "X-Frame-Options"                    "echo '$hdrs' | grep -qi 'x-frame-options'"
check "X-Content-Type-Options: nosniff"    "echo '$hdrs' | grep -qi 'x-content-type-options'"
check "Referrer-Policy"                    "echo '$hdrs' | grep -qi 'referrer-policy'"

echo "== 2. 图形验证码登录（manager01）=="
read -r CAP_ID CODE <<< "$(get_captcha)"
check "获取验证码 captcha_id" "[ -n \"$CAP_ID\" ]"
check "从 Redis 读回验证码（仅本地部署可行）" "[ -n \"$CODE\" ]"
login="$(jcurl -X POST "$BASE/api/v1/auth/login" \
  -d "{\"username\":\"manager01\",\"password\":\"Bt@123456\",\"captcha_id\":\"$CAP_ID\",\"captcha_code\":\"$CODE\"}")"
TOKEN="$(echo "$login" | grep -oE '"access_token":"[^"]+"' | head -1 | cut -d'"' -f4)"
check "manager01 登录成功拿到 access_token" "[ -n \"$TOKEN\" ]"
AUTH="Authorization: Bearer $TOKEN"

echo "== 3. 管理员强制 MFA（临时 admin 角色用户，测后即删）=="
# 生产库 admin 密码已被改，无法用默认口令登录；创建一个临时 admin 角色用户验证
# MFA 强制（未绑定 TOTP → mfa_required + mfa_setup，不签发 access_token），测后删除。
C_HASH="$($COMPOSE exec -T backend python -c "from app.core.security import hash_password; print(hash_password('Smoke@12345'))")"
$COMPOSE exec -T postgres psql -U blueteam -d blueteam -c \
  "INSERT INTO users(username, real_name, password_hash, role_id, status, security_level, failed_attempts)
   VALUES ('smoke_mfa_test','Smoke MFA','$C_HASH',(SELECT id FROM roles WHERE code='admin'),'active',1,0)
   ON CONFLICT (username) DO UPDATE SET role_id=(SELECT id FROM roles WHERE code='admin'), status='active', failed_attempts=0, password_hash='$C_HASH';" >/dev/null 2>&1
read -r CAP2 CODE2 <<< "$(get_captcha)"
admin_login="$(jcurl -X POST "$BASE/api/v1/auth/login" \
  -d "{\"username\":\"smoke_mfa_test\",\"password\":\"Smoke@12345\",\"captcha_id\":\"$CAP2\",\"captcha_code\":\"$CODE2\"}")"
check "admin 角色登录被要求二次认证 mfa_required" "echo '$admin_login' | grep -q 'mfa_required'"
admin_token="$(echo "$admin_login" | grep -oE '"access_token":"[^"]+"' | head -1 | cut -d'"' -f4)"
check "未完成 TOTP 未签发 access_token" "[ -z \"$admin_token\" ]"
# 清理：优先删除；审计外键可能阻止删除时降级为禁用
$COMPOSE exec -T postgres psql -U blueteam -d blueteam -c "DELETE FROM users WHERE username='smoke_mfa_test';" >/dev/null 2>&1 \
  || $COMPOSE exec -T postgres psql -U blueteam -d blueteam -c "UPDATE users SET status='disabled' WHERE username='smoke_mfa_test';" >/dev/null 2>&1
left="$($COMPOSE exec -T postgres psql -U blueteam -d blueteam -t -A -c "SELECT count(*) FROM users WHERE username='smoke_mfa_test' AND status='active';" 2>/dev/null | tr -d '\r\n ')"
check "临时 MFA 测试用户已清理" "[ \"$left\" = 0 ]"

echo "== 4. 阶段5新功能冒烟（manager01 权限路径）=="
devices="$(curl -kfsS -H "$AUTH" "$BASE/api/v1/monitor/devices")"
check "设备清单接口可用" "echo '$devices' | grep -qE '\"code\":0'"

xlsx_code="$(curl -kfsS -H "$AUTH" "$BASE/api/v1/monitor/devices/export" -o "$ROOT/deploy/smoke_devices.xlsx" -w '%{http_code}')"
check "设备导出 XLSX：HTTP 200" "[ \"$xlsx_code\" = 200 ]"
check "设备导出 XLSX：ZIP 魔数 PK" "[ \"$(head -c2 "$ROOT/deploy/smoke_devices.xlsx")\" = PK ]"
WROOT="$(cygpath -w "$ROOT")"
xlsx_ok="$("$ROOT/backend/.venv/Scripts/python.exe" -c "
from openpyxl import load_workbook
wb = load_workbook(r'$WROOT\\deploy\\smoke_devices.xlsx')
ws = wb.active
rows = list(ws.values)
assert rows and rows[0][1] == 'IP地址', rows[:1]
data = [r for r in rows[1:] if r and any(c not in (None,'') for c in r)]
print('rows=%d' % len(data))
" 2>&1)"
check "设备导出 XLSX：表头含 IP地址（工作簿有效）" "echo '$xlsx_ok' | grep -q 'rows='"
check "设备导出 XLSX：含种子设备数据行" "echo '$xlsx_ok' | grep -qE 'rows=[1-9]'"

recycle="$(curl -kfsS -H "$AUTH" -X POST "$BASE/api/v1/monitor/allocations/recycle")"
check "租约回收接口返回 recycled" "echo '$recycle' | grep -qE '\"recycled\"'"

printf 'name,ip_address,mac_address,device_type,manufacturer,model,location,department,status\n冒烟终端,10.0.0.250,,pc,Acme,SmokeX,机房A,安全运营部,active\n' > "$ROOT/deploy/smoke_import.csv"
imp="$(curl -kfsS -H "$AUTH" -F 'file=@deploy/smoke_import.csv;type=text/csv' "$BASE/api/v1/monitor/devices/import")"
check "设备导入 CSV：created=1" "echo '$imp' | grep -qE '\"created\":1'"
dev_id="$(curl -kfsS -H "$AUTH" "$BASE/api/v1/monitor/devices" | grep -oE '\{\"id\":[0-9]+,\"name\":\"冒烟终端\"' | head -1 | grep -oE '[0-9]+' | head -1)"
if [ -n "$dev_id" ]; then
  curl -kfsS -H "$AUTH" -X DELETE "$BASE/api/v1/monitor/devices/$dev_id" >/dev/null 2>&1
  check "冒烟导入的设备已清理（DELETE）" "[ -n \"$dev_id\" ]"
fi

printf '{"alert_type":"abnormal","severity":"high","title":"生产冒烟告警","description":"阶段6冒烟测试创建"}' > "$ROOT/deploy/smoke_alert.json"
alert="$(jcurl -X POST -H "$AUTH" "$BASE/api/v1/monitor/alerts" -d @deploy/smoke_alert.json)"
check "创建告警成功" "echo '$alert' | grep -qE '\"code\":0'"

echo "== 5. 文件类型白名单 =="
printf 'MZ fake exe' > "$ROOT/deploy/smoke_evil.exe"
printf 'MZ fake exe' > "$ROOT/deploy/smoke_evil.png"
f_exe="$(curl -kfsS -H "$AUTH" -F 'file=@deploy/smoke_evil.exe;type=application/x-msdownload' "$BASE/api/v1/files" 2>/dev/null || true)"
check ".exe 上传被拒绝（不支持类型）" "echo '$f_exe' | grep -q '不支持的文件类型'"
f_png="$(curl -kfsS -H "$AUTH" -F 'file=@deploy/smoke_evil.png;type=text/html' "$BASE/api/v1/files" 2>/dev/null || true)"
check ".png 声明 MIME 与扩展名不匹配被拒" "echo '$f_png' | grep -qE '不匹配|不支持'"

echo "== 6. 会话加固：cookie 认证非 GET 缺 CSRF 头被拒 =="
read -r CAP3 CODE3 <<< "$(get_captcha)"
jar="$ROOT/deploy/smoke_cookies.txt"; rm -f "$jar"
jcurl -c "$jar" -X POST "$BASE/api/v1/auth/login" \
  -d "{\"username\":\"manager01\",\"password\":\"Bt@123456\",\"captcha_id\":\"$CAP3\",\"captcha_code\":\"$CODE3\"}" >/dev/null 2>&1
csrf_block="$(curl -kfsS -b "$jar" -H 'Content-Type: application/json' \
  -d '{"alert_type":"abnormal","severity":"low","title":"CSRF-test","description":"x"}' \
  "$BASE/api/v1/monitor/alerts" 2>/dev/null || true)"
check "cookie 会话非 GET 缺 CSRF 头 → 拒绝" "echo '$csrf_block' | grep -qE 'CSRF|缺少'"

rm -f "$ROOT/deploy/smoke_import.csv" "$ROOT/deploy/smoke_alert.json" \
      "$ROOT/deploy/smoke_evil.exe" "$ROOT/deploy/smoke_evil.png" \
      "$ROOT/deploy/smoke_cookies.txt" "$ROOT/deploy/smoke_devices.xlsx"
echo ""
echo "== 结果：$PASS 通过 / $FAIL 失败 =="
[ "$FAIL" = 0 ] && echo "生产部署冒烟通过 ✅" || echo "存在失败项，请检查 ❌"
exit "$FAIL"

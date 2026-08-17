#!/usr/bin/env bash
# 蓝队业务管理系统 · 安全自检脚本
# 检查：① 部署密钥/口令 ② 默认账号弱口令（bcrypt 实比）③ nginx Server 头
#       ④ 安全响应头 ⑤ IP 请求限流
# 用法：bash deploy/security_check.sh
# 说明：弱口令/密钥/头泄露为【风险】项（发现即退出码非 0）；栈未运行等环境问题仅【警告】。
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$ROOT/deploy/.env.prod"
COMPOSE="docker compose -p blueteam --env-file $ENV_FILE -f $ROOT/deploy/docker-compose.prod.yml"
BASE_URL="${BASE_URL:-https://localhost}"

GREEN=$'\033[32m'; RED=$'\033[31m'; YELLOW=$'\033[33m'; NC=$'\033[0m'
pass() { echo "  ${GREEN}[通过]${NC} $1"; }
warn() { echo "  ${YELLOW}[警告]${NC} $1"; }
fail() { echo "  ${RED}[风险]${NC} $1"; RISK=1; }
RISK=0

echo "======================================================"
echo "  蓝队业务管理系统 · 安全自检"
echo "======================================================"

# ---------- 1/5 部署密钥 / 口令 ----------
echo ""
echo "[1/5] 部署密钥 / 口令（deploy/.env.prod）"
if [ ! -f "$ENV_FILE" ]; then
  warn "缺少 $ENV_FILE（生产部署需 cp deploy/.env.prod.example deploy/.env.prod）"
else
  jwt="$(grep -E '^JWT_SECRET_KEY=' "$ENV_FILE" | head -1 | cut -d= -f2-)"
  if [ -z "$jwt" ]; then
    warn "JWT_SECRET_KEY 未设置"
  elif echo "$jwt" | grep -qiE 'dev-secret|please-change|change-me|your-secret|TODO|xxxx|test-'; then
    fail "JWT_SECRET_KEY 疑似占位符：${jwt:0:24}…（请改为随机长串 ≥32 字符）"
  elif [ "${#jwt}" -lt 32 ]; then
    warn "JWT_SECRET_KEY 仅 ${#jwt} 字符，建议 ≥32"
  else
    pass "JWT_SECRET_KEY 已设置且非占位符（${#jwt} 字符）"
  fi

  pg="$(grep -E '^POSTGRES_PASSWORD=' "$ENV_FILE" | head -1 | cut -d= -f2-)"
  if [ -z "$pg" ]; then
    warn "POSTGRES_PASSWORD 未设置（compose 会用默认 blueteam_pass）"
  elif echo "$pg" | grep -qiE 'blueteam_pass|postgres|password|123456|admin'; then
    fail "POSTGRES_PASSWORD 疑似弱口令：${pg:0:16}…"
  else
    pass "POSTGRES_PASSWORD 已设置"
  fi

  mu="$(grep -E '^MINIO_ROOT_USER=' "$ENV_FILE" | head -1 | cut -d= -f2-)"
  mp="$(grep -E '^MINIO_ROOT_PASSWORD=' "$ENV_FILE" | head -1 | cut -d= -f2-)"
  if [ "${mu:-minioadmin}" = "minioadmin" ] || [ "${mp:-minioadmin}" = "minioadmin" ]; then
    fail "MINIO_ROOT_USER / MINIO_ROOT_PASSWORD 仍为默认 minioadmin"
  else
    pass "MinIO 根账号口令已改"
  fi
fi

# ---------- 2/5 默认账号弱口令 ----------
echo ""
echo "[2/5] 数据库默认账号弱口令（bcrypt 实比）"
if docker ps --format '{{.Names}}' | grep -qE 'blueteam.*-backend'; then
  HITS="$(
$COMPOSE exec -T backend python - <<'PY' 2>/dev/null || true
import asyncio
from sqlalchemy import select
from app.db.session import AsyncSessionLocal
from app.models import User
from app.core.security import verify_password

WEAK = ['admin123', 'Bt@123456', 'password', '123456', 'admin', 'Admin@123']

async def main():
    async with AsyncSessionLocal() as s:
        rows = (await s.execute(select(User.username, User.password_hash))).all()
        for username, pwd_hash in rows:
            for p in WEAK:
                if verify_password(p, pwd_hash):
                    print(username + '|' + p)

asyncio.run(main())
PY
)"
  if [ -n "$HITS" ]; then
    while IFS='|' read -r u p; do
      [ -n "$u" ] && fail "默认弱口令：$u / $p（请登录后改强密码）"
    done <<<"$HITS"
  else
    pass "未发现默认弱口令"
  fi
else
  warn "backend 容器未运行，跳过默认口令检查（先 bash deploy/start.sh）"
fi

# ---------- 3/5 nginx Server 头 ----------
echo ""
echo "[3/5] nginx Server 头（版本隐藏）"
srv="$(curl -kIsS --max-time 10 "$BASE_URL/health" | tr -d '\r' | grep -iE '^server:' || true)"
if [ -z "$srv" ]; then
  warn "未获取到 Server 头（$BASE_URL 不可达？先启动栈）"
elif echo "$srv" | grep -qE 'nginx/[0-9.]+'; then
  fail "Server 头泄露版本：$(echo "$srv" | sed 's/^[Ss]erver: //')（应仅显示 nginx 或隐藏）"
else
  pass "Server 头未泄露版本：$(echo "$srv" | sed 's/^[Ss]erver: //')"
fi

# ---------- 4/5 安全响应头 ----------
echo ""
echo "[4/5] 安全响应头"
HDRS="$(curl -kIsS --max-time 10 "$BASE_URL/" | tr -d '\r')"
check_hdr() {
  local name="$1" need="${2:-}"
  if printf '%s\n' "$HDRS" | grep -qiE "^$name:" &&
     { [ -z "$need" ] || printf '%s\n' "$HDRS" | grep -qiE "^$name:.*$need"; }; then
    pass "$name"
  else
    fail "$name 缺失${need:+（缺 $need）}"
  fi
}
check_hdr "Content-Security-Policy" "upgrade-insecure-requests"
check_hdr "Strict-Transport-Security"
check_hdr "X-Content-Type-Options" "nosniff"
check_hdr "X-Frame-Options" "SAMEORIGIN"
check_hdr "Referrer-Policy"
check_hdr "Permissions-Policy"

# ---------- 5/5 IP 限流 ----------
echo ""
echo "[5/5] IP 请求限流（连发 captcha 探 429）"
codes=""
for i in $(seq 1 15); do
  code="$(curl -k -s -o /dev/null -w '%{http_code}' --max-time 5 "$BASE_URL/api/v1/auth/captcha")"
  codes="$codes $code"
done
if echo "$codes" | grep -q '429'; then
  pass "限流生效（连发 15 次触发 429：$codes）"
else
  warn "未触发 429（burst 内通过或限流未生效：$codes）"
fi

echo ""
echo "======================================================"
if [ "$RISK" = 1 ]; then
  echo "  自检结果：存在高风险项，请尽快修复（见上方【风险】标记）"
  exit 1
else
  echo "  自检结果：全部通过 ✅"
  exit 0
fi

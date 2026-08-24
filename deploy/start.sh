#!/usr/bin/env bash
# 蓝队业务管理系统 · 一键完整启动
# 功能：Docker Desktop（未运行时自动拉起）→ 生产栈 → 公网隧道 → 健康验证 → 访问地址汇总。
# 用法：bash deploy/start.sh
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
URL_CF=""   # 公网隧道地址

echo "======================================================"
echo "  蓝队业务管理系统 · 一键完整启动"
echo "======================================================"

# ---------- 1/5 检查并拉起 Docker Desktop ----------
echo ""
echo "[1/5] 检查 Docker daemon…"
if docker info >/dev/null 2>&1; then
  echo "      ✅ Docker daemon 已就绪"
else
  echo "      Docker Desktop 未运行，正在启动…"
  "/c/Program Files/Docker/Docker/Docker Desktop.exe" & disown
  ok=0
  for i in $(seq 1 60); do
    if docker info >/dev/null 2>&1; then
      echo "      ✅ daemon 就绪（第 ${i} 次探测）"
      ok=1; break
    fi
    sleep 3
  done
  if [ "$ok" = 0 ]; then
    echo "      ❌ Docker daemon 3 分钟仍未就绪，请检查 Docker Desktop 是否正常"
    exit 1
  fi
fi

# ---------- 2/5 启动生产栈（构建 + 启动 + seed，幂等） ----------
echo ""
echo "[2/5] 启动生产栈（容器：backend/frontend/postgres/redis/minio）…"
bash "$ROOT/deploy/deploy.sh" up

# ---------- 3/5 启动公网隧道（免费 Cloudflare Tunnel） ----------
echo ""
echo "[3/5] 启动公网隧道…"
TUNNEL_OUT="$(bash "$ROOT/deploy/tunnel.sh" up 2>&1)"
TUNNEL_RC=$?
if [ "$TUNNEL_RC" = 0 ]; then
  URL_CF="$(echo "$TUNNEL_OUT" | grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' | head -1)"
  echo "      ✅ 公网地址：${URL_CF:-<未知>}"
else
  echo "      ⚠️  公网隧道启动失败（不影响本机/局域网访问）："
  echo "$TUNNEL_OUT" | tail -3
fi

# ---------- 4/5 健康验证 ----------
echo ""
echo "[4/5] 健康验证…"
h_local=""
for i in $(seq 1 20); do
  h_local="$(curl -kfsS --max-time 5 https://localhost/health 2>/dev/null)"
  echo "$h_local" | grep -qE '"code":0' && break
  sleep 2
done
if echo "$h_local" | grep -qE '"code":0'; then
  echo "      ✅ 本机 /health 正常"
else
  echo "      ❌ 本机 /health 异常：${h_local:-无响应}"
  echo "      查看后端日志：bash deploy/deploy.sh logs backend"
  exit 1
fi

if [ -n "$URL_CF" ]; then
  h_cf="$(curl -ksS --max-time 20 "$URL_CF/health" 2>/dev/null)"
  if echo "$h_cf" | grep -qE '"code":0'; then
    echo "      ✅ 公网 /health 正常（隧道可达）"
  else
    echo "      ⚠️  公网 /health 暂不可达（隧道刚建可能需 10~30s 生效，稍后重试即可）"
  fi
fi

# ---------- 5/5 访问地址汇总 ----------
echo ""
echo "[5/5] 访问地址汇总"
echo "======================================================"
# 局域网 IP：提取 ipconfig 中的 IPv4，过滤虚拟网卡/回环/APIPA 段
LAN_IP="$(ipconfig 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+' \
  | grep -vE '^(255\.|127\.|169\.254\.|172\.(1[6-9]|2[0-9]|3[01])\.|10\.|0\.)' \
  | grep -vE '^(192\.168\.(59|133)\.)' | head -1)"
echo "  本机      https://localhost"
[ -n "$LAN_IP" ] && echo "  局域网    https://$LAN_IP"
if [ -n "$URL_CF" ]; then
  echo "  公网      $URL_CF"
  echo ""
  echo "  提示：公网地址每次隧道重启会变，随时用 bash deploy/tunnel.sh status 查询。"
fi
echo ""
echo "  默认账号：生产环境 6 个默认账号已改随机强密码"
echo "           （口令保存在本地自查记录，不随脚本输出）"
echo "  自签证书浏览器会提示，点击『继续前往』即可。"
echo "======================================================"
echo "启动完成 ✅"

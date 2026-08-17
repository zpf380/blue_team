#!/usr/bin/env bash
# 蓝队业务管理系统 · Cloudflare Tunnel（免费公网访问）辅助脚本
#
# 原理：cloudflared 容器建立到 Cloudflare 边缘的出站隧道，生成临时公网地址
#   https://<random>.trycloudflare.com  —— 无需公网 IP / 无需路由器配置 / 无需买服务器。
# 好处：来源 IP 变真实公网 IP（登录审计不再全是 Docker 网关地址）。
# 局限：
#   1) 地址每次隧道重启都会变（quick tunnel 免费特性）；
#   2) 国内访问 Cloudflare 边缘可能间歇性慢/不稳（时好时坏）；
#   3) 若要固定地址，需自有域名并托管到 Cloudflare（几元/年），改用 named tunnel。
#
# 用法：
#   bash deploy/tunnel.sh up       # 启动隧道（不存在则创建），完成后打印公网地址
#   bash deploy/tunnel.sh status   # 显示当前公网地址（docker logs 解析）
#   bash deploy/tunnel.sh down     # 停止隧道
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NETWORK="blueteam_bt-net"
IMG="cloudflare/cloudflared:latest"
NAME="bt-tunnel"

current_url() {
  docker logs "$NAME" 2>&1 | grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' | head -1
}

case "${1:-up}" in
  up)
    if docker ps --format '{{.Names}}' | grep -qx "$NAME"; then
      echo "[tunnel] 隧道已在运行：$(current_url)"
      exit 0
    fi
    # 清理可能残留的旧容器，再全新启动（URL 会更新）
    docker rm -f "$NAME" >/dev/null 2>&1 || true
    echo "[tunnel] 启动 Cloudflare Tunnel（连接 CF 边缘，约需 5~10s）…"
    docker run -d --name "$NAME" --restart unless-stopped --network "$NETWORK" \
      "$IMG" tunnel --no-autoupdate --no-tls-verify --url https://frontend >/dev/null
    for i in $(seq 1 20); do
      url="$(current_url)"
      if [ -n "$url" ]; then break; fi
      sleep 1
    done
    if [ -n "$url" ]; then
      echo "[tunnel] ✅ 公网地址：$url"
      echo "[tunnel] 浏览器打开即可（首次可能等 10~30s 生效）；来源 IP 将记录真实公网 IP。"
    else
      echo "[tunnel] ❌ 未拿到公网地址，请用 docker logs $NAME 查看错误。"
      exit 1
    fi
    ;;
  status)
    url="$(current_url)"
    if [ -n "$url" ]; then
      echo "[tunnel] 当前公网地址：$url"
    else
      echo "[tunnel] 隧道未运行或无地址（先执行 bash deploy/tunnel.sh up）"
    fi
    ;;
  down)
    docker rm -f "$NAME" >/dev/null 2>&1 && echo "[tunnel] 隧道已停止" || echo "[tunnel] 隧道未运行"
    ;;
  *)
    echo "用法: bash deploy/tunnel.sh [up|status|down]"
    ;;
esac

#!/usr/bin/env bash
# 蓝队业务管理系统 · 单机部署助手（在项目根目录执行）
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="$ROOT/deploy/docker-compose.prod.yml"
ENV_FILE="$ROOT/deploy/.env.prod"
CERT_DIR="$ROOT/deploy/certs"
BACKUP_DIR="$ROOT/deploy/backup"
BACKUP_KEEP=30   # 保留最近 N 份备份，自动清理旧档

cmd="${1:-up}"

compose() {
  docker compose -p blueteam --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"
}

# ---- 随机值生成（hex 保证可安全嵌入 URL/密码）----
gen_hex() { openssl rand -hex "${1:-24}"; }
gen_b64() { openssl rand -base64 "${1:-48}" | tr -d '\n'; }

# ---- 环境硬化 ----
# first=1：首次部署（刚复制 .env.prod.example）→ 全部口令/密钥替换为随机值
# first=0：存量部署 → JWT 弱值强制替换随机（重启后端生效）；DB/MinIO 弱口令仅警告
#          （自动替换会与已初始化的数据卷口令不一致导致后端无法连接）
harden_env() {
  local first="${1:-0}"
  if [ "$first" = "1" ]; then
    sed -i \
      -e "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=$(gen_hex 24)|" \
      -e "s|^MINIO_ROOT_PASSWORD=.*|MINIO_ROOT_PASSWORD=$(gen_hex 32)|" \
      -e "s|^JWT_SECRET_KEY=.*|JWT_SECRET_KEY=$(gen_b64 48)|" \
      "$ENV_FILE"
    echo "[deploy] 已为 .env.prod 生成随机数据库/MinIO 口令与 JWT 密钥"
    return
  fi

  if grep -qE '^JWT_SECRET_KEY=(please-change-me-to-a-long-random-secret|dev-secret-key-change-in-production)' "$ENV_FILE"; then
    sed -i "s|^JWT_SECRET_KEY=.*|JWT_SECRET_KEY=$(gen_b64 48)|" "$ENV_FILE"
    echo "[deploy] JWT_SECRET_KEY 原为弱值，已替换为随机密钥（现有登录会话将失效，需重新登录）"
  fi
  if grep -qE '^POSTGRES_PASSWORD=blueteam_pass$' "$ENV_FILE"; then
    echo "[warn] POSTGRES_PASSWORD 仍为默认值 blueteam_pass！自动替换会与现有数据库卷口令不一致，"
    echo "       请手动处理：先备份，再 docker compose down -v 重建卷，然后修改 .env.prod 中该值。"
  fi
  if grep -qE '^MINIO_ROOT_PASSWORD=minioadmin$' "$ENV_FILE"; then
    echo "[warn] MINIO_ROOT_PASSWORD 仍为默认值 minioadmin！同上，请手动处理（重建 minio 卷后修改）。"
  fi
  return 0
}

# ---- 自签 TLS 证书（HTTPS）----
ensure_certs() {
  if [ -f "$CERT_DIR/server.crt" ] && [ -f "$CERT_DIR/server.key" ]; then
    return
  fi
  mkdir -p "$CERT_DIR"
  echo "[deploy] 生成自签 TLS 证书（CN=localhost，有效期 825 天）…"
  # Windows Git Bash 会把 "-subj /CN=localhost" 的 /CN 当成路径转成
  # C:/Program Files/Git/CN 导致 openssl 失败：MSYS_NO_PATHCONV=1 禁用转换。
  # 禁用转换后绝对 MSYS 路径（/h/...）不再被转成 Windows 路径，故进入证书目录用相对路径输出。
  (
    cd "$CERT_DIR"
    MSYS_NO_PATHCONV=1 openssl req -x509 -newkey rsa:2048 -nodes \
      -keyout server.key -out server.crt \
      -days 825 -subj "/CN=localhost" \
      -addext "subjectAltName=DNS:localhost,IP:127.0.0.1"
  )
  echo "[deploy] 证书已生成：deploy/certs/（正式环境请替换为受信任证书，挂载路径不变）"
}

# ---- 数据库备份（pg_dump → deploy/backup/，保留最近 $BACKUP_KEEP 份）----
backup() {
  mkdir -p "$BACKUP_DIR"
  local ts out
  ts="$(date +%Y%m%d_%H%M%S)"
  out="$BACKUP_DIR/blueteam_${ts}.sql"
  echo "[deploy] 备份数据库 → $out"
  docker compose -p blueteam --env-file "$ENV_FILE" -f "$COMPOSE_FILE" \
    exec -T postgres pg_dump -U blueteam -d blueteam --clean --if-exists > "$out" \
    || { rm -f "$out"; echo "[deploy] 备份失败：pg_dump 退出非零，已清理无效文件" >&2; return 1; }
  # 完整性校验：pg_dump 成功输出以 Dump complete 收尾
  if [ ! -s "$out" ] || ! grep -q "Dump complete" "$out"; then
    rm -f "$out"
    echo "[deploy] 备份失败：输出为空或未完成，已清理无效文件" >&2
    return 1
  fi
  # 清理旧备份，保留最近 $BACKUP_KEEP 份
  ls -1t "$BACKUP_DIR"/blueteam_*.sql 2>/dev/null | tail -n +$((BACKUP_KEEP + 1)) | xargs -r rm -f
  local count
  count="$(ls -1 "$BACKUP_DIR"/blueteam_*.sql 2>/dev/null | wc -l)"
  echo "[deploy] 完成：$out（当前共 ${count} 份，最多保留 ${BACKUP_KEEP} 份）"
}

backup_cron() {
  local job="30 2 * * * cd $ROOT && bash deploy/deploy.sh backup >> $ROOT/deploy/backup/cron.log 2>&1"
  if crontab -l 2>/dev/null | grep -qF "deploy/deploy.sh backup"; then
    echo "[deploy] 备份 cron 已存在（每日 02:30），未重复安装"
    return 0
  fi
  (crontab -l 2>/dev/null; echo "$job") | crontab -
  echo "[deploy] 已安装每日 02:30 数据库备份 cron（保留最近 ${BACKUP_KEEP} 份，日志 deploy/backup/cron.log）"
}

case "$cmd" in
  up)
    first=0
    if [ ! -f "$ENV_FILE" ]; then
      echo "[deploy] 首次部署：复制 .env.prod.example → .env.prod"
      cp "$ROOT/deploy/.env.prod.example" "$ENV_FILE"
      first=1
    fi
    harden_env "$first"
    ensure_certs
    echo "[deploy] 构建并启动全部服务…"
    compose up -d --build
    echo "[deploy] 等待后端就绪…"
    for i in $(seq 1 40); do
      if curl -kfsS https://localhost/health >/dev/null 2>&1; then break; fi
      sleep 2
    done
    echo "[deploy] 预置数据（幂等，可重复执行）…"
    compose exec -T backend python -m scripts.seed_data || true
    echo "[deploy] 完成：https://localhost  （账号 admin / admin123 或 manager01 / Bt@123456；自签证书请忽略浏览器警告）"
    ;;
  seed)
    compose exec -T backend python -m scripts.seed_data
    ;;
  certs)
    ensure_certs
    ;;
  backup)
    backup
    ;;
  backup-cron)
    backup_cron
    ;;
  status)
    compose ps
    ;;
  logs)
    compose logs -f --tail=100 "${2:-}"
    ;;
  down)
    compose down
    ;;
  destroy)
    compose down -v
    echo "[deploy] 已删除数据卷（含数据库/存储数据）"
    ;;
  *)
    echo "用法: bash deploy/deploy.sh [up|seed|certs|status|logs <服务>|backup|backup-cron|down|destroy]"
    ;;
esac

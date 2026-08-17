# 蓝队业务管理系统 · 后端镜像（FastAPI + uvicorn）
# 健康检查用 Python 标准库，避免额外依赖
# nmap 为真实漏洞扫描的功能硬依赖（-sS 需 root + CAP_NET_RAW，基础镜像默认满足）
FROM python:3.13-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# 可选：国内镜像加速构建，例如 --build-arg PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
ARG PIP_INDEX_URL=https://pypi.org/simple
# 可选：Debian 国内 apt 镜像加速（deb.debian.org 在国内不可达时必须用）。
# 用法：--build-arg APT_MIRROR=http://mirrors.tuna.tsinghua.edu.cn（镜像根，不含 /debian）
#       --build-arg APT_MIRROR=http://mirrors.aliyun.com（阿里云镜像根）
# Dockerfile 自动拼接 /debian（main）与 /debian-security（security）。
ARG APT_MIRROR=

RUN if [ -n "$APT_MIRROR" ]; then \
      sed -e "s|URIs: http://deb.debian.org/debian|URIs: ${APT_MIRROR%/}/debian|" \
          -e "s|URIs: http://deb.debian.org/debian-security|URIs: ${APT_MIRROR%/}/debian-security|" \
          -i /etc/apt/sources.list.d/debian.sources; \
    fi \
    && apt-get update \
    && apt-get install -y --no-install-recommends nmap \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --index-url ${PIP_INDEX_URL} -r requirements.txt

COPY . .

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=3)" || exit 1

# 启动前先执行数据库迁移，再起服务
# 单机部署必须单 worker：WebSocket 连接与 HTTP 请求若被分发到不同 worker 进程，
# 各自独立的内存态 ConnectionManager 无法共享 → WS 实时推送（课程发布/聊天广播）会丢失。
# 如需横向扩容，按 ws/manager.py 文档扩展 Redis Pub/Sub 后再加 worker。
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1"]

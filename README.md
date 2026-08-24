# 蓝队业务管理系统

网络安全公司蓝队（防御方）业务管理系统：**沟通协同、能力培养、资产管控、人员治理**四大能力，零软件授权成本。

> 上游文档：《需求分析与设计报告_v1.0》 / 《详细设计计划_v1.0》 / 《执行计划_v1.0》（位于 `H:\ZPF12\Documents\`）

## 技术栈

| 层 | 技术 |
|---|---|
| 前端 | Vue3 + Vite + Element Plus + Pinia + ECharts |
| 后端 | Python 3.13 / FastAPI / SQLAlchemy 2.0 (async) / Pydantic v2 |
| 数据 | PostgreSQL 16 / Redis 7 / MinIO |
| AI | DeepSeek API（可降级 Ollama，永不抛错） |
| 部署 | Docker Compose + Nginx 反向代理（限流/安全头加固） |

## 目录结构

```
blue-team-system/
├── backend/            # FastAPI 后端
│   ├── Dockerfile      # 生产镜像（alembic 迁移 + uvicorn 单 worker）
│   ├── app/
│   │   ├── core/       # 配置 / 安全 / 异常 / 权限点 / 依赖
│   │   ├── db/         # SQLAlchemy 引擎与会话
│   │   ├── models/     # 全部数据模型（含 training/monitor/audit/leave/网络发现）
│   │   ├── schemas/    # Pydantic 模型
│   │   ├── api/v1/     # auth / users / roles / departments / stats / chat / ai /
│   │   │               # files / training / monitor / audit / leaves / ws 通知
│   │   ├── services/   # scanner(真实nmap) / patrol(巡检) / notify(外部通知) /
│   │   │               # data_scope / audit_log / audit_report / ai_gateway /
│   │   │               # sandbox_service / badge_service / training_generator / leave_status
│   │   └── ws/         # WebSocket 频道聊天 + 全局通知（心跳 / 广播）
│   ├── scripts/        # init_db / seed_data / demo_data / create_admin / reset_data
│   └── tests/          # 单元 + 集成测试（180 个全绿，需 PostgreSQL）
├── frontend/           # Vue3 前端
│   ├── Dockerfile + nginx.conf      # 生产镜像（静态托管 + 反代 /api /ws + 限流加固）
│   └── src/
│       ├── api/        # axios 封装（统一解包 + 401 自动刷新）
│       ├── stores/     # user / permission / menu（动态菜单）/ chat / notifications
│       ├── router/     # 路由 + 权限守卫
│       ├── directives/ # v-permission 按钮级权限
│       └── views/      # 登录 / 五角色首页 / 聊天 / 训练 / 监控 / 审计 / 考勤
└── deploy/
    ├── docker-compose.dev.yml   # 开发基础设施（PG/Redis/MinIO）
    ├── docker-compose.prod.yml  # 单机生产栈（PG/Redis/MinIO/backend/frontend）
    ├── ollama.yml               # 可选：本地 Ollama（AI 降级通道）
    ├── .env.prod.example        # 生产环境变量模板
    ├── deploy.sh                # 部署助手
    ├── start.sh                 # 一键完整启动（Docker→生产栈→公网隧道→健康验证）
    ├── tunnel.sh / tunnel.md    # Cloudflare 公网隧道管理 / 使用说明
    └── security_check.sh        # 安全自检（弱口令/密钥/头泄露/限流）
```

## 快速启动（开发环境）

前置：Docker Desktop（需已启动）、Python 3.11+、Node.js。

```bash
# 1. 启动基础设施（PostgreSQL/Redis/MinIO）
cd H:\ZPF12\Projects\blue-team-system
docker compose -f deploy/docker-compose.dev.yml up -d

# 2. 后端
cd backend
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
copy .env.example .env
.venv\Scripts\python -m scripts.init_db      # 建表
.venv\Scripts\python -m scripts.seed_data    # 5 角色 + 管理员 + 演示账号
.venv\Scripts\uvicorn app.main:app --reload --port 8000

# 3. 前端
cd frontend
npm install
npm run dev        # http://localhost:5173
```

## 默认账号（本地开发）

> **生产部署注意**：首次 `bash deploy/deploy.sh up` 预置数据后，生产环境默认口令已被改密（见下文「安全加固」），下表口令**仅本地开发环境有效**。



账号	角色	新口令
admin	系统管理员	p!$4D_g%U%T?oZk1
manager01	安全主管	*n0zivIFRZp4r&hr
analyst01	安全分析师	hqBA*y%9KPZJAX0z
trainee01	训练学员	xg6Qh6QvR@f-fIY*
trainee02	训练学员	R4uN*XgzOikSN-%5
auditor01	审计员	U$Y$j2f_g2fD&?%O


### 生产环境口令

> 生产库 6 个默认账号的随机强口令**不写入本仓库**（避免公开泄露），保存在 `deploy/.env.prod` 与部署记录中；如需对外分享项目，口令一律放在本地环境变量里。
> 这些字符含 `$`、`&`、`!` 等 shell 特殊字符，命令行中使用务必加单引号包裹。

> **安全提示**：admin 角色强制 MFA，命令行登录会返回 `mfa_required=true`；自动化操作请使用 manager01 等非强制角色账号。

## 已实现功能（全部阶段完成）

| 阶段 | 内容 |
|---|---|
| M1 基础 | 用户 / RBAC / 审计：图形验证码 + 账号锁定 + 防枚举、JWT 轮换 + MFA、数据范围过滤、操作日志只追加、用户 CRUD/导入导出 |
| P2/P3 沟通 | 聊天 IM + AI 网关：频道/私聊/@提及、WebSocket 心跳广播、消息已读/撤回/全文检索、AI 助手（DeepSeek→Ollama→兜底，永不抛错） |
| P4 培养 | 训练中心 + 模拟沙箱：智能体/场景闯关、虚拟文件系统命令、任务判分/扣分、徽章/排行 |
| P5 监控 | 设备（数据范围 CRUD/探测）、IPAM（子网/分配/租约回收/历史追溯）、**真实 nmap** 漏洞扫描 + 告警去重 + **外部通知** + 报告审核闭环 |
| P6 合规 | 审计中心：操作日志聚合统计、合规报告快照生成/导出 CSV |
| 阶段7 治理 | 考勤状态管理：休假/外勤申请 → 审批 → 到点自动切换 |
| 阶段8 AI 课程 | 主题 → DeepSeek 自动生成实训课程 → 编辑器审改 → 发布 → **WebSocket 实时推送在线学员**（NEW 徽标） |
| 监控优化 | 告警去重窗口（24h）、自动巡检（15min 全子网刷新设备状态）、**网络发现**（nmap 主机发现 IP+MAC → 勾选登记终端设备 + 自动建子网） |
| 部门管理 | 组织架构维护：新增 / 编辑 / 删除部门（admin+manager），**删除被引用部门自动拒绝**（有子部门/用户/设备/子网时 409 并提示明细），防循环上级校验 |
| AI 助手会话 | AI 问答**会话持久化**：历史会话列表 / 切换 / 删除，切回页面自动续接上次对话（后端 `ai_conversations` 持久化，最近 10 轮上下文） |

- 认证：登录/刷新/登出、bcrypt、JWT（2h+7d）、连续 5 次失败锁定 15 分钟、MFA（强制角色绑定 TOTP）
- RBAC：角色白名单 + 权限点校验 + 数据范围过滤（all / dept / self 启用，**sub_dept 预留未启用**）+ 按钮级 v-permission
- 5 角色工作台：系统管理员 / 安全主管 / 安全分析师 / 训练学员 / 审计员
- 前端：动态菜单 / 路由守卫 / 401 自动刷新 / WebSocket 实时推送
- **后端测试 180/180 全绿**

## 生产部署（单机 4C8G，Docker Compose）

前置：Docker + Docker Compose v2。

```bash
cd H:\ZPF12\Projects\blue-team-system

# 1. 配置环境变量（含 DeepSeek API Key、数据库口令、JWT 密钥）
cp deploy/.env.prod.example deploy/.env.prod
#    编辑 deploy/.env.prod：
#    DEEPSEEK_API_KEY=sk-你的密钥      ← 接入 DeepSeek 主通道（留空自动降级 Ollama）
#    POSTGRES_PASSWORD=强口令
#    JWT_SECRET_KEY=≥32 字符随机串
#    FRONTEND_ORIGIN=http://<服务器IP或域名>

# 2. 构建 + 启动 + 预置数据（幂等）
bash deploy/deploy.sh up

# 3. 可选：启用本地 Ollama 降级通道
docker compose -p blueteam -f deploy/ollama.yml up -d
docker compose -p blueteam -f deploy/ollama.yml exec ollama ollama pull llama3
```

访问 `https://<服务器IP>`（80 端口自动 301 跳转 HTTPS；自签证书浏览器提示继续即可）。

| 命令 | 作用 |
|---|---|
| `bash deploy/start.sh` | **一键完整启动**：Docker Desktop→生产栈→公网隧道→健康验证→地址汇总 |
| `bash deploy/security_check.sh` | **安全自检**：弱口令/弱密钥/Server 头/安全响应头/IP 限流 |
| `bash deploy/tunnel.sh up\|status\|down` | 公网隧道：启动 / 查地址 / 关闭入口 |
| `bash deploy/deploy.sh up` | 首次部署（构建 + 启动 + 预置数据） |
| `bash deploy/deploy.sh status` / `logs backend` | 服务状态 / 后端日志 |
| `bash deploy/deploy.sh seed` | 重新预置数据 |
| `bash deploy/deploy.sh down` / `destroy` | 停止 / 停止并删除数据卷 |

### 公网访问（Cloudflare Tunnel，免费）

> 详细说明见 [deploy/tunnel.md](deploy/tunnel.md)。解决两个问题：① 外部任何网络可访问系统（无需公网 IP/服务器/路由器配置）；② 登录审计来源 IP 从 Docker 网关地址（172.19.0.1）变为**真实公网 IP**。

```bash
bash deploy/tunnel.sh up       # 启动隧道，打印公网地址 https://xxxxxx.trycloudflare.com
bash deploy/tunnel.sh status   # 查看当前公网地址（隧道重启后地址会变）
bash deploy/tunnel.sh down     # 停止隧道（关闭公网入口）
```

### 漏洞扫描机制

扫描编排：`launch_scan` → 后台任务 `execute_scan`（pending→running→completed/failed）→ 真实 `nmap` 子进程（唯一进程边界）→ XML 解析 → 风险评分 → 告警去重 + 外部通知。

| 能力 | 说明 |
|---|---|
| **扫描选项** | 支持 `scan_type`（`sS` 默认 / `sT` / `sU`）、`top_ports` 端口数、`port_range` 端口范围（如 `22,80,443`、`1-1000`，与端口数二选一，展开上限 `NMAP_MAX_PORTS_IN_RANGE=1024` 防全端口 DoS）、NSE 开关；本次扫描的生效选项快照落 `scan_reports.scan_options`（JSONB） |
| **UDP 扫描** | `sU` 自动使用更小默认端口数（`NMAP_UDP_TOP_PORTS=20`）与更保守超时（`NMAP_UDP_TIMEOUT_SECONDS=300`），避免 UDP 慢速拖垮队列 |
| **真实漏洞检测（NSE）** | 默认挂 `--script vuln`（nmap 自带离线签名，不依赖外网）：解析端口级与主机级 `<script>` 结果，提取 `CVE-XXXX-XXXX`，启发式定级（`ms17-010`/`smb-vuln-*`→critical、含 CVE→high、其余 medium）。与静态端口映射合并，漏洞列表带 `source`（`nse`/`static`）标签区分；`NMAP_NSE_SCRIPTS=""` 可全局关闭，扫描接口的 `nse` 字段可单次关闭 |
| **任务工程化** | 运行中可**取消**（`POST .../cancel`，kill 子进程后落 `failed/cancelled`）；失败可**重试**（`POST .../retry`，沿用原 scan_options 重新排队）；失败原因分类 `error_code ∈ {cancelled, timeout, permission, unreachable, generic}`（权限不足/目标不可达等按 nmap stderr 关键字识别），前端列表与详情可操作 |
| **基线漂移对比** | 同目标同扫描口径（scan_type + 端口规格一致）的两次扫描自动对比，产出 `baseline_diff`：`new_ports`（新增）/`closed_ports`（关闭）/`changed_services`（服务变化），写入本次 `scan_data` 并在摘要提示「与上次扫描相比」；仅提示，**不改变告警阈值** |

### 告警外部通知

扫描 risk≥70 自动建告警 → 后台推送外部渠道，**任一渠道失败静默不影响主流程**，发送成功回写 `alerts.notified_at`（监控中心可看「已通知」）。未配置渠道自动关闭。

| 渠道 | 配置 |
|---|---|
| **飞书（生产已启用）** | `ALERT_NOTIFY_WEBHOOK_URL=https://open.feishu.cn/open-apis/bot/v2/hook/<token>` + `ALERT_NOTIFY_WEBHOOK_TYPE=feishu` |
| 企业微信 / 钉钉 | 同上，URL 换企微/钉钉机器人，`WEBHOOK_TYPE` 分别填 `wecom` / `dingtalk` |
| SMTP 邮件 | `ALERT_NOTIFY_EMAIL_TO` + `SMTP_HOST/PORT/USERNAME/PASSWORD/FROM`（465 SSL） |

配置于 `deploy/.env.prod`，改后需 `docker compose -p blueteam --env-file deploy/.env.prod -f deploy/docker-compose.prod.yml up -d --force-recreate --no-deps backend` 生效。

### 安全加固（Web 渗透防护）

基础防护：SQL 注入（全参数化）、命令注入（无 shell 拼接）、XSS（DOMPurify + CSP）、文件上传白名单、CSRF、JWT 轮换 + MFA、RBAC、扫描目标限制（防 SSRF）、CORS 白名单。

对外暴露公网后追加的加固：

| 层 | 加固项 |
|---|---|
| Nginx 限流 | 登录/验证码 `1r/s` 严格限流、其余 API `15r/s` 一般限流（防暴力破解/撞库/CC），超限统一 JSON `42900`；限流 key 取 XFF 第一个 IP，公网下即真实公网 IP，每 IP 独立计数 |
| Nginx 硬化 | `server_tokens off` 隐藏版本号、请求超时/缓冲上限（防慢速攻击/header 炸弹） |
| 安全响应头 | CSP（含 `upgrade-insecure-requests`）+ `Permissions-Policy` 禁摄像头/麦克风/定位等 + HSTS/nosniff/X-Frame-Options/Referrer-Policy |
| 登录审计 | 账号锁定（连续 5 次失败）事件写入操作日志 `auth:lock`，暴力破解可追溯 |
| 自检脚本 | `bash deploy/security_check.sh` 检查弱口令/弱密钥/头泄露/限流，发现风险退出码非 0 |

**对外发布前必做**：生产环境已为 6 个默认账号改出随机强密码（见安全自检输出）；`deploy/.env.prod` 中 `JWT_SECRET_KEY` 使用 ≥32 字符随机串。改完运行 `bash deploy/security_check.sh` 复核。

### DeepSeek API Key 接入说明

- **位置**：`deploy/.env.prod` 的 `DEEPSEEK_API_KEY`，经 compose `env_file` 注入后端容器。
- **验证**：`docker compose -p blueteam -f deploy/docker-compose.prod.yml exec backend printenv DEEPSEEK_API_KEY`；或在聊天页 AI 助手中提问，消息气泡会显示 provider 徽章 `deepseek`。
- **降级**：密钥留空 / DeepSeek 超时限流 → 自动降级 Ollama → 最终返回占位文案，永不抛错（NFR-004）。
- **本地开发**：密钥写在 `backend/.env` 同名变量即可，无需动生产配置。

> 架构说明：生产栈含 PostgreSQL / Redis / MinIO / backend / frontend(Nginx:443)。Ollama（约需 4-8GB 模型）独立于 `ollama.yml` 按需启用。

## 测试

```bash
cd backend
.venv\Scripts\python -m pytest        # 180/180 全绿
# 集成测试需 PostgreSQL 已启动（docker compose up 后自动运行）
```

## 演示数据

跑一遍 `python -m scripts.demo_data`（幂等，可重复执行）即可为演示填充真实感内容：
聊天故事线消息 / AI 会话 / 学员训练进度+积分+徽章 / 漏洞扫描报告（含一条待审核） / 历史操作日志（审计图表用） / 合规审计报告快照。

```bash
# 开发库
.venv\Scripts\python -m scripts.seed_data && .venv\Scripts\python -m scripts.demo_data
# 生产库（Docker）
bash deploy/deploy.sh seed
docker compose -p blueteam --env-file deploy/.env.prod -f deploy/docker-compose.prod.yml exec backend python -m scripts.demo_data
```

## API 文档

后端启动后访问 http://localhost:8000/docs（OpenAPI 自动生成）。

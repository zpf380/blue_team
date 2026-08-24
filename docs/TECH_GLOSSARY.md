# 蓝队业务管理系统 · 技术名词解释（定义 + 本项目体现）

> 每个术语：**定义**（一句话，面向非该领域的人）+ **本项目体现**（在哪里、怎么用的）。
> 配合 [DESIGN_TECH_DETAILS.md](DESIGN_TECH_DETAILS.md) 看"为什么"。

---

## 一、前端

### Vue3 / Composition API / `<script setup>`
- **定义**：渐进式前端框架；Composition API 用函数组织逻辑；`<script setup>` 是其单文件组件简化写法。
- **本项目**：全部视图用 `<script setup>`；用 `ref/reactive/computed/watch` 管理响应式状态；每个页面一个组件（views/ 按业务分目录）。

### Vite
- **定义**：前端构建工具，基于原生 ESM，开发秒热更、生产打包优化。
- **本项目**：`npm run dev` 开发、`npm run build` 产物 dist/；构建输出按路由分包（chunk >500KB 有警告提示）。

### Element Plus
- **定义**：Vue3 组件库。
- **本项目**：表格/表单/弹窗/树/消息提示全套；`ElMessageBox.confirm` 危险操作确认、`el-tree-select` 部门树选择、`:rules` 表单校验、`el-empty` 空状态。

### Pinia
- **定义**：Vue3 官方状态管理库。
- **本项目**：按域分 5 个 store——`user`（登录态/用户信息）、`permission`（权限点集合）、`menu`（动态菜单生成）、`chat`（消息/WS 连接）、`notifications`（全局事件）。

### Vue Router + 路由守卫
- **定义**：前端路由；守卫在跳转前拦截做逻辑。
- **本项目**：每次导航同步权限 → 生成动态菜单；未登录 → `/login`、无权限 → `/403`、未知路径 → `/404`。

### axios（HTTP 客户端 + 拦截器）
- **定义**：Promise 化 HTTP 库，拦截器可在请求/响应前后统一处理。
- **本项目**：`api/http.js` 统一 baseURL + Cookie；请求拦截器给写操作加 `X-Requested-With`（CSRF 配套）；响应拦截器解包 `{code,message,data}` + **401 自动刷新重试**。

### ECharts
- **定义**：可视化图表库。
- **本项目**：角色工作台/训练统计/审计图表——告警趋势、能力雷达、角色分布、30 天学习曲线。

### 自定义指令 v-permission
- **定义**：Vue 指令，绑定元素做自定义逻辑。
- **本项目**：`v-permission="'monitor:device:manage'"` 按后端权限点显隐按钮，与后端同名权限点对齐。

### SPA（单页应用）
- **定义**：整个应用一个 HTML 入口，路由在浏览器切换。
- **本项目**：前端容器 nginx 需要 SPA 回退（`try_files $uri /index.html`），否则刷新子路由 404。

### sessionStorage（本地会话存储）
- **定义**：浏览器按标签页隔离的存储。
- **本项目**：存访问令牌——之前用 localStorage 导致多标签页登录互相串号，改 sessionStorage 天然按标签页隔离。

### HttpOnly Cookie
- **定义**：只能由服务器读写、JS 不可读的 Cookie，防 XSS 窃取。
- **本项目**：access/refresh 令牌放 HttpOnly Cookie，同源请求自动携带，前端无感知轮换。

---

## 二、后端框架

### FastAPI
- **定义**：Python 异步 Web 框架，类型标注即自动校验与生成 OpenAPI 文档。
- **本项目**：所有 API 用它；`APIRouter` 按域拆模块；`Depends` 注入 session/当前用户/权限；`/docs` 自动文档。

### ASGI / Uvicorn
- **定义**：Python 异步服务器网关协议/实现服务器。
- **本项目**：生产 uvicorn 跑 FastAPI，`--workers 1`（WS 连接表是进程内存，多 worker 会丢事件）。

### Pydantic v2
- **定义**：Python 数据校验库，类型声明即运行时校验。
- **本项目**：Create/Update/Out schema 分层；`EmailStr` 拒空串、`Field(pattern=...)` 校验枚举、`model_dump(exclude_unset=True)` 区分"未提交/显式置空"。

### SQLAlchemy 2.0（async ORM）
- **定义**：Python ORM，2.0 支持原生 async。
- **本项目**：全异步 `AsyncSession` + `select()`；模型分六域（user/chat/monitor/training/leave/audit）；JSONB/INET/DateTime(tz) 列。

### Alembic（迁移）
- **定义**：数据库 schema 版本管理工具。
- **本项目**：每个模型变更一个迁移，生产容器启动 `alembic upgrade head` 自动建表/加列。

### 依赖注入（Depends）
- **定义**：由框架提供函数依赖参数，而非手动创建。
- **本项目**：`Depends(get_db)` 注入数据库会话、`Depends(get_current_user)` 鉴权、`Depends(require_permission(...))` 权限校验——**接口签名即安全声明**。

### 中间件（Middleware）
- **定义**：请求进入路由前/响应返回后统一处理的钩子。
- **本项目**：`access_log_middleware` 记录每个 HTTP 请求的 method/path/status/duration/ip 为 JSON 日志。

### lifespan
- **定义**：FastAPI 应用启动/关闭的生命周期钩子。
- **本项目**：启动时挂后台调度器（巡检/租约回收/休假切换）+ 清扫遗留的扫描任务（pending→failed）。

### asyncio / 事件循环
- **定义**：Python 异步 IO 运行时，单线程并发。
- **本项目**：DB/AI 调用/扫描全部异步；事件循环不被阻塞。

### 后台任务 asyncio.create_task
- **定义**：在事件循环中并发调度一个协程。
- **本项目**：nmap 扫描/巡检/课程 WS 推送用 `create_task` + **模块级任务引用表**（防任务被 GC 回收导致静默中断）。

### WebSocket
- **定义**：全双工实时通信协议。
- **本项目**：`/ws/chat/{id}` 聊天（30s 心跳）+ `/ws/notifications` 全局事件（课程发布实时推送学员）。

---

## 三、认证与安全

### JWT（JSON Web Token）
- **定义**：无状态签名令牌。
- **本项目**：access 2h + refresh 7d **轮换**；改密/登出吊销 refresh；HttpOnly Cookie 存储。

### bcrypt（口令哈希）
- **定义**：带盐的慢哈希算法，抗彩虹表/暴力。
- **本项目**：用户口令 `hash_password` 存储；生产改密用后端容器内脚本直写库（强制 MFA 账号无法走 API 改密）。

### TOTP / MFA（多因素认证）
- **定义**：基于时间的一次性密码。
- **本项目**：admin 强制 MFA，`totp_secret/totp_confirmed_at` 落库，扫码绑定后登录需动态码。

### CAPTCHA（图形验证码）
- **定义**：人机校验。
- **本项目**：Redis 存码（TTL 300s），登录失败达 2 次才要求——平时不打扰、遇暴力才加码；校验即删（一次性）。

### 账号锁定
- **定义**：连续失败后临时冻结账号。
- **本项目**：5 次失败锁 15min + 写 `auth:lock` 审计留痕。

### CSRF（跨站请求伪造）
- **定义**：诱导已登录用户发送恶意请求的漏洞。
- **本项目**：写请求前端带 `X-Requested-With` 自定义头，后端 refresh/logout 强制校验（跨域站点无法带该头）。

### XSS（跨站脚本）
- **定义**：注入脚本窃取信息/篡改页面。
- **本项目**：消息渲染走 DOMPurify 清洗 + CSP `script-src 'self'` + 令牌 HttpOnly 使 JS 无法窃取。

### SQL 注入
- **定义**：把输入拼进 SQL 执行。
- **本项目**：全参数化（SQLAlchemy 绑定参数），无字符串拼 SQL。

### 命令注入
- **定义**：把输入拼进系统命令执行。
- **本项目**：nmap 子进程**无 shell**（参数列表直传），扫描目标限制为已登记网段。

### SSRF（服务端请求伪造）
- **定义**：诱导服务器访问内网/本地资源。
- **本项目**：扫描目标仅限 IPAM 已登记网段，防扫描内网元数据服务。

### CORS（跨域资源共享）
- **定义**：浏览器跨域访问策略。
- **本项目**：后端白名单允许来源（同源前端 + 配置域名），防跨域读取。

### Rate Limiting（限流）
- **定义**：限制请求频率防暴力/CC。
- **本项目**：nginx 登录 1r/s、API 15r/s；**限流 key 取 XFF 真实 IP**（Docker 网关下 remote_addr 恒为网关 IP，否则全站共享一个桶）。

### RBAC（基于角色的访问控制）
- **定义**：按角色授予权限点。
- **本项目**：角色 → permissions JSONB 白名单；接口 `require_permission` + 前端按钮级 `v-permission`。

### 数据范围过滤（Data Scope）
- **定义**：同一权限下按数据归属限制可见行。
- **本项目**：all/dept/self 三级；analyst 只看本部门设备/告警/报告；列表和详情双端应用（防越权）。

### 统一错误码 / AppError
- **定义**：业务异常统一编码。
- **本项目**：`AppError` → HTTP 200 + `{code,message,data}`（40001/40100/40301/40302/40400/40900/42900/50000），前端按业务码处理（40100 自动刷新）。

### 审计日志（Operation Log）
- **定义**：记录"谁在何时做了什么"的不可篡改日志。
- **本项目**：operation_logs 表 + PostgreSQL RULE **防删防改**；全关键操作 `record()` 落库；审计中心可查/可导出。

---

## 四、数据库与存储

### PostgreSQL
- **定义**：开源关系数据库。
- **本项目**：主库；用 JSONB（灵活字段）、INET（IP 列）、ILIKE（中文检索）、RULE（防篡改）、事务。

### JSONB
- **定义**：PG 的二进制 JSON 列，可索引查询。
- **本项目**：角色权限白名单、子网保留段、扫描主机表、AI 会话上下文。

### INET
- **定义**：PG 的 IP 地址类型，支持网络运算。
- **本项目**：设备 IP/告警目标 IP 列；拒绝非法 IP/十六进制。

### ILIKE 全文检索
- **定义**：不区分大小写的模糊匹配。
- **本项目**：聊天消息中文检索用 `ILIKE` 兜底（PG 原生全文检索对中文分词不可靠）。

### RULE（规则）防篡改
- **定义**：PG 的改写规则，拦截 SQL。
- **本项目**：`prevent_delete_oplog / prevent_update_oplog`（DO INSTEAD NOTHING）——审计链底层不可篡改。

### 软删 vs 物理删
- **定义**：标记删除（保留行）vs 真正删除（删行）。
- **本项目**：子网 `is_active=False`、用户 archived（保 FK/审计链）；无引用的才物理删。

### Redis
- **定义**：内存键值存储。
- **本项目**：图形验证码（TTL 300s 一次性）、轻量缓存（cache.py）；不存聊天消息（消息落 PG，职责单一）。

### MinIO（对象存储）
- **定义**：S3 兼容的对象存储。
- **本项目**：文件二进制存对象、DB 存元数据；返回**签名 URL**（预签名临时链接）；对象 key 按用户分区 `chat/{uid}/{uuid}.ext`。

### 事务
- **定义**：一组操作要么全成要么全败。
- **本项目**：登记设备+分配+建子网单事务；删除/状态切换与审计记录同 commit。

---

## 五、AI 相关

### LLM（大语言模型）
- **定义**：海量文本训练的大规模语言模型。
- **本项目**：DeepSeek 模型承担问答与课程生成。

### DeepSeek / Ollama
- **定义**：云上 LLM API / 本地私有模型服务。
- **本项目**：主通道 DeepSeek（生产配 Key 实测返回）、本地降级通道 Ollama；`provider` 徽章展示用的是哪个。

### 多通道降级（Fallback）
- **定义**：主服务失败时自动切换备用服务。
- **本项目**：`AIGateway.chat` 按 DeepSeek→Ollama→兜底文案逐级降级，**永不抛错（NFR-004）**。

### 提示词工程（Prompt Engineering）
- **定义**：设计给 LLM 的指令以稳定产出。
- **本项目**：课程生成指令全放 user 消息 + 严格 JSON 格式约束（`build_course_query`）。

### 上下文窗口 / 上下文管理
- **定义**：LLM 单次可处理的输入范围；管理其长度/成本。
- **本项目**：会话最近 10 轮上下文（`context_messages`），`trim_history` 截断；聊天与课程超时分层（30s/90s）。

### 幻觉（Hallucination）
- **定义**：LLM 一本正经生成错误内容。
- **本项目**：课程 JSON 用**括号平衡解析**（抗截断/包裹）+ **命令白名单硬校验** + 人工审改才发布——三层防幻觉。

### 超时（Timeout）
- **定义**：请求超过时限视为失败。
- **本项目**：AI 30s/90s 分层 + nginx 精确匹配放宽长请求（曾 60s 掐断导致 504）。

---

## 六、安全工具与协议

### nmap
- **定义**：网络扫描工具。
- **本项目**：漏洞扫描（`-sS` 半开 SYN + `-sV` 服务版本探测）+ 主机发现（`-sn` LAN ARP）。

### -sS / -sV / -sn
- **定义**：nmap 扫描模式——SYN 半开扫描 / 服务版本探测 / 主机发现。
- **本项目**：`_build_nmap_cmd` 纯函数拼参数（曾把 `-sS` 拼成 `-ssS`，纯函数+单测固化）。

### CVE / 漏洞研判
- **定义**：公开漏洞编号 / 对开放服务定性风险。
- **本项目**：端口规则 → 服务名规则（40+）→ product 子串三层定性，每端口至多一条，CVE 宁缺毋滥。

### 风险分（Risk Score）
- **定义**：把开放端口/漏洞量化成风险数值。
- **本项目**：`_compute_risk_score` 计算；risk≥70 自动建告警。

### 心跳（Heartbeat）
- **定义**：定期发小包保活/检测连接。
- **本项目**：WS 客户端 30s ping / 服务端 pong，超时清理断线连接。

### X-Forwarded-For（XFF）
- **定义**：HTTP 头，记录代理链上真实来源 IP。
- **本项目**：nginx 限流 key + 后端登录审计取 XFF 第一个 IP（Docker 网关/CF 隧道下拿真实客户端 IP）。

### HTTP 动词与 REST
- **定义**：GET/POST/PUT/DELETE 语义化接口。
- **本项目**：CRUD 按动词设计；DELETE 不依赖 body（reason 走 query，nginx 下 DELETE+body 会 500）。

### 429（限流状态码）
- **定义**：请求过多被拒。
- **本项目**：nginx 限流超限返回统一 JSON `{"code":42900}`。

### WebSocket 升级
- **定义**：HTTP 升级到双向连接（101）。
- **本项目**：nginx 反代 `/ws` 需配置 Upgrade/Connection 头，冒烟验证 101。

---

## 七、部署与运维

### Docker / Docker Compose
- **定义**：容器化 / 多容器编排。
- **本项目**：单机栈 postgres/redis/minio/backend/frontend；backend healthcheck 用 Python urllib（镜像不带 curl）；CN 网络用清华/阿里镜像加速构建。

### Nginx（反向代理）
- **定义**：接收外部请求转发的 Web 服务器。
- **本项目**：反代 `/api` `/ws`、强制 HTTPS、限流、安全响应头、SPA 回退、静态资源缓存——五重职责。

### TLS / HTTPS（自签证书）
- **定义**：传输加密；自签 = 未受第三方信任机构签发。
- **本项目**：openssl 生成自签证书 + 80 端口 301 跳 443；浏览器提示"继续访问"。

### Cloudflare Tunnel
- **定义**：由容器**出站**建立到 CF 边缘的隧道，免公网 IP 暴露内网。
- **本项目**：`cloudflared` 容器 `tunnel --url https://frontend`；公网 `https://<random>.trycloudflare.com`；审计来源 IP 真实化。

### Health Check（健康检查）
- **定义**：探针确认服务存活。
- **本项目**：backend `/health`（Python urllib），容器 unhealthy 自动重启；start.sh 校验本机+公网可达。

### CIDR / 子网 / IPAM
- **定义**：无类别域间路由（如 10.99.60.0/24）/ 网段划分 / IP 地址管理。
- **本项目**：IPAM 模块建子网、重叠检测、保留段、自动分配、租约回收、usage 热图、VLSM 拆分。

### DHCP / 租约
- **定义**：动态地址分配协议 / 地址使用期限。
- **本项目**：IP 分配 type=static/dhcp/reserved；过期 DHCP 租约惰性回收 + 后台定时 + 手动三种触发。

### Cron（定时任务）
- **定义**：按计划周期执行任务。
- **本项目**：`deploy.sh backup-cron` 每日 02:30 pg_dump 备份（保留 N 份 + 完整性校验）。

### 冒烟测试（Smoke Test）
- **定义**：发布后对核心链路快速验证。
- **本项目**：`smoke.sh` 24/24 + 各专项（课程 WS 21/21、考勤 14/14、巡检 22/22、AI 会话 10/10）。

### 幂等（Idempotent）
- **定义**：重复执行结果一致。
- **本项目**：seed 预置数据幂等（按 name/code 匹配存在则跳过，自愈去重）；demo 数据可重复跑。

---

## 八、业务领域术语

| 术语 | 定义 | 本项目体现 |
|---|---|---|
| 蓝队 | 防御方安全团队 | 系统的目标用户 |
| RBAC 角色 | 安全主管/分析师/学员/审计员/管理员 | 五角色权限矩阵 |
| 数据范围 dept/self | 按部门/个人隔离数据 | analyst 只见本部门资产 |
| 漏洞扫描闭环 | 扫描→研判→告警→通知→审核 | 报告确认后风险分才生效 |
| 幽灵设备 | 网络在线但台账未登记 | 巡检/发现自动识别 |
| 合规报告 | 按周期聚合的审计快照 | 审计中心生成/CSV 导出 |

---

> 配套文档：[AI_PROJECT_REPORT.md](AI_PROJECT_REPORT.md) · [INTERVIEW_NOTES.md](INTERVIEW_NOTES.md) · [DESIGN_TECH_DETAILS.md](DESIGN_TECH_DETAILS.md)

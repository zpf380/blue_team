# 蓝队业务管理系统 · 功能设计逻辑与技术应用深度解析

> 从"为什么这么设计"的角度逐模块拆解全部功能，并说明每项技术在本项目中的具体用法与选型理由。
> 代码位置均给出（backend 根为 `H:\ZPF12\Projects\blue-team-system\backend`，前端为 `...\frontend\src`）。

---

# 第一部分 · 功能设计逻辑

## 1. 认证与账号安全（`app/api/v1/auth.py` + `app/core/security.py` + `app/services/mfa.py`）

**设计目标**：在"公网可达、防渗透"的前提下提供易用的登录体验。

| 环节 | 设计逻辑 |
|---|---|
| 图形验证码 | 失败达 `CAPTCHA_THRESHOLD=2` 次后要求验证码（Redis 存码 TTL 300s）——**平时不打扰，遇暴力尝试才加码**，平衡体验与安全 |
| 账号锁定 | 连续 5 次失败锁 15min + 写 `auth:lock` 审计——防止撞库，且违规行为可追溯 |
| 防枚举 | 登录失败统一返回同一文案，不区分"用户不存在/密码错误"；MFA 强制角色单独提示 |
| JWT 轮换 | access 2h + refresh 7d，HttpOnly Cookie 存（JS 不可读防 XSS）；改密/登出吊销 refresh |
| CSRF 双校验 | 所有写请求前端带 `X-Requested-With`，后端 refresh/logout 强制校验该头（`_require_xhr`） |
| MFA | admin 强制 TOTP（`MFA_FORCE_ROLES=["admin"]`），`totp_secret/totp_confirmed_at` 落库；强制角色不可自助解绑 |
| 前端 401 自动刷新 | 后端 `AppError` 统一返回 **HTTP 200 + code**，前端拦截器同时捕获 HTTP 401 与业务码 40100，刷新令牌后重试一次（并发 401 用共享 Promise 防重复刷新） |

**设计要点**：整个认证走**"Cookie 优先"**——刷新令牌也在 HttpOnly Cookie，前端无感知完成轮换。

## 2. RBAC 权限 + 数据范围（`app/core/permissions.py` + `app/services/data_scope.py`）

**两层隔离**：纵向（角色权限点）+ 横向（数据行范围）。

- 角色 → `permissions` JSONB 白名单；每个接口 `require_permission("monitor:device:manage")` 校验；前端按钮级 `v-permission` 指令同样按权限点显隐。
- 数据范围 3 级：`all`（admin/manager 全量）/ `dept`（analyst 只看本部门）/ `self`（只看自己）。
  - `apply_data_scope` 在**列表和详情**都应用（曾漏 `get_device` 导致越权，已补）——设计原则是"**每个查询入口都要过范围过滤，不能只信列表端点**"。
- 越权语义区分：有权限但超范围 = 40301；无权限操作 = 40302。

## 3. 用户与部门管理（`users.py` / `departments.py`）

- 用户 CRUD + 批量导入（xlsx/csv，逐行报错不整批失败）+ 导出（UTF-8 BOM 兼容 Excel）。
- **自我保护**：不能禁用/删除自己。
- **最后管理员保护**：系统始终至少 1 名有效管理员，第二管理员可降级第一，但不可自降。
- **删除引用保护**：删除用户/部门前统计所有引用（设备 owner、频道 creator、消息 sender、分配、扫描报告等），任一非零 → 40900 + `data=refs` 明细。
- 部门树：循环上级检测（PUT 父级落在自身/后代 → 40900）、被引用（子部门/用户/设备/子网）拒绝删除。

## 4. 聊天 IM（`channels.py` + `ws/manager.py` + `stores/chat.js`）

**设计目标**：安全的内部协同 + 角色隔离。

- 频道类型 `public / private / trainee`；`_get_channel` 是统一闸口——**所有读取/发送都过它**。
- 角色隔离（核心设计）：
  - trainee 仅可与其他学员私聊（单向限制：非学员可主动找学员，学员不可主动找非学员）；
  - 学员公共空间只有「学员社区」频道（seed 扩员实现跨角色群聊）；
  - **admin 全量监控**：可见并读取任意频道（含他人私聊）。
- 消息能力：已读/撤回/全文检索（中文用 `ILIKE` 兜底，PostgreSQL 原生 `to_tsvector` 对中文分词不可靠）、@提及计数徽标。
- **WebSocket 心跳**：客户端 30s ping，服务端 pong，超时清理连接——保活 + 断线检测。
- 联系人（DM）：候选列表按角色过滤；学员只能看到学员。
- 系统消息（加入/离开等）单独渲染分支，不占业务消息数。

## 5. AI 助手（`ai.py` + `services/ai_gateway.py` + `AIAssistant.vue`）

- `POST /ai/invoke` 带 `conversation_id` 续接，后端加载 `ai_conversations.context_messages` 最近 **10 轮**上下文。
- 会话持久化：表存 `title=首条提问预览 / message_count / updated_at`；前端左右两栏会话列表，**切回页面自动续接**。
- 隔离：续接他人/频道内会话一律 **40400（不泄露存在性）**。
- `regenerate` 复用会话续接，语义为"追加新回复"（完整记录每轮提问）。
- 降级：DeepSeek → Ollama → 兜底文案，`provider` 徽章展示（详见技术部分 12）。

## 6. 训练中心 + 模拟沙箱（`training.py` + `sandbox_service.py`）

- 智能体/场景：AI 生成或内置，闯关式完成。
- **沙箱 = 零成本仿真**：不建真实容器，基于场景预置的**虚拟文件系统**（`build_virtual_fs`）模拟 Linux 终端，支持 `ls/cat/grep/head/tail`。
- **判分引擎**（`_matches`）：任务命中 = `check.cmd`（命令）∩ `pattern/args`（参数）∩ `output_contains`（输出内容），三类组合；`calc_final_score` 提交结算（全完成且无扣分 = completed，否则 failed）。
- 会话治理：`start_scenario` 旧会话置非活跃、每人活跃会话上限；提交校验会话活跃 + agent 仍 published。
- 配套：积分、徽章（`badge_service.py`，7 类）、排行榜、训练统计（30 天学习曲线）。

## 7. AI 课程生成 + 发布 + WS 推送（`training_manage.py` + `training_generator.py` + `training_notify.py`）

**全自动流水线但带人工闸门**：

```
主题 → build_course_query（严格 JSON 指令）→ DeepSeek(90s 超时)
→ extract_json（括号平衡兜底，抗截断/包裹 markdown）
→ validate_course（命令白名单 + id 唯一 + 结构硬校验）
→ 编辑器审改 → publish → WS push_course_published → 在线学员实时收到（NEW 徽标 ≤7 天）
```

- 发布态守卫：draft→published→draft 状态机；已发布课程的编辑需重新发布才生效。
- 学员侧只读 published；生成失败（AI 不可用/校验不过）返回友好错误不落脏数据。
- 长请求单独 `AI_COURSE_TIMEOUT_SECONDS=90` + nginx 精确匹配 `proxy_read_timeout 180s`。

## 8. 设备监控（`monitor.py` 设备段 + `services/patrol.py`）

- 设备 CRUD 全走数据范围；`ping_device` 真实探测刷新状态。
- **自动巡检**：后台每 15min 全子网 nmap 探测，比对台账得三态——`在线 / 离线（offline_since 落值）/ 幽灵`（在线未登记）。
- 离线判定：未响应且非 maintenance/archived → `offline_since` 首次判定落值，前端红字「离线自 xxx」。
- 导出（xlsx/csv 中英双表头兼容）+ 导入逐行校验。

## 9. IPAM 地址管理（`monitor.py` IPAM 段）

- **子网正确性**：重叠/嵌套检测（遍历 active 网段 `net.overlaps`）、仅内网网段可登记、网关格式校验。
- **分配管理**：自动分配跳过网关+保留段、静态/保留/过期 DHCP 惰性回收、编辑、历史追溯（查操作日志 detail 的 ip 字段）。
- **保留段**：`reserved_ranges` JSONB（CIDR 归一化 + subnet_of 校验）。
- **规划能力**：usage 热图（含分配明细）、VLSM 拆分（前端计算 + 批量建）。
- **删除保护**：被分配引用的子网 40900（"子网下仍有 N 条地址分配"）；子网软删保留历史。

## 10. 网络发现（`scanner.py` discovery 段）

- 复用 nmap `-sn` 主机发现（LAN 走 ARP，无需 root）→ 比对台账得在线未登记（幽灵）/在线已登记/离线三组。
- `hosts` JSONB 存 `[{ip,mac,vendor}]`；登记 = 建 Device + DHCP 分配 + 自动复用/创建子网（掩码固化进台账）。
- **半自动**：勾选确认才登记，不误写临时设备；防篡改（按 IP 反查 hosts 的 MAC）。
- 限制：网段 >1024 地址（/22 以上）拒；历史对全量用户可见、部门范围用户过滤。

## 11. 漏洞扫描 + 研判（`scanner.py` scan 段）

- **真实 nmap**：`-sS -Pn --open --top-ports N [-sV]` 后台异步任务，报告 `scan_status`（pending/running/completed/failed），前端 2s 轮询。
- 三层研判 `_derive_vulnerabilities`：端口规则 → 服务名规则（40+）→ product 子串 → info 兜底；每端口至多一条，CVE 宁缺毋滥。
- 风险分 `_compute_risk_score`；risk≥70 自动建告警（24h 去重窗口同 IP+type）。
- **审核闭环**：报告需 manager/admin 审核（confirmed/suspected/exposure），审核后才算数；目标仅限已登记网段（防 SSRF）；服务重启遗留任务置 failed。
- `scan_policy.py`：扫描目标策略（网段归属校验）。

## 12. 告警与外部通知（`monitor.py` 告警段 + `services/notify.py`）

- Alert 生命周期：open → acknowledged → resolved；创建校验 device 存在。
- 扫描自动告警 + 外部推送：飞书（生产启用）/企微/钉钉/SMTP，`_send_webhook` 按渠道差异 payload。
- **失败静默**：任一渠道失败不影响主流程，发送成功回写 `alerts.notified_at`（前端可见「已通知」）。

## 13. 审计中心（`audit.py` + `services/audit_log.py` / `audit_report.py`）

- `operation_logs` 表 + PostgreSQL RULE **防删防改**（DO INSTEAD NOTHING）——审计链不可篡改。
- 所有关键操作 `record(session, user, action, target_type, target_id, detail, ip, ua)` 落库。
- 合规报告：按时间窗口聚合统计（登录/操作/越权/告警）→ 快照 → CSV 导出，仅 admin/auditor。

## 14. 考勤状态机（`leaves.py` + `services/leave_status.py`）

- `LeaveRequest` 状态机：`pending → approved → in_progress → completed`；`pending → rejected/cancelled`。
- **到点自动切换**：后台 5min 一轮，先结束到期 in_progress（仅当 user.status==leave_type 才恢复 active），再开始到期 approved（仅 active 才切）——**不覆盖 disabled/archived**。
- 约束：请假不可重叠、end>start、不可审批自己、只审批 pending。
- 复用 `User.status` 值（on_leave/business_trip），聊天 WS 白名单天然处理外勤不可聊。

## 15. 角色工作台（`stats.py` + 5 个 dashboard 视图）

`GET /stats/workspace` 按角色聚合返回不同字段（权限即数据）：
- manager：待审报告 / 未解决告警 / 待批请假 / 训练排行 Top / 合规状态
- analyst：未处理告警 / 本部门告警 / 我的设备 / AI 会话数
- trainee：能力总分 / 徽章数 / 完成场景 / 30 天学习天数
- auditor：今日操作数 / 异常事件 / 合规状态 / 待核查
- admin：`/stats/overview` 全量总览（用户/角色分布/部门）

## 16. 文件服务（`files.py`）

- 扩展名白名单 + MIME 软校验 + 大小限制（入配置）；存 MinIO，返回签名 URL。
- `FileRecord` 表记录（user/filename/object_key/url/size/mime）；上传写审计。

---

# 第二部分 · 技术应用逻辑

## 1. Python / FastAPI（异步全链路）

**应用逻辑**：
- **模块化路由**：`APIRouter` 按域拆分（auth/users/roles/departments/stats/chat/ai/files/training/monitor/audit/leaves），`router.py` 统一挂 `/api/v1`。
- **依赖注入**：`Depends(get_db)` 注入 async session、`Depends(get_current_user)` 解析令牌、`Depends(require_permission(...))` 组合鉴权——**权限即函数参数**，接口签名即安全声明。
- **统一异常**：`AppError` 携带错误码，异常处理器统一转 **HTTP 200 + `{code,message,data}`**（业务码比 HTTP 状态更精细，40100/40302/40900/40400/42900...）；并注册 `IntegrityError/DataError` 兜底防裸 500。
- **中间件**：`access_log_middleware`（JSON 访问日志）。
- **lifespan**：启动时挂后台调度器（巡检/租约/休假切换）+ 清扫遗留扫描任务。
- **后台任务**：nmap 扫描用 `asyncio.create_task` + **模块级任务引用表防 GC 回收**（进程内持有引用，否则任务会被垃圾回收静默中断）。

## 2. SQLAlchemy 2.0 async + Pydantic v2

**应用逻辑**：
- 全异步 ORM：`AsyncSession`、`select()` 链式、`scalar_one_or_none()` 必须整体括号（`await (session.execute(...)).scalar_one_or_none()`）。
- **模型分层**（models/）：user / chat / monitor / training / leave / audit 六域；用 `JSONB`（permissions/reserved_ranges/hosts/context_messages）、`INET`（IP 列，拒绝十六进制）、`DateTime(timezone=True)` 统一 UTC。
- **Alembic 迁移**：每次模型变更独立迁移，生产 `alembic upgrade head`。
- **软删 vs 物理删**：业务上要留痕的（用户归档、子网 is_active=False）软删，防 FK 链断裂。
- Pydantic v2 **schemas 分层**：Create/Update/Out 分离；`model_dump(exclude_unset=True)` 区分"未提交"与"显式置空"（部门 parent_id 显式 null = 移到根）；`Field(pattern=...)` 做枚举/格式校验；`EmailStr` 拒空串（前端空字段必须转 null）。

## 3. PostgreSQL 16

**应用逻辑**（不只是"存数据"）：
- **只追加审计**：用 RULE 实现防删防改，比应用层锁更底层、不可绕过。
- **中文全文检索**：`ILIKE` 兜底（原生全文检索对中文分词不可靠），配合索引。
- **JSONB 灵活字段**：权限白名单、子网保留段、扫描主机表、AI 会话上下文。
- **聚合统计**：`func.count()`/去重/窗口函数（seed 自愈去重 rn>1）。
- 生产 + 测试双库：compose 无 host 端口映射（生产只能容器内访问），pytest 连独立本地测试库，隔离干净。

## 4. Redis 7

**应用逻辑**：
- **图形验证码**：`captcha:{id}` 存码，TTL 300s，校验即删（一次性）。
- **缓存服务**（`services/cache.py`）：轻量缓存封装。
- **限流**：生产放 nginx（应用层不再重复）；开发环境验证码等也依赖 Redis。
- 不承载聊天消息（消息落 PG，WS 只做实时通道）——职责单一。

## 5. MinIO（对象存储）

**应用逻辑**：
- 文件二进制存对象，DB 只存元数据（filename/object_key/url/size/mime）——分离存储，DB 保持轻量。
- 懒加载客户端（`_client()` 首次用时建）——不占用启动资源。
- 返回**签名 URL**（预签名临时链接），桶 `blueteam-files`，对象 key `chat/{user_id}/{uuid}.{ext}` 按用户分区。
- 生产依赖坑：requirements 曾缺 `minio` 包 → 上传 500（开发 .venv 有包未暴露），补齐并重建镜像。

## 6. Vue3 `<script setup>` + Composition API

**应用逻辑**：
- 组合式 API 组织逻辑：响应式 `ref/reactive`、`watch`、`computed`；每个视图一个组件（views/ 按业务目录）。
- **动态菜单**（`stores/menu.js`）：`ALL_MENUS` 常量树 + `generateMenus(permissions)` 按权限点过滤——**必须深拷贝再 filter**（曾因浅拷贝污染共享源导致菜单只剩一项）。
- 路由守卫（`router/index.js`）：每次导航同步 `permissionStore` + 动态菜单；未登录/未知角色 → /login；无权限 → /403；未知路径 → /404。

## 7. Element Plus + Pinia + v-permission

- **ElMessageBox.confirm 危险操作确认**（resolve 告警/删除会话/放弃未保存编辑等）。
- **表单校验 `:rules`**：函数式 rules（编辑时密码可选）、`el-tree-select` 必须显式 `value:'id'`、IP/CIDR 自定义 validator。
- **Pinia 按域分 store**：user（令牌/用户信息）、permission（权限点）、menu（菜单）、chat（消息/连接）、notifications（WS 事件）。
- **token 存 sessionStorage**（按标签页隔离）——曾用 localStorage 导致多标签登录串号。
- `v-permission` 指令：元素级权限显隐，与后端权限点同名。

## 8. axios 拦截器（`api/http.js`）

**这是前端的核心枢纽**：
- 统一 baseURL `/api/v1` + `withCredentials`（Cookie 自动携带）。
- **请求拦截器**：非 GET 自动加 `X-Requested-With: XMLHttpRequest`（CSRF 配套）。
- **响应拦截器解包**：`{code,message,data}` → 只返回 `data`；`code!==0` 弹错误。
- **401 自动刷新**：捕获 HTTP 401 与业务码 40100（`!== /auth/login` 且未重试）→ 调 refresh → 重试原请求一次；并发 401 共享同一 Promise（`refreshing` 变量防风暴）。
- 刷新本身用独立 axios（不递归拦截器）。

## 9. WebSocket（`ws/manager.py` + `stores/chat.js`）

- 两条通道：`/ws/chat/{channel_id}`（聊天，心跳 30s）+ `/ws/notifications`（全局事件，按权限鉴权，manager 无 `training:agent:view` 天然 4403 不连）。
- **心跳机制**：客户端定时 ping，服务端 pong；连接表逐连接容错（一个连接异常不影响广播）。
- **全局广播** `_globals`：课程发布等跨频道事件推给所有在线目标角色。
- **核心约束：单 worker（uvicorn `--workers 1`）**——内存 ConnectionManager 跨进程不共享，多 worker 下事件会发到空表丢失；单机内存直推必须单进程（扩展需 Redis Pub/Sub）。

## 10. Docker Compose + Nginx

- **Compose 单机栈**：postgres/redis/minio/backend/frontend；backend healthcheck 用 Python urllib（镜像不带 curl）；构建用清华/阿里镜像加速（CN 网络）。
- **Nginx 五重职责**：① 反代 `/api` 与 `/ws`（WebSocket 升级头）；② HTTPS（自签证书 + 强制 301）；③ **限流**（登录 1r/s、API 15r/s，key 取 XFF 第一个 IP——Docker 网关下 remote_addr 恒为 172.19.0.1，用 remote_addr 会全站共享一个桶）；④ **安全响应头**（CSP/HSTS/nosniff/X-Frame-Options/Referrer-Policy/Permissions-Policy）；⑤ SPA 回退 + 静态资源缓存（index.html no-cache、/assets/ immutable）。
- **两个 nginx 生产坑**：`add_header` 继承陷阱（自定义 add_header 的 location 会遮蔽 server 级安全头，需重 include）；长请求 `proxy_read_timeout 60s` 掐断 AI 生成，需精确 location 放宽。
- **CF Tunnel**：cloudflared 容器出站建隧道，公网 `https://<random>.trycloudflare.com`，审计来源 IP 真实化。

## 11. nmap（真实安全探测）

- 扫描 `-sS -Pn --open --top-ports N [-sV]`；主机发现 `-sn -n`（LAN ARP）。
- **参数构建抽成纯函数** `_build_nmap_cmd`（曾把 `-sS` 拼成 `-ssS` 导致 usage 退出，纯函数 + 单测固化）。
- 子进程边界：`_run_nmap` 无 shell、超时限制（--host-timeout）、XML 解析 `_parse_nmap_xml`。
- 后台任务独立 session + 任务引用表；IPv6 加 `-6`。

## 12. DeepSeek / Ollama（AI 网关，`services/ai_gateway.py`）

- `AIGateway.chat(context, query, model_pref, timeout) → (content, provider)`：
  - 优先级：`model_pref` 指定 → DeepSeek（配 Key 时）→ Ollama → fallback。
  - **永不抛错（NFR-004）**：任何通道失败都被捕获，降级到下一通道，最终兜底文案。
  - `httpx.AsyncClient` 非阻塞调用 OpenAI 兼容 `/chat/completions`。
- 上下文：`_build_messages` 拼装历史（role 白名单过滤）+ `trim_history` 截断 10 轮。
- 超时分层：问答 30s / 课程 90s（`chat(timeout=)` 透传）。
- 课程生成：`build_course_query` 提示词工程（严格 JSON 指令）+ `extract_json`（括号平衡抗截断）+ `validate_course`（白名单硬校验）。

## 13. ECharts（工作台可视化）

- 角色工作台/训练统计/审计图表用 ECharts：能力雷达图、30 天学习曲线、告警趋势、角色分布饼图等——数据来自角色聚合接口。

---

# 第三部分 · 横切设计速查

| 横切项 | 设计 |
|---|---|
| 统一响应 | `{code, message, data}`；成功 code=0；业务码表 40001/40100/40301/40302/40400/40900/42900/50000 |
| 错误处理 | `AppError` → HTTP 200 + 业务码；IntegrityError 兜底 409；未知路由 40400 |
| 审计 | `record()` 全操作落 operation_logs（RULE 防篡改），detail JSONB |
| 日志 | `app/core/logging.py` 统一 JSON 单行（ts/level/logger/msg），HTTP 访问日志中间件，≥500 记 ERROR+exc |
| 数据范围 | `apply_data_scope` / `apply_device_data_scope`，列表+详情双端应用 |
| 分页 | size `Query(ge=1, le=100)` 统一治理 |
| 空值 | Pydantic EmailStr/Optional 对 `""` 校验失败，前端空字段转 null |
| 部署 | Compose + seed 幂等 + healthcheck + security_check 5 项自检 + 定时备份 |

---

> 配套文档：[AI_PROJECT_REPORT.md](AI_PROJECT_REPORT.md)（报告总览）· [INTERVIEW_NOTES.md](INTERVIEW_NOTES.md)（面试备考）

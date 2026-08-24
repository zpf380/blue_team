# 蓝队业务管理系统 · 面试备考笔记

> 面向 **AI 应用开发 / 全栈 / 后端 / 安全方向** 面试官。所有内容基于项目真实代码与生产实测，可经得起追问。
> 配合 [AI_PROJECT_REPORT.md](AI_PROJECT_REPORT.md) 使用。

---

## 一、开场介绍脚本（背熟）

### 30 秒版
> "我独立开发了一个网络安全公司蓝队（防御方）的**业务管理系统**，把沟通协同、员工培养、资产管控、人员治理四大块做成一个全栈产品。它的特色是**深度整合了 AI**：用 DeepSeek 做了 AI 助手和多轮对话、能根据主题自动生成网络安全实训课程、训练沙箱有任务判分引擎，同时接入了真实的 nmap 做漏洞扫描和资产发现。前端 Vue3、后端 FastAPI + PostgreSQL，Docker 单机部署，后端 195 个测试全绿，生产环境实机跑过完整流程。"

### 2 分钟版（面试官让展开时）
> 技术栈：Vue3 + Element Plus + Pinia（前端），Python FastAPI + SQLAlchemy 异步（后端），PostgreSQL/Redis/MinIO（存储），DeepSeek + Ollama（AI 双通道），nginx 反代 + Docker Compose 部署。
> 四大业务域：① 沟通——聊天 IM（频道/私聊/@提及）+ WebSocket 心跳广播 + AI 助手；② 培养——训练闯关 + 模拟沙箱 + **AI 自动生成课程**并实时推送；③ 资产——设备/IPAM/网络发现/真实漏洞扫描 + 告警去重 + 外部通知；④ 治理——RBAC 五角色 + 数据范围隔离 + 休假审批自动化 + 审计合规报告。
> 我的角色：从需求、数据库建模、后端 API、前端页面、安全加固到 Docker 生产部署、测试与冒烟，**全链路独立完成**，一共 195 个后端测试、生产实机验证。

### 5 分钟版 = 2 分钟版 + 挑 2 个难点讲（见第五节）

---

## 二、为什么这是一个"AI 相关项目"（面试官第一个问题）

| AI 能力 | 背后技术 | 面试可展开点 |
|---|---|---|
| AI 助手问答 | DeepSeek API + 会话上下文 | 上下文如何裁剪、降级、超时 |
| AI 课程自动生成 | 提示词工程 + JSON 抗幻觉解析 | 幻觉治理、硬校验、人工审改闭环 |
| 训练沙箱 | 虚拟文件系统 + 任务判定规则 | 不用容器的零成本设计 |
| 漏洞智能研判 | nmap + 三层规则引擎 | 为什么用规则而非 LLM 猜 CVE |
| 告警分发 | 多通道 webhook + SMTP | 失败静默、回写状态 |

---

## 三、高频面试题 · 分类深度解析

### A. AI 应用类

**Q1 为什么选 DeepSeek，不选 GPT？**
- 核心是**成本 + 国内可访问**：DeepSeek API 极便宜，适合做"每问一次都有成本"的助手；Ollama 本地模型做兜底，断网/限流也不影响主流程。
- 生产实测：`deepseek-chat` 路由到 `deepseek-v4-flash`，正常问答 ~几十秒内返回；生成长课程 42.9s 返回。
- **工程点**：不锁定单一厂商——网关层抽象 `chat()`，换模型只改配置。

**Q2 多通道降级怎么设计的？永不抛错怎么实现？**
- `AIGateway.chat(context, query, model_pref, timeout)` 返回 `(content, provider)`：
  - `model_pref` 优先，没配 Key → 尝试 Ollama；DeepSeek 超时/异常 → 捕获 `AIUnavailableError` → 尝试 Ollama；Ollama 也失败 → 返回兜底文案 `"（AI 服务暂不可用…）"`。
  - 因此**任何 AI 故障都不抛 HTTP 500**，前端气泡显示 provider 徽章（deepseek/ollama/fallback），用户无感降级。
- 面试补充：这是 **NFR（非功能需求）-004"永不抛错"** 的落地——对聊天产品，AI 挂了聊天本身不能挂。

**Q3 AI 上下文（记忆）怎么管理？**
- 会话持久化到 `ai_conversations` 表，`context_messages` 存最近 **10 轮**（`trim_history` 截断，`context[-rounds*2:]`）。
- 前端每次提问传 `conversation_id`，后端加载历史拼进 messages，**切页面回来自动续接**。
- 追问点：为什么 10 轮？→ token 成本 + 响应延迟的平衡，模型上下文窗口有限，过长会稀释早期指令。
- 追问点：如何防注入越权？→ 续接他人会话 40400（不泄露存在性）+ 40301。

**Q4 提示词工程具体做了什么？**
- 课程生成：生成指令**全部放 user 消息**（system 复用全局蓝队 prompt），要求严格输出 JSON（场景/任务/命令/判分规则）。
- 关键防呆：`_brace_balanced_extract` 做括号平衡解析，**处理 LLM 输出截断、把 JSON 包进 ```markdown 代码块**等常见坏输出。

**Q5 LLM 幻觉怎么治理？**（高频！）
- **不信任 LLM 输出**：`validate_course()` 硬校验——命令必须在 `ALLOWED_COMMANDS` 白名单、任务 id 必须唯一、结构必须完整，任何一条不过就整体拒绝。
- **AI 生成 ≠ 直接上线**：生成的是草稿，必须经人工编辑器审改后才能发布（发布态守卫 draft→published）。
- 面试升华：生产级 AI 应用的底线是"**LLM 只负责生成，规则负责把关**"。

**Q6 超时怎么处理？（DeepSeek 生成长课程很慢）**
- 普通问答 `AI_TIMEOUT_SECONDS=30s`；课程生成单独 `AI_COURSE_TIMEOUT_SECONDS=90s`，`chat(timeout=)` 透传。
- **生产真实坑**：nginx `proxy_read_timeout 60s` 会掐断长请求——后端其实已完成并落库，但响应被 nginx 掐断 → 前端收到 504。修复：`location = /api/v1/training/manage/generate` 精确匹配单独放宽到 180s。

**Q7 为什么漏洞 CVE 研判用规则，不用 LLM？**
- CVE 是**确定性事实**，规则引擎给确定答案；LLM 可能"一本正经胡说"给出不存在的 CVE 编号——**误导比缺失更糟**。
- 规则设计：端口规则 → 服务名规则（40+ 服务）→ product 子串 → info 兜底，每端口至多一条，CVE"宁缺毋滥"。

### B. 后端架构类

**Q8 为什么 FastAPI + SQLAlchemy 异步？**
- FastAPI：类型标注即文档（OpenAPI 自动生成）、Pydantic v2 校验、原生 async。
- 异步全链路：DB 用 `AsyncSession`、扫描/nmap 用 `asyncio.create_task` 后台跑、AI 调用用 httpx.AsyncClient，**不阻塞事件循环**。

**Q9 WebSocket 怎么设计的？**（高频）
- 两块：`/ws/chat/{channel_id}` 频道聊天（心跳 30s + 广播）、`/ws/notifications` 全局通知。
- 全局连接表 `_globals`（逐连接容错），发布课程后 `send_global` 推给所有在线学员。
- **生产真实坑**：uvicorn `--workers 2` 时 WS 连接与 publish HTTP 请求可能落到**不同 worker 进程**，各自内存 ConnectionManager 不共享 → 事件发到空表**丢失**。修复：`--workers 1`（单机内存直推必须单进程）。
- 追问：横向扩容怎么办？→ 需要 Redis Pub/Sub 共享事件（README/代码注释已留扩展点）。

**Q10 认证体系（能聊很久）**
- JWT 轮换：access 2h + refresh 7d，HttpOnly Cookie 存令牌（JS 不可读，防 XSS 窃取）。
- **CSRF 双校验**：写请求前端带 `X-Requested-With: XMLHttpRequest`，后端 refresh/logout 强制校验该头。
- 图形验证码：Redis 存码（TTL 300s），失败 `CAPTCHA_THRESHOLD` 次后要求验证码；连续 5 次失败锁定 15min + `auth:lock` 审计。
- MFA：admin 强制 TOTP（`MFA_FORCE_ROLES=["admin"]`），扫码绑定后登录需动态码。
- **前端 401 自动刷新**：统一 axios 拦截器，捕获业务码 `40100` 后自动调 refresh 重试一次（并发 401 用共享 Promise 防重复刷新）。

**Q11 权限与数据隔离**
- RBAC：角色权限点白名单（`require_permission("monitor:device:manage")`）+ 按钮级 `v-permission`。
- **数据范围**（比纯 RBAC 更进一步）：all / dept / self 三级；analyst 只能看**本部门**的设备/告警/扫描报告；`apply_data_scope` / `apply_device_data_scope` 在列表与详情端点统一应用（曾漏在 `get_device` 导致越权，已补）。
- 安全细节：越权读他部门设备 = 40301（有权限但超范围）；无权限操作 = 40302。

**Q12 删除保护怎么做的？（典型的工程健壮性）**
- 删除前做**引用计数检查**：子部门/用户/设备/子网/分配等，任一非零 → 40900 + `data=refs` 明细（"子网下仍有 1 条地址分配"），绝不裸 500。
- 先查引用再删，并给 `exceptions.py` 注册 `IntegrityError` 兜底（防遗漏的 FK 冲突仍裸 500）。
- 软删 vs 物理删：子网/用户用软删（`is_active=False` / archived）保留历史与 FK 完整性。

### C. 安全类

**Q13 怎么防 SQL 注入 / 命令注入？**
- SQL：全参数化（SQLAlchemy 绑定参数），无一处字符串拼 SQL。
- 命令注入：nmap 调用 `subprocess` **不带 shell**（列表参数，天然防拼接）、扫描目标限制为已登记网段（防 SSRF）。

**Q14 生产 Web 加固做了哪些？**（背表）
- nginx 限流：登录/验证码 `1r/s burst=10`、其余 API `15r/s burst=40`，429 统一 JSON；**限流 key 用 XFF 第一个 IP**（真实公网 IP 每 IP 独立桶，Docker 网关下 `remote_addr` 恒为 172.19.0.1 会全站共享一个桶误伤）。
- `server_tokens off` 隐藏版本、安全响应头全套（CSP/HSTS/nosniff/X-Frame-Options/Referrer-Policy/Permissions-Policy）、超时/缓冲上限防慢速攻击。
- **真实坑**：nginx `add_header` **继承陷阱**——`location = /index.html` 自定义了 Cache-Control 导致 server 级安全头被整体遮蔽，需在带自定义 add_header 的 location 内重新 `include security-headers.conf`。

**Q15 越权与数据泄露怎么防的？**
- 所有详情端点走数据范围过滤（get_device/get_scan_report/get_discovery 均对齐列表）。
- 未知路由返回 40400 而非 50000；他人会话/私聊返回 40400 不泄露存在性。

### D. 工程与数据库类

**Q16 测试策略？（200 题量级怎么维护）**
- pytest + httpx ASGITransport **异步集成测试**（真实连 PostgreSQL），覆盖：权限矩阵（五角色 × 端点）、数据范围、状态机、删除保护、分页边界、外键校验、导入损坏兜底。
- 共享库测试隔离：conftest `purge` fixture 清理测试残留（数据范围测试、`title LIKE '扫描发现高风险：%'`、10.0.99.% 设备）。
- 每个功能批次 = 后端测试 + 前端 build + 生产冒烟**三层验证**才能算完成。

**Q17 数据模型设计亮点**
- 操作日志**只追加**：PostgreSQL RULE `prevent_delete_oplog / prevent_update_oplog`（DO INSTEAD NOTHING），审计链不可篡改。
- 状态机：考勤（pending→approved→in_progress→completed / rejected / cancelled）由后台定时任务到点自动切换（不覆盖 disabled/archived）。
- 软删 + 历史追溯：IP 分配租约历史查操作日志 detail。

**Q18 部署与运维**
- Docker Compose 单机生产栈（postgres/redis/minio/backend/frontend-nginx），seed 幂等，`deploy.sh up` 一键重建。
- Cloudflare Tunnel 免费公网：容器出站建隧道，**审计来源 IP 从 Docker 网关变成真实公网 IP**。
- 健康检查用 Python urllib（镜像不带 curl），`security_check.sh` 5 项自检。

---

## 四、最有区分度的难点与踩坑（讲 2 个就够）

### 难点 1：nginx 下 DELETE+body 解析失败 → 500
- **现象**：`DELETE /monitor/devices/{id}` 带 `{"reason":"..."}` body，**测试全绿**，生产经 nginx+uvicorn 却报 `{"code":50000,"message":"There was an error parsing the body"}`。
- **根因**：DELETE 携带 body 在 nginx/uvicorn 组合下解析不可靠（ASGI 直连测试不暴露）。
- **解决**：reason 改 **query param**（`reason: str | None = Query(None, max_length=200)`），前端 `{ params: { reason } }`，同步 8 处测试。
- **升华**：*测试环境与生产链路（网关/代理）行为不同，跨层问题必须生产实测才能暴露；写 API 时 DELETE 尽量不依赖 body。*

### 难点 2：uvicorn --workers 2 → WebSocket 事件丢失
- **现象**：AI 课程发布 → 在线学员 WS 收不到推送，偶发。
- **根因**：WS 连接和 publish HTTP 请求落在不同 worker 进程，各自内存 ConnectionManager，事件发到空表丢失。
- **解决**：`--workers 1`（单机内存直推必须单进程）。
- **升华**：*有状态进程内状态（WS 连接表/内存队列）在多 worker 下天然不共享，选型时就要考虑，或引入 Redis Pub/Sub。*

### 备选难点
- **401 刷新死链**：后端 `AppError` 统一返回 HTTP 200 + `code:40100`，前端原只处理 HTTP 401 → 永不触发刷新、死循环弹错。修：成功拦截器也看业务码 40100 走 refresh 重试。
- **DeepSeek 长请求 504**：nginx `proxy_read_timeout` 掐断，需精确匹配 location 单独放宽。
- **token 存 localStorage 多标签串号**：改 `sessionStorage` 按标签页隔离。
- **nmap 参数拼接坑**：`-sS` 配置拼接出 `-ssS` → 需 `_build_nmap_cmd` 纯函数 + 回归测试。
- **compose 只 recreate backend 后 nginx 502**：upstream 缓存旧容器 IP，需一并 recreate frontend。
- **课程 JSON 幻觉**：括号平衡兜底解析 + 命令白名单硬校验。

---

## 五、可能被追问的细节（备查）

| 可能被追问 | 回答要点 |
|---|---|
| access 2h refresh 7d 怎么轮换的 | 刷新后签发新 access；改密/登出吊销 refresh 令牌 |
| 数据范围 sub_dept 呢 | 预留未启用，命中时友好 40001"预留功能请联系管理员配置" |
| 告警去重窗口 | 24h，同 IP+type 且 open/acknowledged 去重 |
| 巡检频率 | 每 15min 全子网刷新设备状态，离线判定 `offline_since` |
| 文件上传安全 | 扩展名白名单 + MIME 软校验 + 大小配置 + 存 MinIO 签名 URL |
| 图形验证码 | 存 Redis（TTL 300s），达阈值才要求，防枚举/撞库 |
| AI 成本控制 | 上下文裁剪到 10 轮、超时分层、双通道降级不烧钱 |
| 为什么单机 | 实践项目，4C8G 单机跑通；WS 单 worker 是当前上限 |

---

## 六、演示路径（面试官想看产品时）

1. `https://localhost` 登录（manager01）
2. **工作台** → 各角色聚合真实数据（待审报告/告警/训练排行）
3. **AI 助手** → 提问 → 看 provider 徽章 + 会话列表续接
4. **课程管理** → 主题 → AI 生成课程 → 审改 → 发布 → 学员端 WS 实时收到
5. **监控** → 建子网/设备 → 扫描 → 报告 → 告警 → 飞书推送
6. **IPAM** → 子网/分配/租约回收 → 删除被引用子网看 40900

> 生产账号口令见本地 `deploy/.env.prod` 与部署记录，**不入 git**。

---

## 七、一句话总结（留作记忆锚点）

> "一个把 **LLM（DeepSeek 多通道降级 + AI 生成课程）**、**真实安全工具（nmap 扫描/发现）**、**规则引擎（CVE 研判/沙箱判分/权限隔离）** 揉进一套可生产部署的蓝队业务系统，前后端全栈 + Docker 部署 + 195 测试 + 生产实机验证的完整闭环。"

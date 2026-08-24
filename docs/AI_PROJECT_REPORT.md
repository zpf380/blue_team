# 蓝队业务管理系统 · 最完整项目报告

> **AI 相关开发项目视角** | 2026-08-19 版本 | 单机生产部署已实机验证

---

## 一、项目概览

**蓝队业务管理系统**是面向网络安全公司蓝队（防御方）的一站式运营平台，覆盖**沟通协同、能力培养、资产管控、人员治理**四大业务域，并深度融合 **LLM（DeepSeek）+ 规则引擎 + 真实安全工具（nmap）** 构建"**AI 驱动 + 安全自动化**"的完整系统。

- **零软件授权成本**：全开源技术栈 + DeepSeek 低单价 API + Cloudflare 免费隧道
- **AI 的定位**：不是演示玩具，而是**生产链路**——AI 问答、AI 自动生成课程、AI 降级容错、安全扫描规则智能研判
- **验证程度**：后端 **195 项测试全绿**、前端构建通过、生产 HTTPS 冒烟 24/24、安全自检 5/5

### 技术栈总览

| 层 | 技术 | 说明 |
|---|---|---|
| 前端 | Vue3 + Vite + Element Plus + Pinia + ECharts | `<script setup>`、动态菜单、v-permission |
| 后端 | Python 3.13 / FastAPI / SQLAlchemy 2.0 (async) / Pydantic v2 | 异步全链路 |
| 数据 | PostgreSQL 16 / Redis 7 / MinIO | 关系库 / 缓存+验证码 / 文件存储 |
| AI | DeepSeek API（主）→ Ollama（本地降级） | 永不抛错 |
| 安全工具 | nmap（真实扫描/主机发现） | 后台异步任务 |
| 部署 | Docker Compose + Nginx 反代（限流/安全头） | 单机 4C8G |

---

## 二、AI 能力全景（核心）

### 2.1 AI 网关架构 —— `backend/app/services/ai_gateway.py`

统一的多通道 LLM 调用层，是全部 AI 功能的底座。

```
AI 调用 → 优先级判定（model_pref）→ 通道① DeepSeek
        → 通道① 失败/超时 → 通道② Ollama（本地降级）
        → 通道② 失败 → 兜底文案（永不抛错）
```

| 特性 | 实现 |
|---|---|
| 通道降级 | `chat()` 返回 `(content, provider)`，provider ∈ `{deepseek, ollama, fallback}`；前端气泡展示 provider 徽章 |
| **永不抛错**（NFR-004） | `AIUnavailableError` + fallback 文案"（AI 服务暂不可用，请稍后再试。聊天功能不受影响。）" |
| 会话上下文 | `_build_messages()` 拼装最近 N 轮 `context_messages`（role 白名单过滤） |
| 超时分层 | 普通问答 `AI_TIMEOUT_SECONDS=30`；AI 生成长课程单独 `AI_COURSE_TIMEOUT_SECONDS=90` |
| 多租户配置 | DeepSeek Key 生产注入，留空自动走 Ollama |

### 2.2 AI 助手（智能问答 + 会话持久化）—— `backend/app/api/v1/ai.py`

- `POST /ai/invoke`：支持会话续接（传 `conversation_id` 加载最近 10 轮上下文），频道内 AI 回复与独立助手会话隔离
- **会话持久化**：`ai_conversations` 表，标题 = 首条提问预览；前端左右两栏会话列表（新建/切换/删除），**切回页面自动续接上次对话**
- 权限：`chat:ai`（admin/manager/analyst），trainee/auditor 无；他人/频道内会话一律 **40400 不泄露存在性**
- `regenerate` 复用会话续接，语义为"追加一轮新回复"（完整记录每轮提问）

### 2.3 AI 课程自动生成 —— `backend/app/services/training_generator.py`

**主题 → 完整实训课程**的全自动流水线，含强校验防 LLM 幻觉：

```
主题输入 → build_course_query（系统 prompt + 严格 JSON 指令）→ DeepSeek
→ extract_json（括号平衡兜底解析）→ validate_course（硬校验）
→ 课程编辑器审改 → 发布 → WebSocket 实时推送在线学员（NEW 徽标）
```

| 环节 | 设计要点 |
|---|---|
| 提示词工程 | 生成指令全部放 user 消息，JSON 格式严格约束 |
| **JSON 抗幻觉** | `_brace_balanced_extract` 括号平衡兜底，防 LLM 输出截断/包裹 markdown |
| 硬校验 `validate_course` | 场景/任务/命令白名单 `ALLOWED_COMMANDS`、任务 id 唯一性、非法命令拒绝 |
| 人工审改环节 | 完整编辑器审改后才可发布，**AI 生成不等于直接上线** |
| 实时分发 | 发布后 `push_course_published` 经 WS 推送到线学员，前端 ElNotification + 即时刷新 |

### 2.4 训练沙箱智能体 —— `backend/app/services/sandbox_service.py`

**零成本的模拟攻防环境**（不做真实容器）：基于场景预置的虚拟文件系统 + 任务规则引擎。

- 虚拟终端：`ls/cat/grep/head/tail` 等命令在虚拟 FS 上执行（`build_virtual_fs` + `_dispatch`）
- **任务判定引擎**：`check.cmd` 匹配命令、`pattern/args` 匹配参数、`output_contains` 匹配命令输出 —— 三类规则组合判分
- 判分/扣分 + 提交结算 `calc_final_score`（全任务完成且无扣分 = completed）
- 配套：3 智能体 + 5 场景 + 7 徽章 + 排行榜 + 积分体系

### 2.5 安全智能分析（真实 nmap + 规则研判）—— `backend/app/services/scanner.py`

虽是规则引擎而非 LLM，但体现"AI 化安全分析"的工程范式：

- **真实 nmap**：`-sS -Pn --open --top-ports N [-sV]` 后台异步扫描，进程内任务引用防 GC
- **三层漏洞研判**（`_derive_vulnerabilities`）：
  1. 端口规则 `PORT_VULN_MAP`（445→CVE-2020-0796 等）
  2. 服务名规则 `SERVICE_VULN_MAP`（40+ 服务，mongod/memcached/couchdb/grafana/kibana/smb 挂有把握的 CVE，**宁缺毋滥**）
  3. product 子串规则 `PRODUCT_RULES`（长串在前）
  4. 每端口至多一条，余下 info 兜底
- 风险分 `_compute_risk_score` → risk≥70 自动建告警 → 告警去重窗口 24h

### 2.6 告警智能分发 —— `backend/app/services/notify.py`

扫描告警自动推送外部渠道：**飞书（生产已启用）/ 企业微信 / 钉钉 / SMTP**。任一渠道失败**静默不影响主流程**，发送成功回写 `alerts.notified_at`。

---

## 三、四大业务能力矩阵

| 域 | 能力 | 关键点 |
|---|---|---|
| **沟通协同** | 聊天 IM（频道/私聊/@提及）、WebSocket 心跳广播、消息已读/撤回/全文检索 | 学员仅可与其他学员私聊（单向限制）、管理员全量监控、AI 助手 |
| **能力培养** | 训练中心（智能体/场景闯关）、模拟沙箱、AI 课程生成+发布+WS 推送、徽章/排行 | 课程发布态守卫、场景审核 |
| **资产管控** | 设备（数据范围 CRUD/探测）、IPAM（子网/分配/租约回收/历史追溯）、网络发现（nmap 主机发现→登记）、真实漏洞扫描 + 报告审核闭环 | 子网重叠检测、保留段、VLSM 拆分、24h 告警去重 |
| **人员治理** | RBAC 五角色 + 部门树、休假/外勤审批→到点自动切换、操作日志只追加 + 合规报告 | 最后管理员保护、自我保护 |

---

## 四、技术架构与数据模型

```
前端 Vue3 + Element Plus + Pinia + ECharts + axios (HttpOnly Cookie)
   │  /api（反代+限流）  /ws（WebSocket 代理）
nginx（生产网关：HTTPS/限流/安全头/SPA）
   ├─ FastAPI（Python 3.13 / SQLAlchemy 2.0 async / Pydantic v2）
   │    ├─ services: ai_gateway / scanner / patrol / notify / sandbox / audit / training_generator
   │    ├─ ws: 频道聊天 + 全局通知（心跳 30s + 广播）
   │    └─ DB: PostgreSQL 16 / Redis 7 / MinIO（文件）
   ├─ DeepSeek API（主通道）→ Ollama（降级）
   └─ nmap（真实扫描）
```

**关键设计**：
- 统一响应封装 `{code, message, data}`；错误码体系（40100 认证失效 / 40302 越权 / 40900 冲突 / 40400 不存在等）
- **数据范围过滤**：all / dept / self 三级（sub_dept 预留），analyst 仅本部门设备/告警/报告
- 认证：JWT 2h+7d 轮换、HttpOnly Cookie + `X-Requested-With` CSRF 双校验、图形验证码 + 连续 5 次失败锁定 15min、admin 强制 MFA（TOTP）、前端 401 自动刷新重试
- 审计：操作日志只追加（PostgreSQL RULE 防删改）、全部关键操作 `record()` 落库

---

## 五、工程化与质量保障

- **后端测试**：**195 项**全绿（单元 + 异步集成，httpx ASGITransport），覆盖权限矩阵/数据范围/状态机/删除保护/边界校验
- **前端**：`npm run build` 通过，动态菜单 + 路由守卫 + 按钮级 `v-permission`
- **生产冒烟**：`smoke.sh` 24/24 + 各专项（课程 WS 21/21、考勤 14/14、巡检 22/22、AI 会话 10/10）
- **安全自检**：`security_check.sh` 5 项全绿（弱口令/密钥/头/限流），退出码 0
- **回归纪律**：每个功能批次 = 后端测试全绿 + 前端构建 + 生产冒烟三层验证

---

## 六、安全加固体系

| 层 | 措施 |
|---|---|
| 应用 | SQL 注入（全参数化）、命令注入（无 shell 拼接）、XSS（DOMPurify + CSP）、文件上传白名单、SSRF（扫描目标限已登记网段）、CORS 白名单 |
| 认证 | JWT 轮换 + MFA、图形验证码 + 锁定、登录审计 `auth:lock` |
| 基础设施 | nginx 限流（登录 1r/s、API 15r/s，key=XFF 真实 IP）、`server_tokens off`、超时/缓冲上限 |
| 响应头 | CSP + HSTS + nosniff + X-Frame-Options + Referrer-Policy + Permissions-Policy（禁摄像头/麦克风/定位） |
| 口令 | 生产 6 账号随机强口令、PostgreSQL/MinIO 已加固为随机强口令（2026-08-19，security_check 清零） |

---

## 七、生产部署与运维

- **单机 4C8G Docker Compose**：postgres/redis/minio/backend/frontend(nginx:443)
- **公网访问**：Cloudflare Tunnel（`deploy/tunnel.sh`），审计来源 IP 真实化
- 一键启动 `start.sh`、安全自检 `security_check.sh`、seed 幂等
- 访问入口：`https://localhost`（自签证书）；公网 `https://<random>.trycloudflare.com`（隧道重启后变化）

---

## 八、AI 相关经验沉淀

1. **多通道降级是 LLM 应用的底线**：DeepSeek → Ollama → 兜底，任何 AI 故障都不影响聊天主流程（NFR-004）
2. **LLM 输出必须过硬校验**：课程 JSON 的括号平衡解析 + 命令白名单 + 结构校验，防幻觉直接入库
3. **AI 生成 + 人工审改闭环**：AI 负责草稿，人负责上线（课程发布态守卫）
4. **超时分层治理**：普通问答 30s、生成长课程 90s，nginx 为长请求单独放宽 `proxy_read_timeout`
5. **规则引擎补位 LLM**：CVE 研判用确定性规则（宁缺毋滥），比让 LLM 猜 CVE 更可信

---

## 九、局限与扩展方向

| 方向 | 现状 | 可扩展 |
|---|---|---|
| 会话记忆 | 最近 10 轮上下文 | 向量检索 + RAG（接入知识库） |
| 扫描研判 | 静态规则三层 | 接入 LLM 结合漏洞库做推理研判 |
| AI 课程 | 单轮生成 + 人工审改 | 多轮精修（生成→审查反馈→迭代） |
| WS 推送 | 单 worker 内存直推 | 横向扩容需 Redis Pub/Sub |

---

## 十、验证结果速查

| 验证项 | 结果 |
|---|---|
| 后端 pytest | **195 passed** |
| 前端构建 | `✓ built` 通过 |
| 生产冒烟 | 24/24 + 各专项全绿 |
| 安全自检 | 5/5 全绿（退出码 0） |
| 生产实测 | 登录/越权/删除保护 409/工作台真实数据/AI 会话/MinIO 读写 |

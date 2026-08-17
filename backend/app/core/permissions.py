"""权限点常量定义（前端路由 meta.permission 与此一一对应）。

命名约定：模块:动作，支持 "*" 通配（`chat:*` 表示 chat 下全部）。
"""

# 仪表盘
DASHBOARD_ADMIN = "dashboard:admin"
DASHBOARD_SECURITY = "dashboard:security"
DASHBOARD_CHAT = "dashboard:chat"
DASHBOARD_TRAINING = "dashboard:training"
DASHBOARD_AUDIT = "dashboard:audit"

# 聊天
CHAT_VIEW = "chat:view"
CHAT_CHANNEL = "chat:channel"
CHAT_DM = "chat:dm"
CHAT_AI = "chat:ai"

# 训练
TRAINING_VIEW = "training:view"
TRAINING_AGENT_VIEW = "training:agent:view"
TRAINING_SANDBOX = "training:sandbox"
TRAINING_RANKING = "training:ranking"
TRAINING_STATS = "training:stats"
TRAINING_COURSE_MANAGE = "training:course:manage"

# 监控
MONITOR_VIEW = "monitor:view"
MONITOR_DEVICE_VIEW = "monitor:device:view"
MONITOR_DEVICE_MANAGE = "monitor:device:manage"
IPAM_MANAGE = "ipam:manage"
MONITOR_ALERT_VIEW = "monitor:alert:view"
MONITOR_ALERT_MANAGE = "monitor:alert:manage"
MONITOR_SCAN = "monitor:scan"

# 用户 / 部门 / 审计
USER_MANAGE = "user:manage"
DEPARTMENT_MANAGE = "department:manage"
AUDIT_LOG = "audit:log"
AUDIT_REPORT = "audit:report"

# 考勤（休假/外勤申请）
LEAVE_APPLY = "leave:apply"
LEAVE_APPROVE = "leave:approve"

# 通配
ALL = "*"

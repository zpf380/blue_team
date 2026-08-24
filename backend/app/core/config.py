"""应用配置：全部通过环境变量 / .env 注入。"""
from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    PROJECT_NAME: str = "蓝队业务管理系统"
    API_V1_PREFIX: str = "/api/v1"
    DEBUG: bool = False

    # 数据库 / 缓存
    DATABASE_URL: str = "postgresql+asyncpg://blueteam:blueteam_pass@localhost:5432/blueteam"
    REDIS_URL: str = "redis://localhost:6379/0"

    # JWT
    JWT_SECRET_KEY: str = "dev-secret-key-change-in-production"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 120
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    @model_validator(mode="after")
    def _reject_default_jwt_secret(self) -> "Settings":
        # 生产 .env.prod 若仍为 deploy/.env.prod.example 的占位符 → 拒绝启动，
        # 避免用已知 JWT 密钥运行（可被离线伪造任意用户 token）。
        # 开发/测试未显式设置时用代码内默认值（dev-secret-*），不受影响。
        if self.JWT_SECRET_KEY == "please-change-me-to-a-long-random-secret":
            raise ValueError(
                "JWT_SECRET_KEY 仍为默认占位符，拒绝启动。"
                "请运行 deploy/deploy.sh 自动生成随机密钥，或手动设置强随机串。"
            )
        return self

    # 登录锁定
    LOGIN_MAX_FAILURES: int = 5
    LOGIN_LOCK_MINUTES: int = 15

    # 登录图形验证码（自适应：用户名/IP 失败达到阈值后必须通过验证码）
    CAPTCHA_THRESHOLD: int = 2
    CAPTCHA_TTL_SECONDS: int = 300

    # MFA（TOTP）：管理员强制启用；其余角色可选
    MFA_ISSUER: str = "蓝队业务管理系统"
    MFA_FORCE_ROLES: list[str] = ["admin"]
    MFA_PENDING_MINUTES: int = 5

    # AI 网关（DeepSeek 主 / Ollama 降级，NFR-004）
    DEEPSEEK_API_KEY: str = ""  # 留空则直接走 Ollama
    DEEPSEEK_BASE_URL: str = "https://api.deepseek.com/v1"
    DEEPSEEK_MODEL: str = "deepseek-chat"
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "llama3"
    AI_TIMEOUT_SECONDS: float = 30.0
    AI_COURSE_TIMEOUT_SECONDS: float = 90.0  # AI 生成训练课程（长任务）单独超时
    AI_MAX_HISTORY_ROUNDS: int = 10  # 同一会话保留最近 N 轮

    # 漏洞扫描（nmap）
    NMAP_TOP_PORTS: int = 1000            # --top-ports N（未指定端口时的默认扫描范围；1000 与常见 nmapGUI top-1000 覆盖一致）
    NMAP_TIMEOUT_SECONDS: int = 90        # --host-timeout + Python 侧硬超时
    NMAP_VERSION_DETECT: bool = True      # -sV 版本探测开关（可给 open_ports 补 service/product/version）
    NMAP_SCAN_TYPE: str = "sS"            # sS（SYN，需 CAP_NET_RAW）/ sT（connect，非 root 场景备选）
    NMAP_HOST_TIMEOUT: int = 30           # 主机发现 --host-timeout（单主机探测超时，秒）
    SCAN_MAX_CONCURRENT: int = 3          # 同时在跑的 nmap 子进程上限（扫描 + 发现共享），防高并发拖垮服务器
    # NSE 漏洞脚本（真实 CVE 检测）：""=全局关闭；"vuln"=nmap 自带离线漏洞签名（默认，不依赖外网）；
    # "vulners"=联网查 CVE（需扫描机可访问 vulners.com）；也支持逗号分隔脚本名/类别
    NMAP_NSE_SCRIPTS: str = "vuln"
    NMAP_UDP_TOP_PORTS: int = 20          # UDP 扫描（sU）默认端口数（UDP 慢，取小值）
    NMAP_UDP_TIMEOUT_SECONDS: int = 300   # UDP 扫描专属 --host-timeout（更保守）
    NMAP_MAX_PORTS_IN_RANGE: int = 1024   # port_range 展开后端口数上限，防 "1-65535" 全端口 DoS

    # 告警外部通知（留空 = 关闭该渠道；配置在 deploy/.env.prod）
    ALERT_NOTIFY_WEBHOOK_URL: str = ""    # 企业微信/钉钉机器人 webhook，或通用回调 URL
    ALERT_NOTIFY_WEBHOOK_TYPE: str = "wecom"  # wecom（企业微信）/ dingtalk / feishu（飞书）/ generic（通用 JSON POST）
    ALERT_NOTIFY_EMAIL_TO: str = ""       # 逗号分隔收件人；为空则不发邮件
    SMTP_HOST: str = ""
    SMTP_PORT: int = 465
    SMTP_USERNAME: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = ""                   # 发件人显示地址，缺省用 SMTP_USERNAME
    # 扫描风险阈值（0-100）：达到即自动产生告警并触发外部通知
    ALERT_RISK_THRESHOLD: int = 70
    # 告警去重窗口（小时）：同 target_ip+alert_type 且状态未解决时，窗口内不重复告警，防扫描刷屏
    ALERT_DEDUP_HOURS: int = 24

    # 租约回收：定时任务间隔（分钟），配合查询时惰性回收
    LEASE_RECYCLE_INTERVAL_MINUTES: int = 60

    # 休假/外勤状态自动切换：轮询间隔（分钟）。租约回收 60 偏宽松，状态切换建议 5 更及时
    LEAVE_AUTO_SWITCH_INTERVAL_MINUTES: int = 5

    # 设备在线自动巡检：轮询间隔（分钟）。后台遍历 active 子网做主机发现刷新设备状态
    DEVICE_PATROL_INTERVAL_MINUTES: int = 15

    # 文件上传白名单（扩展名，逗号分隔；后端同时校验 MIME 与大小）
    UPLOAD_MAX_SIZE_MB: int = 100
    UPLOAD_ALLOWED_EXTENSIONS: str = (
        "png,jpg,jpeg,gif,webp,bmp,ico,"
        "pdf,doc,docx,xls,xlsx,ppt,pptx,"
        "csv,txt,md,log,"
        "zip,rar,7z,tar,gz"
    )

    # 文件存储（MinIO）
    MINIO_ENDPOINT: str = "localhost:9000"
    MINIO_ACCESS_KEY: str = "minioadmin"
    MINIO_SECRET_KEY: str = "minioadmin"
    MINIO_BUCKET: str = "blueteam-files"
    MINIO_SECURE: bool = False

    # CORS
    BACKEND_CORS_ORIGINS: list[str] = ["http://localhost:5173", "http://localhost"]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

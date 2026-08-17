# 公网访问 · Cloudflare Tunnel（免费）

> 配套脚本：`deploy/tunnel.sh`（`up` / `status` / `down`）
> 适用范围：本系统为**短期实践项目**，公网访问采用免费方案即可，无需投入服务器/域名成本。

## 一、解决什么问题

### 1. 让系统"无论什么网络都能访问"

局域网内可用 `https://localhost` 或 `http://192.168.1.105`；通过 Cloudflare Tunnel 后，外部任何网络都能通过一个公网 HTTPS 地址访问系统——**无需公网 IP、无需买服务器、无需路由器端口转发**。

### 2. 让登录审计的来源 IP 变真实

**问题**：直接访问时，审计表 `operation_logs.ip_address` 记录的来源 IP 全是 Docker 网关地址（实测为 `172.19.0.1`），无法区分访问者，来源 IP 失去审计意义。

**根因**：Docker Desktop on Windows 的端口转发（`com.docker.backend.exe`）是**用户态代理**，会把所有入站连接的源 IP 改写为 Docker 网络网关 IP。nginx 看到的 `$remote_addr` 恒为网关地址 → 后端记录的 IP 恒为网关地址。这是**架构级限制**，局域网内无法拿到真实客户端 IP（Docker Desktop 不支持 host 网络、浏览器不会自填 `X-Forwarded-For`）。

**注**：nginx → 后端这段链路本身是正常的——实测注入 `X-Forwarded-For: 8.8.8.8`，后端即记录 `8.8.8.8`。

**解法**：走 Cloudflare Tunnel。Cloudflare 边缘看到的是访问者的**真实公网出口 IP**，通过 `X-Forwarded-For` 传回源站，登录审计即记录真实公网 IP。

## 二、工作原理

```
访问者（任何网络）
   │  HTTPS
   ▼
Cloudflare 边缘节点（记录访问者真实公网 IP，覆盖 X-Forwarded-For）
   │  反向隧道（出站连接，无需开放入站端口）
   ▼
cloudflared 容器（bt-tunnel，挂在 blueteam_bt-net 网络）
   │  HTTPS → https://frontend（nginx，自签证书需 --no-tls-verify）
   ▼
nginx → FastAPI 后端 → PostgreSQL 审计表
```

- 隧道是**出站**连接，不依赖公网 IP、不开放端口，路由器零配置。
- Cloudflare 边缘会**覆盖** `X-Forwarded-For` 为真实客户端 IP，公网场景天然防止伪造来源 IP。

## 三、快速使用

```bash
# 启动隧道（不存在则自动创建），打印公网地址
bash deploy/tunnel.sh up

# 查看当前公网地址（隧道重启后地址会变，用它查最新）
bash deploy/tunnel.sh status

# 停止隧道（关闭公网入口）
bash deploy/tunnel.sh down
```

- 容器名 `bt-tunnel`，镜像 `cloudflare/cloudflared:latest`，已设 `restart unless-stopped`，Docker 重启后自动恢复。
- 公网地址形如 `https://xxxxxx.trycloudflare.com`，浏览器直接打开即可（首次可能需等 10~30s 生效）。
- 完整业务（登录 / API / WebSocket 实时推送）均走隧道可用。

## 四、验证结果（2026-08-17 实测）

| 检查项 | 结果 |
|---|---|
| 公网 `/health` | 200，`{"code":0,"message":"ok"}` |
| 公网 SPA 首页 | HTTP 200 |
| 公网完整登录（captcha → login） | `code:0` |
| 审计 `auth:login` 来源 IP | **真实公网 IP**（实测 `119.249.250.47`） |
| 对比：局域网直连来源 IP | `172.19.0.1`（Docker 网关，无意义） |
| 公网 WebSocket `/ws/notifications` | 101 升级成功 + 心跳 pong 正常（远程学员可实时收课程发布推送） |

## 五、局限性（诚实说明）

1. **地址不固定**：quick tunnel 免费特性，隧道每次重启地址都变。需要固定地址 → 购买域名（几元/年）托管到 Cloudflare，改用 named tunnel。
2. **国内访问不稳定**：到 Cloudflare 边缘的连接时好时坏，高峰时段可能慢/断（本机河北联通实测可通）。
3. **无访问控制层**：公网地址任何人可访问，依靠系统自身的登录 + 图形验证码 + MFA 保护。

## 六、安全建议（对外发布前）

- **修改默认账号密码**：`manager01 / Bt@123456`、`trainee01 / Bt@123456` 等默认口令必须改。
- 管理员 `admin / admin123` 务必改强密码。
- 短期实践结束可直接 `bash deploy/tunnel.sh down` 关闭公网入口。

## 七、故障排查

| 现象 | 排查 |
|---|---|
| `tunnel.sh up` 拿不到地址 | `docker logs bt-tunnel` 查看连接边缘是否失败；本机到 `region1.v2.argotunnel.com:443` TCP 必须可达 |
| 公网地址打不开 | 隧道刚建需等 10~30s；或地址已失效（隧道重启过），用 `tunnel.sh status` 查最新地址 |
| 来源 IP 仍是 172.19.0.1 | 确认访问是走公网地址而非局域网直连；局域网直连永远记录网关 IP（架构限制，见上文根因） |

## 八、实现备注（维护用）

- 创建命令（等价于 `tunnel.sh up`）：
  ```bash
  docker run -d --name bt-tunnel --restart unless-stopped --network blueteam_bt-net \
    cloudflare/cloudflared:latest tunnel --no-autoupdate --no-tls-verify --url https://frontend
  ```
- `--no-tls-verify` 必要：nginx 是自签证书，不关闭 TLS 校验隧道连不上源站。
- 公网地址从 `docker logs bt-tunnel` 中解析 `https://<random>.trycloudflare.com`。
- 安装经验：`winget install Cloudflare.cloudflared` 在国内走 GitHub 下载会被墙（`InternetOpenUrl failed 0x80072efd`），直接用 Docker 镜像最稳。
- 探测 CF 边缘连通性不能靠普通 curl（argotunnel 边缘 443 只接受 cloudflared 特殊握手，返回 000 不代表不通），需 TCP 实测或直接跑 cloudflared 验证。

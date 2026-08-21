# 🍋 Lemon Emby Manager & Telegram Bot (EP 魔改轻量版)

> **极轻量、高颜值、全自动的 Emby 用户管理与 Telegram 智能运营中控系统**  
> 专为低内存 VPS（甚至 512MB / 1GB / 2GB 小鸡）深度优化，异步高并发，支持卡密兑换、每日签到、到期自动封禁与多开播放实时风控。

---

## 🌟 核心特性

### 1. 🤖 高颜值 Telegram 原生交互
- **全 Inline Keyboard 点按式交互：** 个人中心、每日签到、节点线路、推荐客户端一键查询。
- **自助开通与重置密码：** 用户可通过 `/bind 账号 密码` 自助开号并绑定 TG ID，支持 `/resetpw` 自助改密。
- **签到与积分经济：** 支持每日签到领时长（如 +1 天）、攒积分，促进群聊活跃度。

### 2. 🛡️ 智能风控与多开拦截
- **并发设备数限制：** 实时监听 Emby `/Sessions`，当单个账号并发播放数超出设定的阈值（如默认 2 台）时，**自动阻断多余会话并向 TG 推送拦截警告**，彻底杜绝转借号与盗刷。
- **到期自动冻结：** 巡检后台周期扫描，账号到期瞬间在 Emby 停用（保留历史数据），并在 TG 推送续期提醒；用户使用卡密后即刻全自动解封。

### 3. 🎟️ 灵活卡密与时长体系
- **批量生成卡密：** 管理员可在 TG 输入 `/gen 30 10` 批量生成 10 张 30 天时长卡，或在 Web 后台一键生成。
- **一键兑换激活：** 用户输入 `/redeem LEMON-XXXX-XXXX` 即可秒级充值并延长到期时间。

### 4. 📊 独立 Web 管理控制台
- **单文件 Dark Mode 控制面板：** 实时监控 Emby 在线状态、当前活跃播放媒体、客户端型号、IP 来源。
- **在线会话一键强踢：** 在 Web 端即可一键中断违规播放会话。
- **全异步低内存占用：** 纯 Python 异步（FastAPI + aiosqlite + aiohttp），运行时内存仅 **~20MB**。

---

## 🚀 快速开始

### 方式一：Docker Compose（推荐）

1. **克隆项目并进入目录：**
   ```bash
   git clone https://github.com/nayeshiluo/lemon-emby-bot.git
   cd lemon-emby-bot
   ```

2. **配置参数：**
   ```bash
   cp config.example.yaml config.yaml
   vim config.yaml # 填入你的 Emby API Key、TG Bot Token 等
   ```

3. **一键启动：**
   ```bash
   docker compose up -d
   ```

---

### 方式二：Systemd / 本地运行

1. **安装依赖：**
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```

2. **配置与启动：**
   ```bash
   cp config.example.yaml config.yaml
   # 编辑 config.yaml 后运行
   python3 main.py
   ```

---

## ⚙️ 配置文件说明 (`config.yaml`)

```yaml
server:
  host: "0.0.0.0"
  port: 8888
  secret_key: "lemon-emby-admin-secret-key-change-me"  # Web API 管理密钥

emby:
  server_url: "http://127.0.0.1:8096"        # Emby 服务器地址
  api_key: "your_emby_admin_api_key_here"   # Emby 管理员 API Key
  public_url: "https://emby.example.com"     # 用户公网访问地址
  template_user_id: ""                       # 可选：模板用户 ID（自动继承库权限）
  default_max_devices: 2                     # 默认最大播放设备限制

telegram:
  bot_token: "1234567890:ABCdefGHIjklMNOpqrsTUVwxyz" # Telegram Bot Token
  admin_ids:
    - 7996620779                             # 管理员 TG ID
  enable_checkin: true                       # 开启每日签到
  checkin_reward_days: 1                     # 签到赠送天数
  checkin_points: 10                         # 签到获得积分

rules:
  check_interval_minutes: 5                  # 巡检频率（分钟）
  warn_days_before_expiry: 3                 # 提前预警天数
  auto_disable_expired: true                 # 到期自动冻结
  max_concurrency_kill: true                 # 超出并发播放自动踢下线
```

---

## 🎮 Telegram 指令速查

### 👤 普通用户指令
| 指令 | 说明 |
| :--- | :--- |
| `/start` | 打开主控面板与 Inline 菜单 |
| `/my` | 查看个人账号状态、到期时间、积分 |
| `/checkin` | 每日签到领时长与积分 |
| `/bind <账号> <密码>` | 开通或绑定 Emby 账号 |
| `/redeem <卡密>` | 兑换卡密充值续期 |
| `/resetpw <新密码>` | 自助修改 Emby 登录密码 |

### 👑 管理员特权指令
| 指令 | 说明 |
| :--- | :--- |
| `/gen <天数> [张数]` | 批量生成天数充值卡密 |
| `/status` | 查看 Emby 实时负载与活跃播放流 |
| `/users` | 查看已登记的用户列表 |
| `/addtime <用户名> <天数>` | 手动为用户增加有效期 |
| `/ban <用户名>` | 手动禁用/封禁用户 |
| `/unban <用户名>` | 解除用户封禁 |

---

## 📄 License
MIT License © 2026 nayeshiluo

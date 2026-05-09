# Docker 部署指南

## 飞牛NAS / 任意 Docker 环境部署

### 快速开始

```bash
# 1. 进入 docker 目录
cd docker

# 2. 复制配置文件，填入账号密码
cp .env.example .env
nano .env

# 3. 启动
docker-compose up -d

# 4. 查看日志
docker-compose logs -f
```

### 配置说明

编辑 `.env` 文件：

| 变量 | 必填 | 推荐值 | 说明 |
|------|------|--------|------|
| `LINUXDO_USERNAME` | ✅ | 留空后自行填写 | Linux.do 用户名 |
| `LINUXDO_PASSWORD` | ✅ | 留空后自行填写 | Linux.do 密码 |
| `RUN_MODE` | ❌ | endless | 运行模式：`endless` 无尽、`schedule` 定时、`once` 单次 |
| `BROWSE_MODE` | ❌ | deep | 浏览模式：`deep` 深度爬楼、`quick` 轻度速览 |
| `ENABLE_LIKE` | ❌ | false | 是否启用自动点赞 |
| `ENABLE_REPLY` | ❌ | false | 是否启用自动回复；Docker 版暂不支持回复 |
| `LIKE_RATE` | ❌ | 0 | 点赞概率 (0-100)，`ENABLE_LIKE=false` 时不生效 |
| `RUN_ON_START` | ❌ | true | `schedule` 模式启动时是否立即运行一次 |
| `RUNS_PER_DAY` | ❌ | 1 | `schedule` 模式每天运行次数 |
| `TOPICS_MIN` | ❌ | 8 | `schedule` / `once` 模式每次最少浏览帖子数 |
| `TOPICS_MAX` | ❌ | 18 | `schedule` / `once` 模式每次最多浏览帖子数 |
| `CONTAINER_NAME` | ❌ | linuxdo-bot | 容器名称 |
| `TZ` | ❌ | Asia/Shanghai | 容器时区 |
| `CHROME_USER_DATA` | ❌ | /app/chrome-data | Chrome 用户数据目录，默认已持久化 |
| `MEMORY_LIMIT` | ❌ | 1G | 内存限制 |
| `CPU_LIMIT` | ❌ | 1.0 | CPU 限制 |
| `MANUAL_CONTAINER_NAME` | ❌ | linuxdo-manual-login | 手动登录容器名称 |
| `NOVNC_BIND` | ❌ | 127.0.0.1 | noVNC 监听地址，默认仅本机访问 |
| `NOVNC_PORT` | ❌ | 6080 | noVNC 端口 |
| `MANUAL_LOGIN_URL` | ❌ | https://linux.do/login | 手动登录时打开的地址 |
| `SCREEN_WIDTH` | ❌ | 1280 | 手动登录浏览器宽度 |
| `SCREEN_HEIGHT` | ❌ | 800 | 手动登录浏览器高度 |
| `SHM_SIZE` | ❌ | 1gb | 手动登录容器共享内存大小 |
| `DEBUG` | ❌ | 留空 | 填 `1` 可开启调试日志 |

### 首次登录 / 滑块验证

如果服务器首次登录时出现滑块、点选等验证，先用手动登录容器完成一次真人验证。它会和自动任务共用 `chrome-data`，登录状态会保留下来。

```bash
# 1. 停止自动任务，避免 Chrome 配置目录被两个容器同时占用
docker compose down

# 2. 启动手动登录容器
docker compose -f docker-compose.manual.yml up -d --build

# 3. 建议在本机开 SSH 隧道访问 noVNC
ssh -L 6080:127.0.0.1:6080 root@你的服务器IP

# 4. 在本机浏览器打开
# http://127.0.0.1:6080/vnc.html?autoconnect=true&resize=scale
```

在 noVNC 页面里手动登录 Linux.do 并完成滑块验证。确认登录成功后：

```bash
# 停止手动登录容器
docker compose -f docker-compose.manual.yml down

# 启动自动任务
docker compose up -d --build
docker compose logs -f
```

如果不想用 SSH 隧道，可以把 `.env` 里的 `NOVNC_BIND=127.0.0.1` 改成 `NOVNC_BIND=0.0.0.0`，然后访问 `http://服务器IP:6080/vnc.html?autoconnect=true&resize=scale`。这样会把无密码远程桌面暴露到公网，不建议长期打开。

### 推荐无尽深度爬楼配置

如果只想让服务器一直深度爬楼、不点赞、不回复，`.env` 保持下面这样即可：

```env
RUN_MODE=endless
BROWSE_MODE=deep
ENABLE_LIKE=false
ENABLE_REPLY=false

RUN_ON_START=true
CONTAINER_NAME=linuxdo-bot
TZ=Asia/Shanghai
CHROME_USER_DATA=/app/chrome-data
MEMORY_LIMIT=1G
CPU_LIMIT=1.0
DEBUG=
```

停止无尽模式：

```bash
docker compose down
```

### 运行机制

- `RUN_MODE=endless`：启动后持续浏览，不自动停止，直到手动 `docker compose down`
- `RUN_MODE=schedule`：启动后按 `RUNS_PER_DAY` 在 7:00-23:00 之间随机定时运行
- `RUN_MODE=once` 或 `docker compose run --rm linuxdo --once`：只运行一次
- `BROWSE_MODE=deep`：每个帖子尽量按楼层计数器深度爬到末楼
- `BROWSE_MODE=quick`：每个帖子只随机滚动 3-8 次
- 浏览器数据持久化，登录状态会保持

### 常用命令

```bash
# 启动
docker-compose up -d

# 停止
docker-compose down

# 查看日志
docker-compose logs -f

# 重启
docker-compose restart

# 重新构建（更新代码后）
docker-compose up -d --build

# 只运行一次（不启动调度器）
docker-compose run --rm linuxdo --once
```

### 资源占用

- 内存限制: 1GB
- CPU 限制: 1 核
- 磁盘: Chrome 数据约 200MB

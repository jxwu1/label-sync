# 部署 Plan — Hetzner + Docker (内网访问)

**起草**: 2026-05-14
**场景**: Hetzner 租用服务器 (Linux) + Docker + 公司内网访问 (不对外)
**数据库**: 继续 SQLite (服务器是唯一写源)

---

## 出门前必做 (工作 PC, 防止后台 backtest 死)

1. **Push 最新 commit**
   ```bash
   git push
   ```
2. **别关 Claude Code 窗口** (最小化 OK; 关掉 → shell 死 → backtest 子进程死)
3. **别 logout / 切换用户** (锁屏 Win+L OK; logoff 会杀进程)
4. **Power 设置**: Settings → System → Power → Screen and sleep → **Never sleep**
5. **Windows Update**: Active hours 调成 00:00-23:59 防半夜重启
6. **确认家里能 SSH 上 Hetzner**: 出门前 `ssh root@<hetzner_ip>` 测一次

---

## 回家后部署 (Hetzner 服务器, 空 DB 阶段)

### 1. SSH 上服务器
```bash
ssh root@<hetzner_ip>
# Hetzner Cloud 默认用 root + SSH key
```

### 2. 检查 Docker
```bash
docker --version
docker compose version
# 如未装: curl -fsSL https://get.docker.com | sh
```

### 3. 准备项目目录 (跟其他项目隔离)
```bash
mkdir -p /opt/projects && cd /opt/projects
git clone https://github.com/jxwu1/label-sync.git
cd label-sync
```

### 4. 准备数据卷
```bash
mkdir -p ./data/input ./data/output ./data/transfer ./data/垃圾桶 ./data/archive
```

### 5. Hetzner 防火墙 — 放行 5000

**两层防火墙都要看**:

#### a) Hetzner Cloud Firewall (面板)
- 控制台 → Firewalls → 编辑规则
- 加 Inbound: `TCP 5000` 源 IP: 公司出口 IP (CIDR), 比如 `203.0.113.42/32`
- **不要** 设 `0.0.0.0/0`! (那就对外开了)

#### b) 服务器 OS 防火墙 (ufw, 如果开了)
```bash
sudo ufw status
# 如果 active:
sudo ufw allow from <office_cidr> to any port 5000 proto tcp
```

### 6. Build + 起容器
```bash
docker compose up -d --build
# 第一次会 build, 大概 2-3 分钟
```

### 7. 看启动日志
```bash
docker compose logs -f label-sync
```

期待看到:
```
INFO  [alembic.runtime.migration] Running upgrade ... -> b9e1c4f8a3d2
Serving on http://0.0.0.0:5000
```

Ctrl+C 退出查看 (容器继续跑 background)。

### 8. 服务器本机自测
```bash
curl -I http://localhost:5000/
# 期待 HTTP/1.1 200 OK
```

### 9. 公司员工 PC 浏览器测
```
http://<hetzner_public_ip>:5000/
```
A 端首页出来 = 部署成功 (数据是空的, 正常)。

---

## 明天回公司后接数据

### 1. 确认 backtest 跑完 (在工作 PC)
```
读 Claude Code 输出文件:
C:\Users\64474\AppData\Local\Temp\claude\C--Dev-label-sync\<id>\tasks\<task-id>.output
看到 "ALL DONE  total Xh" 才算完
```

### 2. 服务器停容器 (避免 rsync 时写冲突)
```bash
ssh root@<hetzner_ip> "cd /opt/projects/label-sync && docker compose down"
```

### 3. rsync DB (从工作 PC 推到 Hetzner)

**WSL / Git Bash 推荐**:
```bash
rsync -avz --progress \
  /c/Dev/label-sync/stockpile.db \
  root@<hetzner_ip>:/opt/projects/label-sync/data/
```

**PowerShell 替代**:
```powershell
scp C:\Dev\label-sync\stockpile.db root@<hetzner_ip>:/opt/projects/label-sync/data/
```

stockpile.db 估算: 灌库后 ~100-300MB, Hetzner 带宽足够, 几分钟内完。

### 4. 重启容器
```bash
ssh root@<hetzner_ip> "cd /opt/projects/label-sync && docker compose up -d"
```

### 5. 确认数据齐
浏览器 → SKU 列表应有 27,340 行 (active SKUs)。

---

## 兜底排查

| 症状 | 检查 |
|---|---|
| `docker compose up` build 失败 | `docker compose build --no-cache` 看完整 trace |
| 容器起来立刻死 | `docker compose logs label-sync` |
| `alembic upgrade head` 失败 | 进容器查: `docker compose exec label-sync alembic current` |
| curl localhost 通,公司 PC 不通 | Hetzner Cloud Firewall 没放行 5000, 或 ufw 没放行 |
| 公司 PC 也不通 | `nmap -p 5000 <hetzner_ip>` (从公司 PC 跑) 看是不是 filtered |
| 容器活但页面 500 | `docker compose logs label-sync --tail 100` 看 traceback |
| 容器 OOM | `docker stats label-sync` 看内存; 给 Hetzner VM 升内存或 backtest 别在容器里跑 |

---

## 后续运维 cheatsheet

```bash
# 看日志 (实时)
docker compose logs -f label-sync

# 看日志 (尾部 100 行)
docker compose logs label-sync --tail 100

# 重启容器 (不重新 build)
docker compose restart label-sync

# 停 + 起
docker compose down && docker compose up -d

# 代码更新流程
git pull
docker compose up -d --build       # 不需要 down, 自动滚动

# 进容器 debug
docker compose exec label-sync sh

# 容器状态
docker compose ps
docker stats label-sync

# 备份 DB (DB 还在写时也安全 — SQLite WAL 快照)
ssh root@<hetzner_ip> "sqlite3 /opt/projects/label-sync/data/stockpile.db '.backup /tmp/stockpile-$(date +%Y%m%d).db'"
scp root@<hetzner_ip>:/tmp/stockpile-*.db .

# 升级 alembic (代码 pull 后):
docker compose down
docker compose up -d --build       # 容器启动时自动 alembic upgrade head
```

---

## 后续可能要做的事

1. **加自动备份**: cron + sqlite3 .backup → 推到 Hetzner Storage Box 或其他位置
2. **HTTPS 内网**: mkcert + nginx, 如果合规要求
3. **加监控**: Hetzner Cloud 自带基础, 或 Uptime Kuma 容器
4. **rsync 自动化**: 本地 → 服务器 的数据同步如有需要 (现在不需要, 服务器是唯一写源)
5. **资源限制**: docker compose 里加 `deploy.resources.limits.memory` 防 backtest 跑挂其他项目

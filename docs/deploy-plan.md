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

## 明天回公司后接数据 (Coolify 版)

> **场景**: 工作 PC backtest 跑完后, 把真 DB 推到 Hetzner 替换今晚那份家用 PC 上传的版本。
> **服务器路径**: `/data/coolify/applications/k11qu29j1y7wy1njh9eb5edj/data/stockpile.db`
> **Hetzner IP**: `178.104.148.102`

### 1. 确认 backtest 完全跑完 (工作 PC)
- Claude Code output 看到 `ALL DONE total Xh`
- 任务管理器确认没残留 Python 进程在写 stockpile.db (`Get-Process python` 看 0 个)
- backtest 留的 WAL/SHM 还在的话, 先做 checkpoint:
  ```powershell
  python -c "import sqlite3; c=sqlite3.connect('stockpile.db'); c.execute('PRAGMA wal_checkpoint(TRUNCATE)'); c.close()"
  ```

### 2. 本地完整性检查 (防止传坏库)
```powershell
python -c "import sqlite3; print(sqlite3.connect('stockpile.db').execute('PRAGMA integrity_check').fetchone())"
# 必须看到 ('ok',)
```
出 `('ok',)` 才传, 否则先 `.backup` 出 snapshot 用 snapshot。

### 3. Coolify 停应用
- UI: `http://178.104.148.102:8000` → erp project → label-sync → **Stop**
- 弹窗里 **取消勾选** "Run Docker Cleanup" → Confirm
- 第二个弹窗 (Warning: non-persistent data will be deleted) → Confirm
  - `./data` 是 bind mount, 在 host 磁盘上, 不会被删

### 4. 清服务器残留 WAL/SHM + scp 主库

**关键**: 必须 `rm -f` 把旧的 -wal / -shm 一起清掉, 否则新主库配旧 WAL 会数据错乱。

```powershell
ssh root@178.104.148.102 "rm -f /data/coolify/applications/k11qu29j1y7wy1njh9eb5edj/data/stockpile.db /data/coolify/applications/k11qu29j1y7wy1njh9eb5edj/data/stockpile.db-shm /data/coolify/applications/k11qu29j1y7wy1njh9eb5edj/data/stockpile.db-wal"
scp stockpile.db root@178.104.148.102:/data/coolify/applications/k11qu29j1y7wy1njh9eb5edj/data/
```

灌库后 stockpile.db 估算 ~100-300MB, scp 几分钟内完 (Hetzner EU 带宽足)。

### 5. 服务器端校验
```powershell
ssh root@178.104.148.102 "python3 -c \"import sqlite3; c=sqlite3.connect('/data/coolify/applications/k11qu29j1y7wy1njh9eb5edj/data/stockpile.db'); print('alembic:', c.execute('SELECT * FROM alembic_version').fetchall()); print('stockpile rows:', c.execute('SELECT COUNT(*) FROM stockpile').fetchone()[0]); print('integrity:', c.execute('PRAGMA integrity_check').fetchone())\""
```
三项都要对得上预期 (alembic 版本 = head 或本地版本; 行数 ≈ 工作 PC 上的数; integrity = ok)。

### 6. Coolify 重新 Deploy
- UI → 应用 → 右上 **Deploy**
- 看 logs 等 `alembic upgrade head` 跑完 + `Serving on http://0.0.0.0:5000`
- 没必要 force rebuild — image 没变, 直接重启容器即可

### 7. 浏览器验数据
打开 Coolify 给的临时域名 (`*.178.104.148.102.sslip.io`) → SKU 列表看 active SKU 数 ≈ 27,340。

---

## 排错速查 (明天版)

| 症状 | 检查 |
|---|---|
| Deploy 后又是 `bash: -c: option requires an argument` | Build Pack 又被切回 Dockerfile 了, 改回 Docker Compose + Location `/docker-compose.yml` |
| `alembic ... already exists` | DB 半成品状态, 重新走第 4 步 (彻底清 db + wal + shm 再传) |
| `sqlite3.DatabaseError: database disk image is malformed` | 本地没做 wal_checkpoint 就直接 scp, 重新 checkpoint → integrity_check → 再传 |
| Coolify 临时域名 502 | 容器还在起, 看 logs; 或 Traefik label 失效, redeploy |
| 容器健康, 页面 500 | `ssh ... "docker logs <coolify-uuid容器名> --tail 100"` 看 traceback |

---

## 2026-05-14 部署踩坑记录

**坑 1: Coolify 默认 Build Pack 不是 Docker Compose**
- 选 Dockerfile / Nixpacks 时 Coolify 自己渲染一份 compose, **完全忽略** 仓库的 `docker-compose.yml`
- 表现: 端口默认 3000 (我们要 5000)、env vars 丢失、volume 不挂、Entrypoint 改成 `["/bin/bash","-l","-c"]` Cmd 空 → 容器报 `bash: -c: option requires an argument` 循环重启
- 修: General → Build Pack → Docker Compose; Compose Location 填 `/docker-compose.yml` (注意 `.yml` 不是默认的 `.yaml`)

**坑 2: alembic baseline 是空 upgrade(), 不能在空 DB 上 bootstrap**
- `cf04ed0496f7_baseline_reflect_existing_schema.py` 的 `upgrade()` 只 `pass`
- 历史: 项目早期没用 alembic, baseline 是"反射"线上已存在的 schema, 不创建任何表
- 后果: 新 DB 上 `alembic upgrade head` → cf04ed0496f7 不建表 → 2385c879eb58 第 86 行 `SELECT FROM stockpile` 炸 (no such table), 但前面 `CREATE TABLE stockpile_locations` 已成功 → SQLite DDL 不可回滚 → 版本停在 cf04ed0496f7 + 半成品表 → 下次启动 `already exists`
- 修: 不在空 DB 上部署。今晚 scp 本地 prod stockpile.db (alembic_version=68b4bbea9edd, 45,610 行) 上去再起容器
- 长期 fix 候选 (没做): 重写 cf04ed0496f7 用 raw SQL dump 完整 schema, 让空 DB 也能 self-bootstrap

**坑 3: ports vs expose**
- 原 compose `ports: "5000:5000"` 直接绑主机端口, 不走 Coolify Traefik
- 选了 Coolify 临时域名方案后改成 `expose: ["5000"]`, 让 Traefik 通过容器网络反代
- commit `afb0dfb`

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

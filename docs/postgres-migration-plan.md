# PostgreSQL 迁移 Plan（label-sync + AthenNest + bagstore 统一到 shared PG）

> **状态**: Plan 阶段，未开工
> **创建**: 2026-05-18
> **目标**: 一次到位，短期内不再动 DB 层

---

## 1. 背景与决策

### 起点

服务器（Hetzner CPX42, 8 vCPU / 16 GB RAM / 320 GB SSD, IP `178.104.148.102`）当前运行三个项目：

| 项目 | 容器 | DB 形态 |
|---|---|---|
| label-sync (ERP) | `label-sync-k11qu29j...` | **SQLite** (`/data/stockpile.db`, 470 MB) |
| AthenNest | `yzotz6krqbauipsthr2b6e8f` | PostgreSQL container, `postgis/postgis:17-3.5-alpine` |
| bagstore | `x12yyqjugblxlwc5851luv6n` | PostgreSQL container, `postgres:18-alpine` |

### 终态

```
新 shared-pg 容器: postgis/postgis:17-3.5-alpine
├── db: label_sync   (用户 ls_app)   ← 新建，从 SQLite 灌入
├── db: athennest    (用户 an_app, 需 CREATE EXTENSION postgis)
└── db: bagstore     (用户 bs_app)
```

旧两个 PG 容器退役。

### 关键决策

- **共享 PG**（不再走"per-project 独立 PG"）：项目多、维护精力有限、label-sync SLA 容忍中断 → 维护成本 O(1) 大于故障隔离价值。RAM 16 GB 不构成约束
- **镜像选 `postgis/postgis:17-3.5-alpine`**：兼容 AthenNest 的 PostGIS 需求；label-sync / bagstore 不开 PostGIS 扩展即可
- **bagstore 接受 PG 18 → 17 降级**：兼容性核查（见 §2.3）表明无 PG 18 专属特性
- **PostGIS 18 出来后整体升级**：未来用 pg_upgrade 或 dump/restore 统一升 PG 18 PostGIS（不在本 plan 范围）

---

## 2. 应用层适配（仅 label-sync 需要）

### 2.1 SQLite 强耦合点清单

| 位置 | 问题 | 修复方向 |
|---|---|---|
| `app/models.py` × 9 处 | `server_default=text("(datetime('now','localtime'))")` — SQLite 专属 | 改成 `server_default=func.current_timestamp()`（PG/SQLite 双兼容） |
| `app/models.py:49` + `app/repositories/stockpile_db.py:80, 124` | `PRAGMA journal_mode=WAL` event listener | 用 `engine.dialect.name == 'sqlite'` 包起来 |
| `app/repositories/stockpile_db.py:74` | `create_engine(f"sqlite:///{db_path}")` 写死 | 读 `DATABASE_URL` env，回退 SQLite |
| `app/repositories/stockpile_db.py:116` | `_connect()` 用 raw `sqlite3.Connection`（维护脚本依赖） | gate 到 SQLite-only 或重写为 SQLAlchemy raw connection |
| `requirements.txt` | 缺 `psycopg[binary]` | 加 |

### 2.2 非问题点（已验证）

- ORM 全走 SQLAlchemy 2.x，无 raw SQL
- 无 `INSERT OR IGNORE` / `||` 字符串拼接 / SQLite `strftime()` SQL（Python 侧 strftime 安全）
- `alembic/env.py` 已支持 `DATABASE_URL` env 覆盖（line 17-22）
- Dockerfile 不需要改，`psycopg[binary]` 自带 libpq wheel

### 2.3 bagstore 兼容性核查（PG 18 → 17 降级）

读完 `C:\Dev\bagstore\docs\BagStore_ClaudeCode_Guide.md`，schema 用到的特性：

- `cuid()` IDs / `String` / `Int` / `Boolean` / `DateTime` / `Decimal(10,2)` / `Text` / `JSON` (JSONB) / PG enums / `@default(now())` / `@updatedAt` / 多对多 / 索引

全部 PG 12+ 即支持。**无 PG 18 专属特性，降版本安全。**

### 2.4 AthenNest 适配

无版本迁移（PostGIS 17 → PostGIS 17），仅迁数据 + 改 DATABASE_URL，不需要应用代码改动。

---

## 3. PR 序列

### PR-A · label-sync 应用层 schema 可移植性

**分支**: `chore/db-portability`

**任务**:

1. `app/models.py`: 9 处 `datetime('now','localtime')` 替换为 `server_default=func.current_timestamp()`（imports `from sqlalchemy import func`）
2. `app/repositories/stockpile_db.py`:
   - `_build_engine`: 读 `os.getenv("DATABASE_URL")`，回退 `f"sqlite:///{CONFIG.stockpile_db}"`
   - PRAGMA event listener 改为 `if dbapi_conn.__class__.__module__.startswith('sqlite3'):` 或用 `engine.url.drivername == 'sqlite'` 判断
   - `_connect()` 保留但加 `assert _engine().url.drivername == 'sqlite'`，让在 PG 时主动报错（暴露出还有维护脚本依赖 SQLite 的地方）
3. `app/models.py:49` PRAGMA listener 同上 gate
4. `requirements.txt`: 加 `psycopg[binary]>=3.2`

**验收**:

- `pytest tests/` 全过（仍跑 SQLite）
- 本地手动设 `DATABASE_URL=postgresql+psycopg://...` 启动 server.py 能连上（PR-B 会做完整 dry run）
- `git diff` 不超过 50 行（局部修改）

**不做**: ETL 脚本、Coolify 配置、实际切流量

---

### PR-B · label-sync 本地端到端 PG dry run

**分支**: `chore/db-local-dryrun`

**任务**:

1. **本地起 PostGIS 17 dev 容器**

   新增 `docker-compose.dev.yml`（不动生产 `docker-compose.yml`）：

   ```yaml
   services:
     dev-pg:
       image: postgis/postgis:17-3.5-alpine
       container_name: label-sync-dev-pg
       environment:
         POSTGRES_USER: dev
         POSTGRES_PASSWORD: devpass
         POSTGRES_DB: label_sync
       ports:
         - "5433:5432"  # 避开本机已有 PG 端口
       volumes:
         - ./.dev/pg-data:/var/lib/postgresql/data
   ```

   `.dev/` 加进 `.gitignore`

2. **写 ETL 脚本** `tools/sqlite_to_pg.py`

   骨架：

   ```python
   """SQLite → PostgreSQL 数据迁移。

   前置条件:
       1. 目标 PG 已通过 `alembic upgrade head` 建好空 schema
       2. DATABASE_URL 环境变量指向目标 PG
       3. --source 指向 SQLite 文件

   用法:
       DATABASE_URL=postgresql+psycopg://dev:devpass@localhost:5433/label_sync \\
           python tools/sqlite_to_pg.py --source ./stockpile.db
   """

   from __future__ import annotations
   import argparse
   import sqlite3
   from sqlalchemy import create_engine, text, MetaData, Table
   from sqlalchemy.orm import Session

   # 迁移顺序遵守外键依赖（无 FK 父表先走）
   TABLE_ORDER = [
       "schema_meta",
       "import_profiles",
       "stockpile_snapshots",
       "suppliers",
       "customers",
       "foreign_customer_records",
       "stockpile",
       "stockpile_locations",
       "stockpile_changes",
       "inventory_imports",
       "inventory_events",        # 主表 1.36M 行
       "backtest_runs",
       "backtest_results",
   ]

   BATCH_SIZE = 50_000

   def migrate_table(sqlite_conn, pg_session, table_name):
       cur = sqlite_conn.cursor()
       cur.execute(f'SELECT COUNT(*) FROM "{table_name}"')
       total = cur.fetchone()[0]
       if total == 0:
           print(f"  {table_name}: empty, skip")
           return

       cur.execute(f'SELECT * FROM "{table_name}"')
       cols = [d[0] for d in cur.description]

       # 用 SQLAlchemy Core insert 走 bulk
       meta = MetaData()
       table = Table(table_name, meta, autoload_with=pg_session.get_bind())

       inserted = 0
       batch = []
       for row in cur:
           batch.append(dict(zip(cols, row)))
           if len(batch) >= BATCH_SIZE:
               pg_session.execute(table.insert(), batch)
               pg_session.commit()
               inserted += len(batch)
               print(f"  {table_name}: {inserted:,}/{total:,}")
               batch = []
       if batch:
           pg_session.execute(table.insert(), batch)
           pg_session.commit()
           inserted += len(batch)
       print(f"  {table_name}: done ({inserted:,} rows)")

   def reset_sequences(pg_session):
       # 表内有 SERIAL/IDENTITY 列时，必须把 sequence 推到 max(id) + 1
       # 否则 ORM 后续 INSERT 会拿到旧的小 id 撞唯一约束
       sql = """
       SELECT 'SELECT setval(pg_get_serial_sequence(''' || quote_ident(table_name)
              || ''',''' || quote_ident(column_name)
              || '''), COALESCE(MAX(' || quote_ident(column_name)
              || '), 1)) FROM ' || quote_ident(table_name) AS stmt
       FROM information_schema.columns
       WHERE table_schema = 'public'
         AND column_default LIKE 'nextval%';
       """
       stmts = [r[0] for r in pg_session.execute(text(sql))]
       for s in stmts:
           pg_session.execute(text(s))
       pg_session.commit()

   def verify_counts(sqlite_conn, pg_session):
       cur = sqlite_conn.cursor()
       for t in TABLE_ORDER:
           cur.execute(f'SELECT COUNT(*) FROM "{t}"')
           sqlite_n = cur.fetchone()[0]
           pg_n = pg_session.execute(text(f'SELECT COUNT(*) FROM "{t}"')).scalar()
           status = "OK" if sqlite_n == pg_n else "MISMATCH"
           print(f"  {t}: SQLite={sqlite_n:,} PG={pg_n:,} {status}")

   def main():
       ap = argparse.ArgumentParser()
       ap.add_argument("--source", required=True, help="SQLite file path")
       ap.add_argument("--dsn", help="Override DATABASE_URL")
       args = ap.parse_args()

       import os
       dsn = args.dsn or os.environ["DATABASE_URL"]
       sqlite_conn = sqlite3.connect(args.source)
       pg_engine = create_engine(dsn, future=True)

       with Session(pg_engine) as session:
           print("=== migration ===")
           for t in TABLE_ORDER:
               migrate_table(sqlite_conn, session, t)
           print("=== reset sequences ===")
           reset_sequences(session)
           print("=== verify ===")
           verify_counts(sqlite_conn, session)

   if __name__ == "__main__":
       main()
   ```

3. **dry run 流程**

   ```powershell
   # 起 dev PG
   docker compose -f docker-compose.dev.yml up -d

   # 建 schema
   $env:DATABASE_URL = "postgresql+psycopg://dev:devpass@localhost:5433/label_sync"
   python -m alembic upgrade head

   # 跑 ETL
   python tools/sqlite_to_pg.py --source ./stockpile.db

   # 启 server，浏览器跑核心流程
   python server.py
   ```

**验收**:

- `tools/sqlite_to_pg.py` 跑完，verify 阶段所有 13 张表 row count 一致
- `server.py` 启动无报错，浏览器手动跑：扫码解析（phase 1）、stockpile 匹配（phase 2）、月度汇总查询、analytics dashboard
- `pytest tests/` 在 `DATABASE_URL=postgresql+psycopg://...` 下也全过（暴露隐藏的 SQLite 假设）

**风险**:

- `datetime('now','localtime')` 改成 `current_timestamp()` 后，时区从希腊本地变成 UTC（PG 默认）。需在 Coolify env 设 `TZ=Europe/Athens` 或代码侧改 timestamp 类型为 `TIMESTAMP WITH TIME ZONE`。本 PR 跑通后视情况决定

---

### PR-C · Coolify 上起 shared-pg + label-sync 切流量

**分支**: `feat/postgres-cutover`（生产分支，必须先经过 PR-A、PR-B 验证）

#### 准备（不动生产，单独 session 做）

1. **Coolify 新建项目** `infrastructure`
2. **新建 PostgreSQL service**:
   - Image: `postgis/postgis:17-3.5-alpine`
   - Service 名: `shared-pg17`
   - 资源限制: 2 GB RAM（之后视需要调）
   - `POSTGRES_PASSWORD` superuser 密码 → 直接登记到 1Password Servers vault
3. **数据库 + 用户**（用 Coolify terminal 或 `docker exec`）:

   ```sql
   CREATE DATABASE label_sync;
   CREATE USER ls_app WITH PASSWORD '<强密码A>';
   GRANT CONNECT ON DATABASE label_sync TO ls_app;
   \c label_sync
   GRANT ALL PRIVILEGES ON SCHEMA public TO ls_app;
   ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO ls_app;
   ```

4. **凭据登记到 1Password Servers vault**:
   - `shared-pg17 / superuser` (postgres / <pw>)
   - `shared-pg17 / label_sync / ls_app` (ls_app / <pwA>)
   - 字段附完整 `DATABASE_URL=postgresql+psycopg://ls_app:<pwA>@shared-pg17:5432/label_sync`
5. **连通性测试**: 在 Coolify shell 上 `psql -h shared-pg17 -U ls_app -d label_sync -c '\l'`，确认密码正确

#### Cutover（维护窗口，预计 30-60 分钟）

> **维护窗口建议**: 周末或公司下班后。label-sync 内网用，挂 30 分钟无业务影响。

1. **停 label-sync 写入**:
   - Coolify 上 label-sync service → Stop（或路由切静态维护页）
   - 通知公司端"系统升级中"
2. **拉生产 SQLite**:

   ```bash
   ssh root@178.104.148.102
   docker cp label-sync-k11qu29j...:/data/stockpile.db /tmp/stockpile-prod.db
   ls -lh /tmp/stockpile-prod.db   # 确认有数据
   ```

3. **本地或服务器跑 ETL**（哪边网络好用哪边）:

   ```bash
   # 在服务器上的临时 Python 容器里跑
   docker run --rm \
     --network <coolify-network-name> \
     -v /tmp/stockpile-prod.db:/data/stockpile.db:ro \
     -v $(pwd)/tools:/tools \
     -e DATABASE_URL=postgresql+psycopg://ls_app:<pwA>@shared-pg17:5432/label_sync \
     python:3.12 \
     bash -c "pip install psycopg[binary] sqlalchemy alembic && \
              cd /tools && python sqlite_to_pg.py --source /data/stockpile.db"
   ```

   或者本地跑（先 scp 下来再跑）

4. **alembic upgrade head**（如果 PR-A/B 还没合就先在迁数据前跑）:

   ```bash
   DATABASE_URL=postgresql+psycopg://ls_app:<pwA>@shared-pg17:5432/label_sync \
       python -m alembic upgrade head
   ```

   注意顺序：先 alembic（建空 schema） → 再 ETL（灌数据）

5. **改 Coolify 上 label-sync 的环境变量**:
   - 新增 `DATABASE_URL=postgresql+psycopg://ls_app:<pwA>@shared-pg17:5432/label_sync`
   - 配置 Coolify "Connect to other resources" 把 label-sync 挂到 shared-pg17 网络
6. **Redeploy label-sync**:
   - Coolify Dashboard → label-sync → Redeploy
   - 看启动日志，确认连上 shared-pg17
7. **烟雾测试**:
   - 浏览器打开 label-sync 首页
   - 跑一遍 phase 1 扫码上传
   - 查 analytics dashboard 看历史数据是否完整
   - SQL 验证: `SELECT COUNT(*) FROM inventory_events;` 跟 SQLite 一致
8. **观察 24 小时**:
   - 看 Coolify 日志有无报错
   - 公司端日常使用确认无异常

#### 回滚

如果 cutover 当天就发现严重问题：

1. Coolify 上 label-sync 删 `DATABASE_URL` env var → redeploy
2. 应用回退到读 `/data/stockpile.db`
3. 期间在 PG 写入的新数据**会丢**（最多 30 分钟，可接受）

#### 保留期

- `/tmp/stockpile-prod.db` 转存到 `/data/backups/stockpile-pre-pg-cutover.db`
- 保留 30 天作终极回滚保险

**验收**:

- label-sync 在 shared-pg17 上跑了 ≥ 7 天无明显异常
- 行数比对 OK
- 公司端日常使用反馈正常

---

### PR-D · AthenNest 并入 shared-pg

**分支**: 不在 label-sync repo 范畴，在 AthenNest repo 内做

**前置**: PR-C 已合并并稳定运行 ≥ 1 周

**任务**:

1. shared-pg17 上建 athennest database + user:

   ```sql
   CREATE DATABASE athennest;
   CREATE USER an_app WITH PASSWORD '<强密码B>';
   GRANT CONNECT ON DATABASE athennest TO an_app;
   \c athennest
   CREATE EXTENSION postgis;
   GRANT ALL PRIVILEGES ON SCHEMA public TO an_app;
   GRANT ALL PRIVILEGES ON SCHEMA topology TO an_app;  -- postgis 装好后有这个 schema
   ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO an_app;
   ```

2. 旧 PostGIS 17 容器 pg_dump:

   ```bash
   docker exec yzotz6krqbauipsthr2b6e8f \
       pg_dump -U postgres -Fc athennest > /tmp/athennest.dump
   ```

3. 灌入 shared-pg17:

   ```bash
   docker exec -i shared-pg17 \
       pg_restore -U postgres -d athennest --no-owner --role=an_app < /tmp/athennest.dump
   ```

4. AthenNest Coolify env: `DATABASE_URL` 改指向 shared-pg17，redeploy
5. 烟雾测试（浏览器跑首页 / 房源列表 / 空间查询）
6. 观察 ≥ 7 天
7. **退役**旧 PostGIS 17 容器（Coolify 上停服 → 删 service）

**回滚**: AthenNest env 改回旧容器名，redeploy

---

### PR-E · bagstore 并入 shared-pg（PG 18 → 17 降级）

**分支**: 不在 label-sync repo 范畴，在 bagstore repo 内做

**前置**: PR-D 已合并并稳定运行 ≥ 1 周

**任务**:

1. shared-pg17 上建 bagstore database + user:

   ```sql
   CREATE DATABASE bagstore;
   CREATE USER bs_app WITH PASSWORD '<强密码C>';
   GRANT CONNECT ON DATABASE bagstore TO bs_app;
   \c bagstore
   GRANT ALL PRIVILEGES ON SCHEMA public TO bs_app;
   ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO bs_app;
   ```

2. **降版本 dump 策略**: 用 `--data-only --inserts` 避免依赖 PG 18 内部 binary 格式

   ```bash
   docker exec x12yyqjugblxlwc5851luv6n \
       pg_dump -U postgres --data-only --inserts --no-owner bagstore > /tmp/bagstore-data.sql
   ```

3. **schema 由 Prisma 重建**（不从 PG 18 dump schema，避免 PG 18 语法）:

   ```bash
   # bagstore repo 本地
   DATABASE_URL=postgresql://bs_app:<pwC>@<host>:5432/bagstore \
       npx prisma migrate deploy
   ```

   这会在 shared-pg17 上按 bagstore 的 Prisma migrations 历史从零建表，结构和 PG 18 那边完全一致

4. 灌入数据:

   ```bash
   docker exec -i shared-pg17 \
       psql -U bs_app -d bagstore < /tmp/bagstore-data.sql
   ```

5. bagstore Coolify env: `DATABASE_URL` 指向 shared-pg17，redeploy
6. 烟雾测试（前端登录 / 商品列表 / 加购物车 / Stripe 测试卡下单）
7. 观察 ≥ 7 天
8. **退役**旧 PG 18 容器

**风险点**:

- 如果 bagstore 在生产数据里塞了 PG 18 特有的 binary 列（如 UUID v7 二进制存储）— 不会，prisma schema 已核查过
- INSERT 顺序问题：`--data-only --inserts` 走单条 INSERT，遇 FK 时按 dump 文件中表的物理顺序，可能撞 FK。如果遇到，psql 灌 sql 时用 `SET session_replication_role = replica;` 包一层

**回滚**: bagstore env 改回旧容器，redeploy

---

## 4. 风险与防护清单

| 风险 | 缓解 |
|---|---|
| PR-A 改 datetime default 后时区行为变 | PR-B 验收时关注 inventory_events.imported_at 之类字段；必要时在 Coolify env 设 `TZ=Europe/Athens` |
| ETL 漏迁某张表 | `TABLE_ORDER` 列表对照 alembic 模型穷举；脚本 verify 阶段强校验 row count |
| sequence 未重置导致 ORM 后续 INSERT 撞 PK | `reset_sequences()` 函数已在 ETL 脚本中 |
| 维护窗口超出预期 | scp 470 MB + ETL 15 分钟 + 测试 15 分钟 ≈ 30-45 分钟，给 1 小时 buffer |
| shared-pg17 单点故障 | 这是接受的代价，路径 1 决策的内在 trade-off。配套措施：每天 pg_dumpall + 异地保留 7 天 |
| bagstore PG 18 → 17 数据兼容性 | §2.3 已核查 schema，无 PG 18 专属类型/语法 |
| PostGIS 17 镜像被 label-sync / bagstore 误用扩展 | 数据库级别不启用 postgis extension，CREATE EXTENSION 仅在 athennest db 内执行 |

---

## 5. 备份策略（新 shared-pg17 落地后）

```bash
#!/bin/bash
# /opt/scripts/pg-backup.sh  (cron 每天 03:00)
set -euo pipefail

DATE=$(date +%Y%m%d-%H%M%S)
BACKUP_DIR=/data/backups/pg
mkdir -p $BACKUP_DIR

docker exec shared-pg17 pg_dumpall -U postgres | gzip > $BACKUP_DIR/pg-$DATE.sql.gz

# 保留 14 天
find $BACKUP_DIR -name 'pg-*.sql.gz' -mtime +14 -delete
```

异地备份（待规划）: rclone 推 Backblaze B2 / S3，每日同步。

---

## 6. 时间表（建议）

| 阶段 | 估时 | 触发条件 |
|---|---|---|
| PR-A | 半天 | 立即可开 |
| PR-B | 一天 | PR-A 合并 |
| PR-C 准备 + cutover | 半天 | PR-B 合并 + 维护窗口 |
| PR-C 观察 | 7 天 | cutover 完成 |
| PR-D | 半天（含观察前 1 周） | PR-C 稳定 |
| PR-E | 半天（含观察前 1 周） | PR-D 稳定 |

总计 ≈ 3-4 周（含观察期），实际动手时间约 3 个工作日。

---

## 7. 不在本 plan 范围

- PostGIS 18 出来后的整体升级（届时另开 plan）
- shared-pg17 性能调优（`shared_buffers`, `work_mem`, `effective_cache_size` 等）
- 应用层连接池（pgbouncer / pgcat）— 当前流量级别不需要
- pgvector / 全文搜索等扩展启用 — 按需

---

## 8. 关联 memory / 文档

- `feedback_no_db_merge.md` — DB 迁移不允许 anti-join 合并；本 plan 走整库迁移
- `feedback_db_migration_no_backup.md` — 一般 DB 操作不必先备份，但本次涉及生产数据切换，**例外保留 30 天 SQLite 快照**
- `project_deployment_hetzner.md` — Hetzner + Docker + 内网 only 部署形态保持
- 旧 `docs/thesis/label-sync-refactor-plan.md` Phase 7（"SQLite 不迁 PG"）— 已被本 plan 推翻，目标改为 shared PG

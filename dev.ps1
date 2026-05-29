#!/usr/bin/env pwsh
# 本地开发一键启动：本地 PostgreSQL（Docker）+ 热重载 Flask。
#
#   ./dev.ps1
#
# 起来后改 .py / templates/*.html 存盘即自动重载，不用手动重启 server。
# 数据用本地 PG（端口 5433）；要灌线上真实数据先跑 tools/pull_prod_db.py。
$ErrorActionPreference = 'Stop'

# 1. 起本地 PostgreSQL 17（数据卷 ./.dev/pg-data，已 gitignored）
docker compose -f docker-compose.dev.yml up -d

# 2. 指向本地 PG + 打开热重载
$env:DATABASE_URL = 'postgresql+psycopg://dev:devpass@localhost:5433/label_sync'
$env:LABEL_SYNC_DEBUG = '1'

# 3. 同步 schema（幂等）
python -m alembic upgrade head

# 4. 起 server（debug=True → reloader 监听 .py，Jinja 监听模板）
Write-Host "`n本地开发服务器启动中（热重载已开）… http://127.0.0.1:5000`n" -ForegroundColor Green
python server.py

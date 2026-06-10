#!/usr/bin/env pwsh
# 本地 PG 模式跑测试（对齐生产后端 + pytest-xdist 并行）：
#
#   ./test.ps1                          # 全套
#   ./test.ps1 tests/test_purchase_routes.py   # 指定文件/参数原样透传
#
# 快速 sqlite 模式照旧：pytest tests/（不设 TEST_DATABASE_URL 即可）
# 串行 PG 模式：手动设 $env:TEST_DATABASE_URL 后直接 pytest
# xdist 的 worker 库 label_sync_test_gwN 留在容器里复用，不用清。
$ErrorActionPreference = 'Stop'

# 1. 确保本地 PG 起着（与 dev.ps1 同一容器），等到能接连接为止
docker compose -f docker-compose.dev.yml up -d
$ready = $false
for ($i = 0; $i -lt 30; $i++) {
    docker exec label-sync-dev-pg pg_isready -U dev *> $null
    if ($LASTEXITCODE -eq 0) { $ready = $true; break }
    Start-Sleep -Seconds 1
}
if (-not $ready) { throw '本地 PG（label-sync-dev-pg）未就绪' }

# 2. 测试库与镜像库 label_sync 严格隔离，首次自动创建
$exists = docker exec label-sync-dev-pg psql -U dev -d postgres -Atc "SELECT 1 FROM pg_database WHERE datname='label_sync_test'"
if ($exists -ne '1') {
    docker exec label-sync-dev-pg psql -U dev -d postgres -c 'CREATE DATABASE label_sync_test OWNER dev' | Out-Null
}

# 3. PG 模式 + 并行（worker 独立库由 tests/conftest.py 负责）
$env:TEST_DATABASE_URL = 'postgresql+psycopg://dev:devpass@localhost:5433/label_sync_test'
if ($args.Count -eq 0) { $target = @('tests/') } else { $target = $args }
python -m pytest -n auto @target
exit $LASTEXITCODE

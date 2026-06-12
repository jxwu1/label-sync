# label-sync — ERP 库存标签处理 & 数据分析系统

> 基于 Flask 的内部 ERP 工具，用于条码扫描解析、库存匹配、标签生成、进销存分析、补货决策、考勤管理与月度汇总。部署在 Hetzner VPS，通过 Coolify + Docker 管理，仅公司内网访问。

## 功能模块

| # | 模块 | 说明 | 快捷键 |
|---|------|------|--------|
| 01 | 标签处理 | 上传扫描文件 → 三阶段自动处理 → 下载结果 | ⌘1 |
| 02 | 标签查重 | 检测空白 / 非法前缀 / 重复 / 空库位 / 负库存 | ⌘2 |
| 03 | 采购导入 | 上传供应商 Excel → 解析匹配 → 管理新品条码 | ⌘3 |
| 04 | 考勤台账 | 员工考勤日历视图 + 月度统计 | ⌘4 |
| 05 | 货号历史 | 按条码查完整生命周期：当前状态 / 销售分析 / 采购记录 / 扩展指标 / 补货快照 / 时间线图表 | ⌘5 |
| 06 | 数据质量 | 多库位告警 / 高频翻转监控 | ⌘6 |
| 07 | 数据健康 | 进销存导入 + 产品主数据导入 + 系统健康概览 | ⌘7 |
| 08 | 老外客人 | 外国客户月度应收账款管理 + PDF 导出 | ⌘8 |
| 11 | 补货决策 | 基于销售预测的智能补货建议：紧迫评分 / 供应商概览 / 批量操作 | — |

> 前端独立化试点：新版简报页 `/ui/briefing`（Vue 3，见 frontend/）。

## 技术栈

- **后端**: Python 3.12 + Flask + SQLAlchemy 2.x + Alembic
- **数据库**: PostgreSQL 17 (Coolify shared 容器)
- **数据处理**: pandas + openpyxl + python-calamine + pyarrow
- **预测**: numpy (Naive 三件套 + CrostonSBA, 不引 sklearn)
- **前端**: Alpine.js + Vanilla JS + 原生 CSS (无构建步骤)
- **设计**: Apple Design Language — 三套主题 (apple-dark / apple-light / terminal)
- **部署**: Docker + Coolify + Traefik (HTTPS) + waitress (WSGI)
- **测试**: pytest (850+ cases) + Playwright (e2e 烟雾)

## 快速开始

### 本地开发

```bash
python -m venv .venv
.venv\Scripts\Activate.ps1       # Windows
# source .venv/bin/activate      # Linux/macOS

pip install -r requirements.txt -r requirements-dev.txt
python -m alembic upgrade head
python server.py                 # http://127.0.0.1:5000
```

### 测试

```bash
pytest tests/                    # 单元 + 集成
pytest e2e/                      # Playwright 浏览器烟雾测试 (opt-in)
```

## 部署

Hetzner Cloud VPS，Coolify (PaaS) 管理，Docker 隔离，仅内网访问。

```bash
git push                         # 触发 Coolify 自动 redeploy
```

手动部署:
```bash
docker compose build && docker compose up -d
```

详见 `docs/deploy-plan.md`。

## 目录结构

```
label-sync/
├── app/
│   ├── routes/                  # HTTP 蓝图 (按业务域分)
│   ├── services/                # 业务服务层 (analytics / restock / history ...)
│   ├── importers/               # 进销存导入 (product_master / inventory)
│   ├── utils/                   # 工具 (forecast_data / categorizer / customer_classifier)
│   ├── config.py                # 运行配置
│   └── models.py                # SQLAlchemy ORM 单源
├── phase_scripts/               # 标签处理 3 阶段 (subprocess)
├── scraper/                     # boson ERP 数据抓取 (本地, 不部署)
│   ├── sales_scraper.py         # 销售明细
│   ├── purchase_scraper.py      # 采购明细
│   ├── inventory_scraper.py     # 库存快照
│   ├── product_master_scraper.py # 产品总档
│   ├── refresh_cookie.py        # Playwright 自动登录刷 PHPSESSID
│   ├── run_weekly.ps1           # 周一 14:00 全链路自动 (Task Scheduler)
│   └── register_task.ps1        # 一键注册 Task Scheduler
├── tools/                       # CLI 工具 (wipe / clean / import)
├── etl/                         # Parquet 历史回填 pipeline
├── alembic/versions/            # schema 迁移
├── tests/                       # pytest 单元 + 集成
├── e2e/                         # Playwright 浏览器烟雾
├── templates/ + static/         # 前端 (Alpine.js + CSS tokens)
├── docs/                        # 设计 plan / 部署 plan / 论文稿
├── wsgi.py                      # waitress 生产入口
└── server.py                    # 开发入口
```

## 数据抓取 (scraper/)

从 boson ERP 自动抓取销售 / 采购 / 库存数据，脱敏后上传到服务器。

**全自动流程** (每周一 14:00 Task Scheduler 触发):
1. `refresh_cookie.py` — Playwright headless 登录 boson 拿 PHPSESSID
2. `sales_scraper.py` — 抓最近 7 天销售
3. `purchase_scraper.py` — 抓最近 7 天采购
4. `inventory_scraper.py` — 抓库存快照
5. `product_master_scraper.py` — 每月第一个周一跑产品总档
6. `sanitize.py` — 脱敏
7. 上传 parquet 到服务器

**首次配置**:
```bash
cd scraper
cp .env.example .env             # 填 BOSON_USERNAME / PASSWORD / ADD_CODE / UPLOAD_TOKEN
pip install -r requirements.txt
playwright install chromium
# 管理员 PowerShell 运行 register_task.ps1 注册 Task Scheduler
```

日志在 `scraper/logs/run_weekly_<时间戳>.log`。

## 数据目录 (运行时, gitignored)

Docker 挂载到 `/data`:
- `input/` — 待处理输入文件
- `output/` — 处理结果 (按员工 + 时间戳分目录)
- `archive/` — 已处理原始文件归档 + ETL Parquet 历史归档

## 主题系统

三套主题，通过顶栏按钮切换:
- **Apple Dark** (默认) — 纯黑底 + #007AFF 蓝强调
- **Apple Light** — 纯白底 + 同色系
- **Terminal** — 暗色终端风 + #00ff95 绿 + JetBrains Mono

设计文档: `docs/design-brief.md`

## 关键文档

| 文档 | 说明 |
|------|------|
| `CLAUDE.md` | 开发规范 + 编码约定 |
| `docs/deploy-plan.md` | Hetzner / Coolify 部署 plan |
| `docs/design-brief.md` | Apple Design Language 前端设计文档 |
| `docs/superpowers/plans/2026-05-12-forecast-and-backtest.md` | 预测算法主 plan |
| `scraper/README.md` | 抓取脚本配置与用法 |

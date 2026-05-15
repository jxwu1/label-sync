# label-sync（双端处理）

基于 Flask 的 ERP 库存标签处理系统。用于条码扫描解析、库存匹配、标签生成、考勤报表、月度汇总、进销存导入与数据分析。

当前阶段：生产运行中，通过 Coolify + Docker 部署在 Hetzner 服务器（仅公司内网访问）。

## 技术栈

- Python 3.12 + Flask（Web 框架）
- pandas + openpyxl + python-calamine（Excel/CSV 处理）
- pyarrow（Parquet ETL）
- SQLAlchemy 2.x + Alembic（ORM + 数据库迁移）
- SQLite（WAL 模式，当前数据量足够；Phase 7 后可切 PostgreSQL）
- numpy（预测算法 + 回测，不引 sklearn / statsmodels）
- reportlab（月度报表 PDF）
- waitress（生产 WSGI 服务器，跨平台）
- Alpine.js + Vanilla JS（前端，无构建步骤）
- Docker + docker-compose（容器化）
- Coolify + Traefik（PaaS + 反代 + HTTPS）
- pytest + Playwright（测试，708 单元 + e2e 烟雾）

## 目录结构（当前平铺，Phase 2 重构后改为 `app/` 包结构）

```
label-sync/
├── server.py / wsgi.py             # 入口
├── routes.py + routes_*.py         # HTTP 蓝图（按业务域分）
├── *_service.py                    # 业务服务层
├── *_repository.py                 # 数据访问层
├── models.py                       # SQLAlchemy ORM 单源
├── stockpile_db.py                 # SQLite engine + 主档查询
├── forecast_data.py                # 阶段 1 预测数据底座
├── backtest_service.py             # 阶段 2 回测算法 + 框架
├── categorizer.py                  # 4 类生命周期 + 4 类销售形态分类
├── analytics_service.py            # SKU dashboard 指标
├── etl/                            # Parquet 历史回填 pipeline
├── phase_scripts/                  # 标签处理 3 阶段（subprocess）
├── tools/                          # CLI 工具（wipe / clean / import）
├── alembic/versions/               # schema 迁移
├── tests/                          # 单元 + 集成测试
├── e2e/                            # Playwright 浏览器烟雾测试
├── templates/ + static/            # 前端
├── docs/                           # 设计 plan / 部署 plan / 论文稿
└── 运行时（gitignored）: input/ output/ transfer/ 垃圾桶/ stockpile.db
```

## 核心业务流程

**三阶段标签处理**（phase_scripts/）：
1. 阶段 1：扫描数据解析，检测异常条码长度
2. 阶段 2：扫描结果与 stockpile 文件匹配，识别新品条码
3. 阶段 3：按模板生成导入 CSV，整理输出并归档

**数据预测**（forecast_data + backtest_service）：
1. ETL 清洗 → inventory_events 表
2. SKU 形态分类（retail_dominant / mixed / wholesale_only / dying）
3. 基础需求视图（按 SKU 类型分流过滤大单 + 退货归并）
4. Walk-forward 回测（4 个 baseline：Naive 三件套 + CrostonSBA）
5. 评分（MAPE / MASE / Bias / coverage@p98）

## 编码规范

- Python 标识符统一 `snake_case`，用户可见文案保留中文
- 文件编码统一 UTF-8（CSV 读取优先 UTF-8，失败回退 GBK）
- 新增接口：先决定蓝图，放对应 `routes_<域>.py`（Phase 2 后改 `app/routes/<域>.py`）
- 新增业务逻辑：放对应 `*_service.py`（Phase 2 后改 `app/services/*.py`）
- 共享状态放 `state.py`，跨模块结构放 `schemas.py`
- 文件系统访问收敛到 `*_repository.py`
- 数据库 schema 单源：`models.py`，新增字段走 `alembic revision --autogenerate`

## 测试

```bash
pytest tests/        # 单元 + 集成，708 个 case
pytest e2e/          # Playwright 浏览器烟雾测试（opt-in）
```

## 本地开发

```bash
python -m venv .venv
.venv\Scripts\Activate.ps1   # Windows
# 或 source .venv/bin/activate  # Linux/macOS
pip install -r requirements.txt -r requirements-dev.txt
python -m alembic upgrade head
python server.py             # 浏览器开 http://127.0.0.1:5000
```

## 部署

服务器: Hetzner Cloud Linux VPS，Coolify (PaaS) 管理。

```bash
git push                     # 触发 Coolify 自动 redeploy
# 或手动:
docker compose build
docker compose up -d
```

## 数据目录

运行时数据挂载到 `/data`（Docker volume）：

- `stockpile.db` — 主数据库（SQLite WAL）
- `input/` — 待处理输入文件
- `output/` — 处理结果（按员工+时间戳分目录）
- `transfer/` — 双端互传
- `垃圾桶/` — 已处理原始文件归档（Phase 3 重命名为 `archive/`）
- `attendance/` — 考勤 JSON（Phase 1.6 后迁入 DB）
- `monthly_summary/` — 月度汇总 JSON
- `archive/` — Parquet 历史归档

## 关键文档

- `README.md` — 用户使用说明（中文）
- `docs/dev-setup.md` — 开发环境
- `docs/deploy-plan.md` — Hetzner / Coolify 部署 plan
- `docs/superpowers/plans/2026-05-12-forecast-and-backtest.md` — 预测算法主 plan
- `docs/thesis/参考论文.md` — 毕业论文参考稿（双人 joint paper）
- `docs/thesis/项目说明.md` — 给同学的分工说明
- `docs/thesis/迭代路线图.md` — 半年路线图
- `docs/thesis/label-sync-refactor-plan.md` — 7 Phase 重构 plan

---

<!-- gitnexus:start -->
# GitNexus — Code Intelligence

This project is indexed by GitNexus as **label-sync** (5751 symbols, 13765 relationships, 300 execution flows). Use the GitNexus MCP tools to understand code, assess impact, and navigate safely.

> If any GitNexus tool warns the index is stale, run `npx gitnexus analyze` in terminal first.

## Always Do

- **MUST run impact analysis before editing any symbol.** Before modifying a function, class, or method, run `gitnexus_impact({target: "symbolName", direction: "upstream"})` and report the blast radius (direct callers, affected processes, risk level) to the user.
- **MUST run `gitnexus_detect_changes()` before committing** to verify your changes only affect expected symbols and execution flows.
- **MUST warn the user** if impact analysis returns HIGH or CRITICAL risk before proceeding with edits.
- When exploring unfamiliar code, use `gitnexus_query({query: "concept"})` to find execution flows instead of grepping. It returns process-grouped results ranked by relevance.
- When you need full context on a specific symbol — callers, callees, which execution flows it participates in — use `gitnexus_context({name: "symbolName"})`.

## Never Do

- NEVER edit a function, class, or method without first running `gitnexus_impact` on it.
- NEVER ignore HIGH or CRITICAL risk warnings from impact analysis.
- NEVER rename symbols with find-and-replace — use `gitnexus_rename` which understands the call graph.
- NEVER commit changes without running `gitnexus_detect_changes()` to check affected scope.

## Resources

| Resource | Use for |
|----------|---------|
| `gitnexus://repo/label-sync/context` | Codebase overview, check index freshness |
| `gitnexus://repo/label-sync/clusters` | All functional areas |
| `gitnexus://repo/label-sync/processes` | All execution flows |
| `gitnexus://repo/label-sync/process/{name}` | Step-by-step execution trace |

## CLI

| Task | Read this skill file |
|------|---------------------|
| Understand architecture / "How does X work?" | `.claude/skills/gitnexus/gitnexus-exploring/SKILL.md` |
| Blast radius / "What breaks if I change X?" | `.claude/skills/gitnexus/gitnexus-impact-analysis/SKILL.md` |
| Trace bugs / "Why is X failing?" | `.claude/skills/gitnexus/gitnexus-debugging/SKILL.md` |
| Rename / extract / split / refactor | `.claude/skills/gitnexus/gitnexus-refactoring/SKILL.md` |
| Tools, resources, schema reference | `.claude/skills/gitnexus/gitnexus-guide/SKILL.md` |
| Index, status, clean, wiki CLI commands | `.claude/skills/gitnexus/gitnexus-cli/SKILL.md` |

<!-- gitnexus:end -->

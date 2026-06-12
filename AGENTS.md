# label-sync（双端处理）

基于 Flask 的 ERP 库存标签处理系统。用于条码扫描解析、库存匹配、标签生成、考勤报表、月度汇总、进销存导入与数据分析。

当前阶段：生产运行中，通过 Coolify + Docker 部署在 Hetzner 服务器（仅公司内网访问）。

## 技术栈

- Python 3.12 + Flask（Web 框架）
- pandas + openpyxl + python-calamine（Excel/CSV 处理）
- pyarrow（Parquet ETL）
- SQLAlchemy 2.x + Alembic（ORM + 数据库迁移）
- PostgreSQL 17（生产 + 本地主库，Coolify shared 容器）；engine/session 单一真源 `app/db.py`，SQLite 仅作 `DATABASE_URL` 未设时的本地回退 + 测试隔离
- numpy（预测算法 + 回测，不引 sklearn / statsmodels）
- reportlab（月度报表 PDF）
- waitress（生产 WSGI 服务器，跨平台）
- Alpine.js + Vanilla JS + Tailwind CSS v4（前端，Tailwind standalone CLI 构建）
- Docker + docker-compose（容器化）
- Coolify + Traefik（PaaS + 反代 + HTTPS）
- pytest + Playwright（测试，1018 单元 + e2e 烟雾）

## 目录结构（当前平铺，Phase 2 重构后改为 `app/` 包结构）

```
label-sync/
├── server.py / wsgi.py             # 入口
├── routes.py + routes_*.py         # HTTP 蓝图（按业务域分）
├── *_service.py                    # 业务服务层
├── *_repository.py                 # 数据访问层
├── models.py                       # SQLAlchemy ORM 单源
├── stockpile_db.py                 # 主档查询（engine/session 委托 app/db.py 单源）
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
└── 运行时（gitignored）: input/ output/ transfer/ archive/（DB 走 PostgreSQL，不在仓库目录）
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

## 前端独立化（阶段 0+1 试点期）

- 新 API 端点：响应模型声明在 `app/schemas_api.py`（pydantic），改后跑
  `python tools/gen_ts_types.py` 同步 TS 类型（CI --check 守护漂移）
- `/api/*` 未登录返回 JSON 401（auth.py `_require_login` 分流）；
  X-Upload-Token cron 分支语义不可动
- frontend/ 是独立 Vite 工程（Node 严格圈在该目录，仓库根禁 package.json）；
  本地 `./dev.ps1 -Frontend` 或 `cd frontend && npm run dev`
- tokens 单源 = `static/css/tokens.css`（纯 CSS 变量），新栈经
  frontend/src/styles/main.css 的 @theme 映射消费——绝不复制该文件
- 设计 spec：docs/superpowers/specs/2026-06-12-frontend-decoupling-design.md

## 测试

```bash
pytest tests/        # 单元 + 集成，1018 个 case
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

- 主数据库 — PostgreSQL 17（Coolify shared 容器，凭据走部署环境注入）；`stockpile.db`（SQLite）仅 `DATABASE_URL` 未设时的本地回退
- `input/` — 待处理输入文件
- `output/` — 处理结果（按员工+时间戳分目录）
- `transfer/` — 双端互传
- `archive/` — 已处理原始文件归档 + ETL Parquet 历史归档
- `attendance/` — 考勤 JSON（Phase 1.6 后迁入 DB）
- `monthly_summary/` — 月度汇总 JSON

## 关键文档

- `README.md` — 用户使用说明（中文）
- `docs/dev-setup.md` — 开发环境
- `docs/deploy-plan.md` — Hetzner / Coolify 部署 plan
- `docs/superpowers/plans/2026-05-12-forecast-and-backtest.md` — 预测算法主 plan
- `docs/system-mental-model.md` — 系统心智模型（数据流/模块假设/耦合点/改动波及表，改链路前先查）
- `docs/plan-templates.md` — Plan 模板（新模型/补货策略/分类调整）+ 反例库 E1-E12
- `docs/thesis/参考论文.md` — 毕业论文参考稿（双人 joint paper）
- `docs/thesis/项目说明.md` — 给同学的分工说明
- `docs/thesis/迭代路线图.md` — 半年路线图
- `docs/thesis/label-sync-refactor-plan.md` — 7 Phase 重构 plan

## Review 红线（审查检查清单）

> 来源：`docs/adr/0001-replenishment-policy.md`、`docs/adr/0002-model-selection.md`、
> `docs/adr/replenishment-redlines.md`（RL 编号对应该清单）。
> 用法：PR 触碰对应文件时逐项核对，违反任何一条 → reject 并引用条目编号。
> 每条都是可机械执行的检查，不需要重新推导背后的统计学。

### A. 补货 / 预测数值断言（触碰 `restock_calc.py` / `forecast.py` / `backtest.py` 时）

- **A1 非负**：`restock_qty_*`、`mu/sigma/p50/p98` 及一切对外数值必须 ≥ 0（None=无数据 允许）。任何去掉 `max(0, ...)` clamp 的 diff → reject。
- **A2 分位单调**：`p50 ≤ p98`、`restock_qty_p50 ≤ restock_qty_p98`，凑整和闸后仍须成立。
- **A3 凑整只向上**：`0 ≤ rounded − raw < 中包`；`middle_qty ∈ {None, 0, 1}` 时恒等。
- **A4 周分位 × 系数 = 默认 reject（RL-1）**：任何新增"周分位数 × 周数"形态的代码（`p98 * 8`、`* 13` 等）都是已修复 bug 的复发。跨期聚合必须走 `horizon_quantile`（bootstrap 和分位数，固定 seed）。均值 `mu × N` 可以线性相加，分位数不可以。
- **A5 IP 必含在途（RL-2）**：库存位置 = `max(0, qty_total) + on_order`，`on_order = Σ(qty_ordered − qty_arrived)` 仅含非 cancelled/void 单，超收行按 0 计。只用现库存算缺口的 diff → reject。
- **A6 只标记不截断（RL-6）**：合理性闸（`sanity_flag`）只允许标记异常推荐量，任何对推荐值的静默截断/封顶 → reject（截断掩盖上游 bug）。
- **A7 负库存口径一致（RL-7）**：`qty_total < 0` 一律按 0 计；`restock_calc` 与 `stockout.py` 的判定口径必须保持一致，只改一处 → reject。
- **A8 断货 override 不可移除（RL-8）**：反震荡闸必须保留"现库存 ≤ 0 且 S > 0 时必触发"分支，否则死亡螺旋保护失效。
- **A9 随机性必须可复现**：bootstrap / 任何抽样代码必须固定 seed；不带 seed 的 `default_rng()` → reject。
- **A10 缺货周剔除不许填值（RL-3 / ADR-0001 D7）**：缺货周从训练序列**剔除**（当缺失），填 0 或插值 → reject；剔除数必须记入 `stockout_weeks_excluded`。
- **A11 输入清洗在上游**：模型层（`EmpiricalQuantileModel` 等）按约定接收非负序列、不裁剪负值；给模型加负值兜底 = 掩盖上游 `base_demand_view` 清洗失职 → 在上游修。

### B. forecasting 输出与路由（触碰 `forecast_output` 写入/消费、`ROUTING`、`categorizer` 时）

- **B1 新消费端两件套**：任何新读 `forecast_output` 的代码必须处理 ① `computed_at` 过期（>14 天，RL-9）② `stockout_weeks_excluded`（置信分层消费）。缺一 → 要求补。
- **B2 改路由先标定（ADR-0002 D6）**：改 `ROUTING` 表 / 新增 SKU 类别 / 换主力模型的 PR，必须附 `tools/calibrate_model_routing.py` 输出。无标定输出 → reject。
- **B3 改分类阈值 = 回测失效**：`categorizer` 阈值改动会静默改变所有下游预测输入（base_demand 分流），PR 必须声明回测结果失效并重跑（ADR-0001 附录耦合 3）。
- **B4 dying / unclassified 不预测**：给这两类强行出预测 → reject（回测证明 dying 强预测 bias +0.89；冷启动是独立路线图项）。
- **B5 wholesale 准入闸**：CrostonSBA 路由必须保留"≥13 周 且 非零周 ≥5"准入；放宽即引入 interval 噪声估计。

### C. SQLAlchemy / 数据层模式

- **C1 engine 单源**：engine/session 只能来自 `app/db.py`（`get_engine()` / `get_session()`）。任何模块自建 `create_engine` / `sessionmaker` → reject。
- **C2 会话边界**：session 必须走 `with db.get_session()`（或 `stockpile_db._session()`）上下文管理器；把 ORM 实例带出 session 作用域后再访问 lazy 属性 → DetachedInstanceError 隐患，跨边界传 dict。
- **C3 N+1**：循环体内逐个 `session.execute(select(...))` 按单 barcode 查 → reject，改 `in_()` 批查或 join 后字典分发（参考 `_snapshot_qty_lookup` 模式）。
- **C4 事务边界**：读-改-写必须在同一 session/事务内完成；跨两个 session 先读后写 = lost update 隐患。
- **C5 测试 seed 禁裸 sqlite3**：测试数据必须走 SQLAlchemy 写入（CI PG 腿会挂）；确需测 raw sqlite 行为的文件标 `pytestmark = pytest.mark.sqlite_only`。
- **C6 schema 单源**：改表结构必须 `models.py` + `alembic revision --autogenerate` 成对出现，手写 DDL 或只改一边 → reject。

### D. 流程红线（数值改动 PR 的硬门槛）

- **D1 三件套同步**：改补货公式/分位数计算的 PR 必须同步更新 `docs/adr/replenishment-redlines.md` + 对应测试，缺一 → reject。
- **D2 数值测试全绿**：`tests/test_replenishment_redlines.py`、`tests/test_replenishment_properties.py`、`tests/test_forecast_golden.py` 必须全过。golden 基线变更必须在 PR 描述里解释"数值为什么应该变"，无解释的基线更新 → reject（那是在让测试迁就 bug）。

---

# CodeGraph — Code Intelligence

本项目用 [CodeGraph](https://github.com/colbymchenry/codegraph) (SQLite + tree-sitter) 做代码索引，替代 GitNexus。

```bash
npx @colbymchenry/codegraph status          # 查看索引状态
npx @colbymchenry/codegraph sync            # 增量同步
npx @colbymchenry/codegraph impact <symbol> # 影响分析
npx @colbymchenry/codegraph callers <symbol> # 调用方
```

MCP 工具通过 `codegraph serve` 暴露，支持 `codegraph_search` / `codegraph_context` / `codegraph_impact` / `codegraph_callers` / `codegraph_callees`。

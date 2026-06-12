# label-sync 重构计划

> 本文档供 Claude Code 执行。每个 Phase 独立成一个 branch，完成后 merge 到 main。
> 重构原则：**不改变任何现有功能和业务逻辑**，只做结构整理和工程规范对齐。

---

## ✅ 状态对账（2026-06-12，Fable 复核仓库现状）

**本 plan 已基本执行完毕**，以下为逐 Phase 对账。后续读者：本文档价值已转为
历史记录 + plan 写作范本（批次 commit / 复审补丁模式被 `docs/plan-templates.md`
收编），不要再按"待执行"理解。

| Phase | 状态 | 证据 |
|---|---|---|
| 0 安全审查 | 🟡 大体完成，残余在册 | secret env / cron 鉴权等残余项已并入 Codex review backlog（`docs/engineering-backlog.md`），不在本 plan 追踪 |
| 1 CLAUDE.md 重写 | ✅ | 当前 CLAUDE.md 即项目上下文 + CodeGraph（GitNexus 已于 2026-05-29 移除，"保留 GitNexus"的指示已被现实取代） |
| 2 目录结构 app/ 包 | ✅ | `ad908ea Merge Phase 2: app/ package refactor`（8 批次执行，import-audit before/after 在 docs/refactor/） |
| 3 中文目录名清理 | ✅ | 仓库无 `垃圾桶` 引用，运行时目录 = archive/ |
| 4 Node 配置清理 | ✅ | package.json / eslint.config.js 已不在仓库（注意：Tailwind v4 用 standalone CLI，无 Node 依赖） |
| 5 CI/CD | ✅ 且超额 | `.github/workflows/ci.yml`：pytest sqlite+postgres 双矩阵 + ruff + docker（#37），超出原 plan 的单腿设计 |
| 6 README/元信息 | ✅ | README 重写 + GitHub description/topics 已设置 |
| 7 PostgreSQL 迁移 | ✅ 且超额 | 已切 Coolify shared-pg17 为主库（原 plan 仅"可选支持"），engine 单源 `app/db.py` |

**风险分级结论（原"第 8 项"问题的答案）**：plan 已执行完，分级问题消解。
留给未来同类重构的经验已蒸馏进 `docs/plan-templates.md` 反例库
（E11 飞行任务冲突、E12 工具链漂移、工时 ×3 规则、批次独立 commit）。

---

## ⚠️ 执行前置条件（2026-05-15 复审补充）

**开干 Phase 0 之前必须满足**:

1. ✅ **v2 backtest 跑完**（task `boli3ovn7`，4 个 baseline 全部 DONE）
2. ✅ **更新 backtest CSV**（重跑 `_scratch/export_backtest_comparison.py` 拿到 v1+v2 完整数据）
3. ✅ **scp 新 DB 到 Hetzner**（按 `docs/deploy-plan.md` 步骤替换线上 SQLite）
4. ✅ **论文 §5.4.4 / §6.5.4 补 v2 实测数据**
5. ✅ **matplotlib 画完 4 张论文图**（图 5-1 / 6-1 / 6-2 / 系统架构）

**为什么必须先做**:

- Phase 2 移动 40+ 文件会让飞行中的 backtest 进程的 import 失效（虽然已 import 的不受影响，但中途若崩溃重启会找不到模块）
- 论文里的代码路径引用（`forecast_data.py::weekly_demand_series` 等）一旦 Phase 2 移完都失效，要在重构前用完
- `_scratch/` 里的 spike 脚本用 `sys.path.insert` 加根目录，Phase 2 后会断（属于次要问题，但提前知道）

---

## 现状概述

label-sync 是一个基于 Flask 的 ERP 库存标签处理系统（"双端处理"），功能包括：条码扫描解析、库存匹配、标签生成、考勤报表、月度汇总、进销存导入、数据分析等。

当前问题：
- 仓库名 `label-sync` 与实际功能不符
- 40+ 个 .py 文件全部平铺在根目录，无包结构
- CLAUDE.md 是 GitNexus 模板，无项目实际内容
- 存在中文目录名 `垃圾桶/` 已被 commit
- Node.js 配置（package.json、eslint）和 Python 混在一起
- 缺少 CI/CD workflow
- 需要和其他项目（AthenNest / OliveBoard / BagStore）的工程规范对齐

---

## Phase 0 — 安全审查（最高优先级）

**分支名**: `fix/security-audit`

### 任务清单

1. **扫描 Git 历史中的敏感信息**
   ```bash
   # 检查是否有密码、密钥、IP 等敏感信息
   git log --all -p | grep -iE "(password|secret|api_key|token|178\.104)" | head -50
   # 检查 .env 文件是否被 commit 过
   git log --all --diff-filter=A -- "*.env" ".env*"
   ```

2. **确认 .gitignore 覆盖以下内容**（如果缺失则补上）
   ```
   .env
   .env.*
   *.db
   _scratch/
   input/
   output/
   transfer/
   垃圾桶/
   data/
   *.pyc
   __pycache__/
   .venv/
   node_modules/
   ```

3. **如果发现敏感信息已被 commit**：用 `git filter-repo` 清理历史，或通知用户手动处理（因为这会改写 commit 历史）。

4. **确认 config.py 中没有硬编码的密码或密钥**：所有配置项应从环境变量读取。

### 验收标准
- `git log --all -p | grep -iE "password|secret|api_key"` 无结果（或仅有变量名引用，无实际值）
- .gitignore 完整覆盖上述列表

---

## Phase 1 — CLAUDE.md 重写

**分支名**: `docs/rewrite-claude-md`

### 任务

> ⚠️ GitNexus 正在使用中，**不要删除**现有的 GitNexus 部分。采用"前插"策略：在 GitNexus 内容前面加上项目上下文。

最终 CLAUDE.md 结构为两大部分：

```
┌─────────────────────────────────┐
│  Part 1: 项目上下文（新增）      │  ← Claude Code 了解项目用
│  - 技术栈、目录结构、编码规范    │
│  - 业务流程、部署方式            │
├─────────────────────────────────┤
│  Part 2: GitNexus（完整保留）    │  ← Claude Code 改代码时用
│  - Always Do / Never Do          │
│  - Resources / CLI               │
└─────────────────────────────────┘
```

在现有 `# GitNexus — Code Intelligence` 标题**前面**插入以下内容：

```markdown
# label-sync（双端处理）

基于 Flask 的 ERP 库存标签处理系统。用于条码扫描解析、库存匹配、标签生成、
考勤报表、月度汇总、进销存导入与数据分析。

当前阶段：生产运行中，通过 Coolify + Docker 部署在 Hetzner 服务器。

## 技术栈

- Python 3.12 + Flask（Web 框架）
- pandas + openpyxl（Excel/CSV 处理）
- SQLAlchemy + Alembic（ORM + 数据库迁移）
- SQLite（当前，数据量小够用；将来可迁移 PostgreSQL）
- waitress（生产 WSGI 服务器）
- Alpine.js + Vanilla JS（前端）
- Docker + docker-compose（容器化）
- pytest + Playwright（测试）

## 目录结构

（Phase 2 完成后更新为新结构，初始版本先写当前平铺结构）

## 核心业务流程

三阶段标签处理：
1. 阶段 1：读取扫描文件，识别条码与库位，检测异常条码长度
2. 阶段 2：扫描结果与 stockpile 文件匹配，识别新品条码
3. 阶段 3：按模板生成导入 CSV，整理输出并归档

## 编码规范

- Python 标识符统一 snake_case，用户可见文案保留中文
- 文件编码统一 UTF-8
- CSV 读取优先 UTF-8，失败回退 GBK
- 新增接口：先决定蓝图，放到对应 routes_*.py
- 新增业务逻辑：放到对应 *_service.py
- 共享状态放 state.py，跨模块结构放 schemas.py
- 文件系统访问收敛到 *_repository.py

## 测试

- 单元/集成测试：`pytest tests/`
- E2E 烟雾测试：`pytest e2e/`（需 Playwright）

## 本地开发

python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
python server.py

## 部署

docker compose build
docker compose up -d
# Coolify 会自动反代 5000 端口 + SSL

## 数据目录

运行时数据挂载到 /data（Docker volume）：
- stockpile.db — 主数据库
- input/ — 待处理文件
- output/ — 处理结果
- archive/ — 已处理文件归档（原"垃圾桶"）
- attendance/ — 考勤 JSON
- monthly_summary/ — 月度汇总 JSON

---
（以下是 GitNexus 部分，完整保留不动）
```

### 同步更新 AGENTS.md

AGENTS.md 采用同样的"前插"策略：项目上下文放前面，如果有 GitNexus 内容也保留。

### 验收标准
- CLAUDE.md 前半段包含项目上下文（技术栈、目录结构、编码规范、部署方式）
- CLAUDE.md 后半段 GitNexus 内容完整保留，一字不改
- AGENTS.md 同步更新

---

## Phase 2 — 目录结构整理

**分支名**: `refactor/directory-structure`

> ⚠️ 这是最大的改动。每一步都要跑 `pytest tests/` 确认不破坏功能。
>
> **工时修正（2026-05-15 复审）**: 原 plan 估「1-2 小时」**严重低估**。
> 40+ 文件 × 30+ 测试文件需要更新 import × 8 批 × alembic / phase_scripts / _scratch
> 多个潜在雷区 → **真实估计 1-2 天，留 buffer 3 天**。

### 前置步骤：Import Audit（推荐 30 分钟）

开始动手前先把现有 import 关系画清楚：

```bash
# 法 A: 简单 grep
grep -rEhn "^(from|import) (\w+)" --include="*.py" \
  | grep -v "^.venv\|^_scratch" \
  | sort -u > /tmp/import_map.txt

# 法 B (推荐): 直接用 GitNexus
# gitnexus_query({query: "module dependencies"}) 或
# gitnexus_tool_map / gitnexus_route_map 直接出图
```

输出物：`docs/refactor/import-audit-before.md`，列出每个根目录模块的入向 + 出向依赖。Phase 2 完成后再生成一份 `import-audit-after.md`，对比验证无新增循环依赖。

### 目标结构

```
label-sync/
├── app/                          # Python 应用包
│   ├── __init__.py               # Flask app factory
│   ├── config.py                 # ← 从根目录移入
│   ├── state.py                  # ← 从根目录移入
│   ├── schemas.py                # ← 从根目录移入
│   ├── models.py                 # ← 从根目录移入
│   ├── routes/                   # 路由蓝图包
│   │   ├── __init__.py           # 蓝图注册（原 routes.py）
│   │   ├── pages_tasks.py        # ← routes_pages_tasks.py
│   │   ├── query.py              # ← routes_query.py
│   │   ├── transfer.py           # ← routes_transfer.py
│   │   ├── collab.py             # ← routes_collab.py
│   │   ├── analytics.py          # ← routes_analytics.py
│   │   ├── attendance.py         # ← routes_attendance.py
│   │   ├── data_quality.py       # ← routes_data_quality.py
│   │   ├── foreign_customers.py  # ← routes_foreign_customers.py
│   │   ├── history.py            # ← routes_history.py
│   │   ├── inventory.py          # ← routes_inventory.py
│   │   ├── monthly_summary.py    # ← routes_monthly_summary.py
│   │   ├── purchase.py           # ← routes_purchase.py
│   │   ├── recent_changes.py     # ← routes_recent_changes.py
│   │   ├── scan_history.py       # ← routes_scan_history.py
│   │   └── stockpile.py          # ← routes_stockpile.py
│   ├── services/                 # 业务逻辑包
│   │   ├── __init__.py
│   │   ├── task.py               # ← task_service.py
│   │   ├── barcode.py            # ← barcode_service.py
│   │   ├── query.py              # ← query_service.py
│   │   ├── storage.py            # ← storage_service.py
│   │   ├── message.py            # ← message_service.py
│   │   ├── analytics.py          # ← analytics_service.py
│   │   ├── attendance.py         # ← attendance_service.py
│   │   ├── attendance_report.py  # ← attendance_report_service.py
│   │   ├── backtest.py           # ← backtest_service.py
│   │   ├── data_quality.py       # ← data_quality_service.py
│   │   ├── foreign_customer.py   # ← foreign_customer_service.py
│   │   ├── foreign_customer_report.py  # ← foreign_customer_report_service.py
│   │   ├── history.py            # ← history_service.py
│   │   ├── monthly_summary.py    # ← monthly_summary_service.py
│   │   ├── purchase.py           # ← purchase_service.py
│   │   ├── recent_changes.py     # ← recent_changes_service.py
│   │   └── scan_history.py       # ← scan_history_service.py
│   ├── repositories/             # 数据访问层
│   │   ├── __init__.py
│   │   ├── input.py              # ← input_repository.py
│   │   ├── output.py             # ← output_repository.py
│   │   ├── transfer.py           # ← transfer_repository.py
│   │   └── stockpile_db.py       # ← stockpile_db.py
│   ├── importers/                # 数据导入
│   │   ├── __init__.py
│   │   ├── inventory.py          # ← inventory_importer.py
│   │   └── product_master.py     # ← product_master_importer.py
│   ├── parsers/                  # 解析器
│   │   ├── __init__.py
│   │   ├── xls_html.py           # ← xls_html_parser.py
│   │   ├── erp_category.py       # ← erp_category_parser.py
│   │   └── location.py           # ← location_parser.py
│   └── utils/                    # 通用工具
│       ├── __init__.py
│       ├── file_io.py            # ← file_io.py
│       ├── path_safety.py        # ← path_safety.py
│       ├── response_builder.py   # ← response_builder.py
│       ├── route_helpers.py      # ← route_helpers.py
│       ├── categorizer.py        # ← categorizer.py
│       ├── customer_classifier.py# ← customer_classifier.py
│       └── forecast_data.py      # ← forecast_data.py
├── phase_scripts/                # 保持不动（subprocess 调用）
├── alembic/                      # 保持不动
├── static/                       # 保持不动
├── templates/                    # 保持不动
├── tests/                        # 保持不动（但更新 import 路径）
├── e2e/                          # 保持不动
├── etl/                          # 保持不动
├── tools/                        # 保持不动
├── docs/                         # 保持不动
├── server.py                     # 入口，改为 from app import create_app
├── wsgi.py                       # 入口，改为 from app import create_app
├── Dockerfile                    # 保持不动
├── docker-compose.yml            # 保持不动
├── alembic.ini                   # 保持不动
├── requirements.txt              # 保持不动
├── requirements-dev.txt          # 保持不动
├── pyproject.toml                # 保持不动
├── CLAUDE.md                     # Phase 1 已更新
├── AGENTS.md
├── CHANGELOG.md
└── README.md                     # Phase 4 更新
```

### 执行步骤

1. **创建 `app/` 包和子包**：先创建所有 `__init__.py`
2. **逐批移动文件**（每批一个独立 commit，失败可单批 revert）：
   - 第 1 批：utils（file_io, path_safety, response_builder, route_helpers, categorizer, customer_classifier, forecast_data）
   - 第 2 批：parsers（xls_html_parser, erp_category_parser, location_parser）
   - 第 3 批：repositories（input_repository, output_repository, transfer_repository, stockpile_db）
   - 第 4 批：importers（inventory_importer, product_master_importer）
   - 第 5 批：schemas, models, config, state → app/
   - 第 6 批：services（所有 *_service.py）
   - 第 7 批：routes（所有 routes_*.py + routes.py）
   - 第 8 批：更新 server.py 和 wsgi.py 的 import
3. **每批移动后**：
   - 更新所有内部 import 语句
   - 运行 `pytest tests/` 确认通过
   - 如果 phase_scripts 中有 import 根目录模块的，需要同步改
   - **commit 模板**（关键: 每批独立 commit, 失败时单批 revert）:
     ```
     refactor(p2-batch1): move utils/ to app/utils/

     - file_io.py → app/utils/file_io.py
     - path_safety.py → app/utils/path_safety.py
     - ...
     - update imports in tests/
     - pytest: 708 passed ✓
     ```
   - **回退命令**: `git reset --hard HEAD~1` （仅当 commit 还没 push）
4. **更新 alembic 配置**：`alembic/env.py` 中的 model import 路径
5. **更新 Dockerfile**：如果 COPY 路径有变化
6. **更新 `_scratch/*.py` spike 脚本**：用 `sys.path.insert(0, Path(__file__).parent.parent)` 的需要确认是否还能找到 `app/` 模块；推荐改为 `sys.path.insert(0, str(Path(__file__).resolve().parent.parent))` 即可（根目录加 sys.path 后 `from app.forecast_data import ...` 仍能 work）

### 验收标准
- 根目录不再有 `*_service.py` 和 `routes_*.py` 文件
- `pytest tests/` 全部通过
- `docker compose build` 成功
- `python server.py` 能正常启动

---

## Phase 3 — 中文目录名 + 运行时目录清理

**分支名**: `refactor/rename-directories`

### 任务

1. **`垃圾桶/` → `archive/`**
   - 全局搜索所有引用 `垃圾桶` 的代码，替换为 `archive`
   - 涉及文件：config.py、storage_service.py、phase_scripts/ 中的脚本、README.md
   - docker-compose.yml 注释中提到的 `垃圾桶` 也改掉

2. **确认所有运行时目录在 .gitignore 中**
   ```
   archive/
   input/
   output/
   transfer/
   data/
   ```

3. **从 Git 历史中移除已 commit 的 `垃圾桶/` 目录**
   ```bash
   git rm -r --cached 垃圾桶/
   ```

4. **更新 docker-compose.yml 注释**：
   `垃圾桶` → `archive`

### 验收标准
- 代码中无中文目录名引用
- `git status` 中 `垃圾桶/` 不再被跟踪
- 功能不受影响（文件归档正常工作）

---

## Phase 4 — Node.js 配置清理

**分支名**: `chore/cleanup-node-config`

> ⚠️ **修正（2026-05-15 复审）**: 原 plan 说「Biome 不需要 Node」**事实错误**。
> Biome 虽然用 Rust 写但通过 npm 分发，**仍需要 Node 环境**。
> 真要去 Node 化只有两条正路:
> A. 删 `eslint.config.js`，前端 JS lint 靠 IDE 自带（推荐，前端代码量小）
> B. 用 ruff format（Phase 5 引入）覆盖 Python，前端 JS 不 lint

### 任务

1. **评估 package.json 的实际用途**：
   - 查看 `package.json` 内容，确认是否只用于 eslint
   - 如果是：**直接删除**（不要换 Biome — 它也需要 Node）
   - 如果前端 JS 确实需要 npm 依赖：保留但整理

2. **如果决定移除 Node 依赖**：
   ```bash
   rm package.json package-lock.json eslint.config.js
   # .gitignore 中的 node_modules/ 可以保留以防万一
   ```

3. **如果决定保留**：
   - 将 `eslint.config.js` 移到 `.config/` 目录
   - 在 README 中说明这是前端 JS 的 lint 配置

### 验收标准
- 根目录不会让人误以为这是 Node.js 项目
- 如果保留 eslint，有文档说明用途

---

## Phase 5 — CI/CD 基础 Workflow

**分支名**: `ci/github-actions`

> ⚠️ **复审补充（2026-05-15）**: 现有代码没用 ruff，**直接加 `ruff check` 到 CI 会一开就红一片**。
> 必须在加 CI workflow 之前先做 ruff baseline:

### 前置：ruff baseline（30 分钟）

```bash
# 1. 装 ruff
pip install ruff

# 2. 自动 fix 能修的
ruff check . --fix

# 3. format 一遍
ruff format .

# 4. 看剩多少 warning, 评估是否要在 pyproject.toml 放宽规则
ruff check .
# 如果还有几十条无法自动 fix 的, 加 [tool.ruff.lint] ignore = [...] 让 baseline 干净

# 5. commit baseline
git add . && git commit -m "chore: ruff baseline (auto-fix + format)"
```

### 任务

创建 `.github/workflows/ci.yml`：

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python 3.12
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install dependencies
        run: |
          pip install -r requirements.txt -r requirements-dev.txt

      - name: Run tests
        run: pytest tests/ -v

      - name: Check formatting (ruff)
        run: |
          pip install ruff
          ruff check .
          ruff format --check .

  docker:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Build Docker image
        run: docker build -t label-sync:ci .
```

### 验收标准
- push 到 main 时自动跑 pytest + ruff + docker build
- badge 状态绿色

---

## Phase 6 — README 和仓库元信息更新

**分支名**: `docs/update-readme`

### 任务

1. **在 GitHub 仓库设置中补充**：
   - Description: `ERP 库存标签处理系统 — 条码扫描、库存匹配、标签生成、考勤报表`
   - Topics: `flask`, `erp`, `inventory`, `barcode`, `python`
   - **仓库改名说明（2026-05-15 复审修正）**: 原 plan 说「改名会影响 Coolify 部署」**不准确** —— GitHub 改名后旧 URL 会自动 redirect，Coolify 走 git URL 不受影响。但**仍建议不改名**：论文 / GitNexus 索引 / 部署 plan 都已引用 `https://github.com/jxwu1/label-sync`，改名后这些文档需要全量更新引用，工作量不值得。

2. **更新 README.md**：
   - 保留当前使用说明的全部内容（写得很好）
   - 在顶部加一段英文简介（方便 GitHub 索引）：
     ```
     > Internal ERP tool for barcode label processing, inventory matching, and report generation. Built with Flask + pandas.
     ```
   - 更新"目录说明"为 Phase 2 之后的新结构
   - 把 `垃圾桶` 的引用改为 `archive`

3. **更新 CLAUDE.md 中的目录结构**（Phase 2 完成后的新结构）

### 验收标准
- README 反映最新目录结构
- GitHub 仓库有 description 和 topics

---

## Phase 7 — 部署对齐（可选，低优先级）

**分支名**: `feat/postgres-migration`

> 这个 Phase 是可选的，只在你决定把 label-sync 的数据库从 SQLite 迁移到共享 PostgreSQL 时才做。

### 背景

你的其他项目（OliveBoard、AthenNest）都规划使用 Coolify 上的共享 PostgreSQL。label-sync 目前用 SQLite（stockpile.db），如果将来想统一备份和监控，可以考虑迁移。

### 任务

1. 在 config.py 中支持 DATABASE_URL 环境变量，默认值仍为 SQLite
2. 更新 alembic.ini 和 alembic/env.py 支持从环境变量读取数据库连接
3. docker-compose.yml 中添加可选的 PostgreSQL service
4. 写迁移脚本：SQLite → PostgreSQL 数据迁移

### 验收标准
- 默认仍使用 SQLite（不影响现有部署）
- 设置 DATABASE_URL 后可切换到 PostgreSQL
- 所有测试通过

---

## 执行顺序总结

```
Phase 0（安全审查）        ← 立刻做
  ↓
Phase 1（CLAUDE.md 重写）  ← 10 分钟
  ↓
Phase 3（中文目录名清理）  ← 30 分钟，影响范围小
  ↓
Phase 4（Node 配置清理）   ← 10 分钟
  ↓
Phase 2（目录结构整理）    ← 最大改动，1-2 小时，分 8 批执行
  ↓
Phase 5（CI/CD）           ← 15 分钟
  ↓
Phase 6（README 更新）     ← 20 分钟
  ↓
Phase 7（PostgreSQL，可选） ← 看需求
```

每个 Phase 完成后：
1. 确认 `pytest tests/` 通过
2. 确认 `docker compose build` 成功
3. commit + merge 到 main
4. Coolify 重新部署验证

---

## 给 Claude Code 的提示

- 开始前先 `git status` 确认工作区干净
- 每个 Phase 新建分支，完成后让用户确认再 merge
- Phase 2 移动文件时，**先复制再删除**，不要直接 `git mv`（防止 import 断裂时无法回退）
- 每移动一批文件后立即跑 `pytest`，红了就回退该批
- `phase_scripts/` 里的脚本用 subprocess 调用，可能有硬编码的 import 路径，要特别检查
- 前端模板（templates/）中如果有 `垃圾桶` 字样也要替换
- alembic/env.py 中的 `target_metadata` import 路径在 Phase 2 后需要更新

---

## 📋 2026-05-15 复审补丁说明

本 plan 经一轮复审，新增以下补充（已 inline patch 入对应 Phase）：

| 补丁 | 位置 | 内容 |
|---|---|---|
| **执行前置条件** | 顶部新增 section | v2 backtest / 论文图 / DB scp 必须先完成 |
| Phase 2 工时修正 | Phase 2 头部 | 1-2h → 1-2 天，留 buffer 3 天 |
| Phase 2 Import Audit | Phase 2 前置步骤 | GitNexus `tool_map` / `route_map` 直接出依赖图 |
| Phase 2 batch commit 模板 | 执行步骤 3 | 每批独立 commit，回退命令 |
| Phase 2 _scratch/ 修改 | 执行步骤 6 | spike 脚本 sys.path 处理 |
| **Phase 4 Biome 错误修正** | Phase 4 头部 | Biome 也需要 Node；正解是直接删 eslint 或用 ruff |
| Phase 5 ruff baseline | Phase 5 前置步骤 | 加 CI 前先 ruff fix + format，避免 CI 一开就红 |
| **Phase 6 改名澄清** | Phase 6 任务 1 | GitHub 改名 redirect 自动生效，Coolify 不受影响；但仍建议不改名 |

**未补丁但建议关注**:

- Phase 0 `git filter-repo` 改写历史**很危险**：如果发现敏感信息已 commit，建议先评估「真的有人 clone 过该 commit 吗」，没有的话直接 force-push 干净仓库；改写历史会让所有协作者重新 clone
- Phase 5 CI 可考虑加 type check（mypy / pyright），但优先级低
- Phase 5 之后可加 pre-commit hook 集成（本地 commit 时自动跑 ruff），但 Phase 5 跑通后再加

**未来扩展（不在本 plan 范围）**:

- 跟 `docs/thesis/迭代路线图.md` 协调：本 plan Phase 7（PG 接口）是迭代路线图 Phase 1（PG 数据迁移）的前置工作
- 本 plan 完成后再开始迭代路线图的功能扩展（Holt-Winters / Prophet / 监控等），代码自然落在 `app/services/` 干净位置

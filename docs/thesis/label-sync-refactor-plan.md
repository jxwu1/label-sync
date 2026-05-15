# label-sync 重构计划

> 本文档供 Claude Code 执行。每个 Phase 独立成一个 branch，完成后 merge 到 main。
> 重构原则：**不改变任何现有功能和业务逻辑**，只做结构整理和工程规范对齐。

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
2. **逐批移动文件**（每批移完跑测试）：
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
4. **更新 alembic 配置**：`alembic/env.py` 中的 model import 路径
5. **更新 Dockerfile**：如果 COPY 路径有变化

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

### 任务

1. **评估 package.json 的实际用途**：
   - 查看 `package.json` 内容，确认是否只用于 eslint
   - 如果是：考虑用 Biome 替代（`pip install biome` 或独立 binary，不需要 Node）
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
   - （仓库改名需要手动操作，建议改为 `erp-label-tool`，但这会影响 Coolify 部署配置，所以可以暂时不改名，先补 description）

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

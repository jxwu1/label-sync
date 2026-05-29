# PDA 扫描端 — 设计

**Date:** 2026-05-29
**Status:** Draft（待用户 review）
**Scope:** 单个功能模块，一个实现计划即可覆盖。
**Branch:** feat/pda-scan

## 目标

把现状的手工链路——「员工在 Zebra PDA 上用电子表格 App 扫条码 → 手动导出 xlsx →
传给管理员 → 管理员跑标签处理」——换成：「员工在 PDA **网页**上扫（界面和现在的电子表格
几乎一样）→ 点保存 → 自动进管理员 PC 的『待处理』队列 → 管理员一键跑现有三阶段」。

核心约束：**员工端无感切换、零学习**（界面就是一张表格，和现在一样，员工甚至不该察觉换了
东西）；所有便利与"聪明"都在**管理端、对员工不可见**。

`(action, verify)`：
- action: 新增 PDA 扫描网页 + 服务端扫描会话 + PC 待处理队列 + 两级权限，复用现有三阶段管线。
- verify:
  - 扫描会话 service / repo / route 三段单测全绿；
  - **物化出的 .xlsx 喂现有 phase1 解析，结果与等价手工表格一致**（关键回归，单测覆盖）；
  - 权限单测：`scanner` 账号除 `/pda/*` 外全部被挡；`admin` 不受影响；未登录跳 `/login`；
  - e2e 烟雾：scanner 登录 → 选员工 → 扫库位+条码 → 保存 → PC 待处理列表出现该批 →
    点处理触发现有 `run` → 三阶段跑通并产出 output。

## 关键决策（已与用户确认）

| 议题 | 决策 |
|---|---|
| "适配 PDA 的 xlsx" 指什么 | = **扫描采集表**：PDA 页本身就是边扫边长的表，保存时物化成现有格式 .xlsx |
| 员工端界面 | **纯净版电子表格**：只有 A 列（库位码 + 条码），B/C 空。仿现状，零学习、无感切换 |
| 库位 vs 条码区分 | **自动**：沿用现有 phase1 逻辑（字母前缀=库位码，纯数字=条码），员工不用切换 |
| 库位录入 | 扫库位标签（标签内容=库位码，如 `C08-12-03`），作为一行落入 A 列 |
| 在线 / 离线 | 在线为主（每扫一行后台落库）；断线本地缓存 + 重传，带"待同步"角标 |
| 实时显示型号/品名 | **不显示**（选纯净版的连带结论）；匹配照旧在 PC 的 phase2 判断 |
| 账号模型 | **不给员工建账号**。每台 PDA 一个共享 `scanner` 账号常驻登录，只能进 `/pda` |
| 操作员身份 | PDA 页顶选择器，名单 = `Employee` 表中 `is_scanner=1` 的员工；首次由管理员勾选谁会扫描 |
| 权限级别 | 两级：`scanner` / `admin`。`User.role` 默认 `admin`（老用户不变） |
| 保存后处理 | 进 PC「待处理」队列，管理员**手动**点处理 → 投 `input/` → 触发现有 `run` |
| 扫描数据持久化 | **服务端扫描会话**（`ScanSession` + `ScanItem`），边扫边存，崩溃不丢、可审计 |
| 重复条码 | 允许（同现状，现有管线处理） |

## 数据流（端到端）

```
[扫描员] 设备常驻 scanner 登录 → 打开 /pda（只此一页）
  选操作员（下拉：is_scanner 员工）→ 开始扫描会话
  扫库位标签 C08-12-03  ┐
  扫条码 5828...379      ├─ 每行实时 POST → 写 ScanItem（crash-safe）
  扫条码 5828...386      │   A 列自动区分库位/条码；扫完自动跳下一行
  扫库位标签 C08-12-02  ┘
  点「保存」→ finalize：status=pending，从 ScanItem 物化成现有格式扫描 .xlsx
──────────────────────────────────────────────
[管理员] PC「待处理」队列（新页面）：列 pending 批次（操作员 / 件数 / 时间）
  点「处理」→ 物化 .xlsx 投入 input/ → 触发现有 run_phase_one
            → 之后异常处理 / 确认 / 下载 = 现有三阶段 UI，零改动
  点「作废」→ status=discarded
```

## 架构

### 1. 数据模型（`app/models.py` + 一个 alembic 迁移）
- `User.role`：`TEXT NOT NULL DEFAULT 'admin'`，取值 `scanner` / `admin`。现有用户自动 admin，不影响管理员登录。
- `Employee.is_scanner`：`INTEGER NOT NULL DEFAULT 0`（0/1）。管理员勾选谁会扫描；PDA 操作员下拉只列 `is_scanner=1`。
- `ScanSession`：
  - `id` PK
  - `operator_employee_id` FK→Employee（必选）
  - `operator_name` 快照（冗余，保证后续改名不影响已生成批次命名）
  - `device` TEXT NULL（记录哪台设备 / 哪个 scanner 账号，便于审计）
  - `status`：`active` / `pending` / `processing` / `done` / `discarded`
  - `batch_label`：`{operator_name}价格标{YYYYMMDDHHMMSS}`（显示用，沿用现有 output 命名）
  - `item_count` 冗余计数
  - `created_at` / `finalized_at`
- `ScanItem`：
  - `id` PK，`session_id` FK→ScanSession
  - `seq` 行序（保证物化顺序）
  - `raw` 扫描原始值（库位码或条码原文）
  - `kind`：`location` / `barcode`（落库时按现有逻辑判定，便于审计/统计；物化只用 raw+seq）
  - `scanned_at`

### 2. 仓储 `app/repositories/scan_session.py`
- `create_session(operator_employee_id) -> ScanSession`
- `get(id)` / `get_active_for(device|account)`
- `append_item(session_id, raw) -> ScanItem`（判 kind、分配 seq、自增 item_count）
- `pop_last_item(session_id)`（撤销）
- `list_items(session_id)`（按 seq）
- `set_status(id, status)` / `list_pending()`

### 3. 服务 `app/services/scan_session.py`
- `start(operator_employee_id)`：校验该员工 `is_scanner`；建/恢复 active session。
- `scan(session_id, raw)`：trim → append_item；返回尾部状态（纯净版**不回**商品信息）。
- `undo(session_id)`：pop_last_item。
- `finalize(session_id)`：物化 .xlsx → status=pending；空会话（0 行）拒绝。
- `materialize_xlsx(session) -> Path`：**核心**。把 items 按 seq 写成现有格式扫描 .xlsx
  （单列、库位码与条码交替）。
  - 文件名需让现有 phase1 正确取出 `operator_name`（现有逻辑取 `scan_files[0].stem`）——
    **实现时对齐 phase1 的取名逻辑**，使最终 output 目录 = `{operator_name}价格标{ts}`；单测覆盖。
  - 复用现有 `storage` / `file_io`（openpyxl）写 xlsx。

### 4. 路由 `app/routes/pda.py`（蓝图，前缀 `/pda`）
扫描端（`scanner` 或 `admin` 均可）：
- `GET  /pda` → 渲染 `templates/pda.html`（独立移动页，不进桌面外壳）
- `GET  /pda/operators` → `is_scanner` 员工列表（下拉数据）
- `POST /pda/session/start` `{operator_employee_id}`
- `GET  /pda/session/<id>` → 当前明细（刷新 / 续扫恢复）
- `POST /pda/session/<id>/scan` `{raw}`
- `POST /pda/session/<id>/undo`
- `POST /pda/session/<id>/finalize`

PC 端（`@require_role('admin')`）：
- `GET  /pda/pending` → 待处理批次列表（或做成现有 SPA 的一个新 page）
- `POST /pda/pending/<id>/process` → 物化（若未物化）/ 投 `input/` → 触发现有 `run_phase_one`
- `POST /pda/pending/<id>/discard`

管理端（`@require_role('admin')`）：
- 现有 `/admin` 用户管理扩展：建 / 改用户时可选 `role`。
- 员工 `is_scanner` 勾选：放在用户管理页或考勤员工页（见"待确认 #4"）。

### 5. 权限（基于现有 Flask-Login + before_request，`app/auth.py`）
- 现有 `@app.before_request` 已强制登录。新增规则：
  - `current_user.role == 'scanner'` 时，只放行 endpoint ∈ `pda.*` / `auth.*` / `static`；其余 → 跳 `/pda`（或 403）。
  - 新装饰器 `@require_role('admin')`，套在所有 PC 业务路由（标签处理 / 采购 / 分析 / 库存 / 用户管理…）。
- 共享 scanner 账号：管理端创建一个 `role=scanner` 账号（如 username=`pda`），每台设备用它登录常驻。

### 6. 前端 `templates/pda.html` + `static/js/pda.js` + `static/css/pda.css`
- **独立页**（参照现有 `login.html`），不含侧边栏 / 桌面外壳；移动优先、大触摸目标、表格铺满。
- 顶栏：操作员下拉（`is_scanner` 员工）+ 在线点 + 「保存」。
- 主体：电子表格（行号 + A 列）；扫描即 append 行、自动滚到底；库位码加粗、条码缩进（仿截图）。
- 隐藏 autofocus 输入承接扫描枪键盘输入：扫完发 Enter → 提交该行 → 重新聚焦等下一扫。
- 「撤销」删最后一行；「保存」→ finalize → 提示"已提交，共 N 件"，清屏可开新一批。
- 断线：行先入本地队列 + "待同步 n"，联网后台补传，不丢数据。
- **部署提示**：把设备浏览器主页 / 快捷方式设为 `/pda`，员工打开即"表格"，实现无感切换。

## 异常处理 / 边界
- **WiFi 抖动**：每行 POST 失败 → 本地缓存 + 重试 + "待同步"角标；长时间离线给明显提示。
- **物化 .xlsx 必须兼容现有 phase1**：最大风险点，单测专门覆盖（物化结果 == 等价手工表 解析结果）。
- **库位格式**：纯净版**不**在员工端拦截（保持无感）；非法库位码照旧由 phase1 检测、在 PC 端处理。
- **新品 / 未匹配**：员工端不提示（纯净版）；phase2 照旧识别为新品。
- **同设备并发**：一个 scanner 账号同一时间一个 active session；开新会话前若有未 finalize 的，提示续扫或丢弃。
- **空保存**：0 行不允许 finalize。
- **改名**：`operator_name` 快照，`batch_label` 不受后续改名影响。

## 测试
- 单元：
  - `materialize_xlsx`：给定 items 序列 → xlsx → 现有 phase1 解析 → location_map 与手工等价表一致。
  - service：`start`（校验 is_scanner）/ `scan` / `undo` / `finalize` 状态机；空保存拒绝；并发 active 处理。
  - repo：append / pop / list 顺序、item_count、list_pending。
  - 权限：scanner 访问 PC 路由被挡；admin 正常；未登录跳 `/login`。
- e2e 烟雾（Playwright）：scanner 登录 → 选员工 → 扫库位+条码若干 → 保存 → `/pda/pending` 出现 →
  process 触发 `run` → 三阶段跑通、产出 output。

## 复用 / 不改动
- **三阶段 `phase_scripts` 零改动**（物化成它已吃的格式）。
- 复用 `stockpile_db`（只读）、`storage` / `file_io`（写 xlsx）、现有 `/run`·`/status`·异常处理 UI。
- 现有 `auth.py` 扩展（加 role 判断），不重写。

## 待你回来确认的点
1. **纯净版连带**：员工端**不显示**型号/品名、**不**在端上拦新品/错码（都交给 PC phase2）—— 确认 OK？
2. **断线策略**：本地缓存 + 重传（推荐）  vs  直接要求必须在线（离线就禁止扫）—— 你倾向哪种？
3. **共享 scanner 账号**：用户名（如 `pda`）+ 初始密码谁来设？要不要**每台设备不同账号**（便于审计是哪台扫的）？
4. **is_scanner 勾选**放哪个界面顺手：用户管理页 / 考勤员工页？
5. **「待处理队列」**做成独立页，还是现有 SPA 里加一个 nav page？

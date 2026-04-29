# 阶段 3：扫描历史浏览 (feature/scan-history) — 设计文档

**起草日期**：2026-04-29
**对应 roadmap 阶段**：阶段 3 `feature/scan-history`
**前置依赖**：阶段 1（ORM）✓ / 阶段 1.5（多库位）✓ / 阶段 1.6（最近改动）✓ / 阶段 2（Alpine）✓
**预计 PR**：1 个 (`feature/scan-history`)

---

## 1. 问题与目标

### 当前痛点

`output/` 目录下已经存档了 51 个扫描批次（命名 `{员工}价格标{YYYYMMDDHHMMSS}/`），但**前端无法浏览**：

- 想查"ALI 这周扫了几次"——只能命令行 `ls output/`
- 想重新下载某次产出的 CSV——只能手工去服务器 filesystem 里找
- 阶段 1.6 最近改动只看到 DB 端 diff，看不到员工维度（DB 不存员工）和原始扫描内容

### 主要使用场景

按使用频率排序（与用户访谈对齐）：

1. 🔝 **查某员工的近期扫描记录**（"ALI 上周扫了几次"）
2. 🔝 **重新下载某次扫描产出的 CSV**（业务系统再导入需要）
3. 🟡 **偶尔查看某次扫描具体内容**（通过下载文件 → Excel 打开，不在 web 内浏览）

明确**不做**：

- 反查"DB 某次变更对应的源头扫描"（YAGNI；阶段 1.6 已覆盖 DB 端 audit；filesystem timestamp 与 snapshot.taken_at 对齐有精度问题）
- 员工生产力对比/统计图表（YAGNI；用户场景未点名需要）
- web 内 CSV 内容浏览（YAGNI；下载到本地 Excel 打开是合理"偶尔"路径）
- 文本搜索 / 日期范围筛选（YAGNI；仅员工 dropdown 已够用）

### 成功标准

1. 货号历史 tab 内出现第 3 个二级 tab `📂 扫描批次`
2. 默认显示最近 100 个批次时间倒序，含员工 dropdown 筛选
3. 每条批次能展开看 CSV/xlsx 文件清单 + 行数 + 下载链接
4. 点 CSV/xlsx 下载链接立即拿到 filesystem 原文件
5. `pytest` 全套通过；新增 service + routes 单测覆盖核心路径

---

## 2. 决策摘要（来自 brainstorming）

| # | 决策 | 选项 | 理由概要 |
|---|------|------|---------|
| 1 | 跟阶段 1.6 关系 | A 员工×时间 + B 单批次详情 为主；C 跨链反查不做 | 1.6 已覆盖 DB 端 audit；filesystem 提供"员工 + 原始内容"维度 |
| 2 | UI 布局 | B：两层（全局批次时间线 + 员工 dropdown），点行展开 | 51÷8≈6 批/人，员工列表独占一栏太薄；行内展开避免抽屉嵌套 |
| 3 | CSV 内容展示 | C：不展开内容，仅 metadata + 下载链接 | CSV 不含位置；要 join xlsx 复杂度跳升；场景 3"偶尔"用，下载本地看够 |
| 4a | 筛选维度 | 仅员工 dropdown | 51 个 batch 不需要复杂筛选 |
| 4b | Pagination | 截断最近 100，无分页 UI | 数据量小，未来 3 倍增长才触顶 |
| 4c | API endpoint | 3 个 GET（list / download CSV / download xlsx） | 仿 recent_changes 模式；REST 简单 |
| 4d | xlsx 下载 | 支持，每个 batch 内可能多个 xlsx | 原始扫描记录有时需要追溯 |
| 4e | 文件结构 | 仿 recent_changes 三件套 + 测试 | 项目已有先例 |
| 4f | PR 拆分 | 单 PR | 代码量预估比 1.6 小 |

---

## 3. 架构设计

### 3.1 数据源（filesystem）

```
output/
  ABADUL价格标20260409142110/    ← batch_id = 文件夹名
    1产品信息导入模板.csv          ← CSV 产出（61 列业务模板，UTF-8-sig）
    ABADUL.xlsx                  ← 原始扫描文件（可能多个）
  ALI价格标20260423155137/
    1产品信息导入模板.csv
    ALI.xlsx
  ...
```

**解析规则**：

- `batch_id` = 完整文件夹名，作 URL-safe ID（含中文，需 URL encode；Flask 解码自动处理）
- 解析 `^(?P<employee>.+?)价格标(?P<timestamp>\d{14})$` 抽员工名 + 14 位时间戳
- 时间戳格式 `YYYYMMDDHHMMSS` → 解析成 `datetime`
- 不匹配此 pattern 的目录直接忽略（防御性）

### 3.2 后端 service：`scan_history_service.py`

公共 API（仿 `recent_changes_service.py` 风格）：

```python
def list_batches(limit: int = 100) -> list[dict]:
    """扫 output/ 目录，按时间倒序返回最近 limit 个 batch 概览。
    员工筛选由前端做（拿到全部数据后 dropdown 切换），服务端不过滤。

    每条 dict 字段：
        batch_id: str               # 文件夹名
        employee: str               # 员工名
        scanned_at: str             # ISO datetime
        csv_filename: str | None    # 主 CSV 文件名（找不到为 None）
        csv_rows: int | None        # CSV 行数（不含 header）
        csv_size_bytes: int | None
        xlsx_files: list[dict]      # [{name, size_bytes}]
    """

def get_batch_csv_path(batch_id: str) -> Path | None:
    """返回 batch 内主 CSV 的 Path；不存在返回 None。"""

def get_batch_xlsx_path(batch_id: str, filename: str) -> Path | None:
    """返回指定 xlsx 文件 Path；越界或不存在返回 None。
    必须做 path traversal 防护（拒绝含 .. / 绝对路径的 filename）。
    """

def list_employees() -> list[str]:
    """从现有 batch 中抽出 unique 员工名，按字母序。"""
```

**设计要点**：

- 纯文件系统操作，**不写 DB**、不缓存（每次扫；51 个文件夹的 stat 调用 < 50ms）
- 行数算法：`sum(1 for _ in csv_path.open(encoding="utf-8-sig")) - 1`（去 header）
- 路径安全：所有 `batch_id` / `filename` 在 service 边界做 `Path.resolve()` + 检查 `is_relative_to(OUTPUT_DIR)`，绝不直接拼字符串
- Encoding 健壮：CSV 用 `utf-8-sig`，行数计算只数行不解析内容（避免 61 列 schema 假设）

### 3.3 后端 routes：`routes_scan_history.py`

```python
GET /scan_history/batches
    → {"ok": True, "employees": [...], "batches": [...]}
    总是返回最近 100 条全部员工的记录；员工筛选由前端做（dropdown）

GET /scan_history/batches/<batch_id>/download/csv
    → send_file(csv_path, as_attachment=True, download_name=...)
    404 if batch_id 不存在或无 CSV

GET /scan_history/batches/<batch_id>/files/<filename>
    → send_file(xlsx_path, as_attachment=True)
    404 同上 + path traversal 拒绝
```

注：

- `employees` 字段在 list endpoint 一起返回（驱动前端 dropdown），避免再开一个 endpoint
- 前端筛选：100 行 × ~150 字节 ≈ 15KB，完全可一次拉全；server-side 筛选属于 YAGNI

### 3.4 前端：`static/js/index-scan-history.js`

仿 `index-recent-changes.js` 风格的 vanilla JS module（不引入新框架；当前阶段 2 已 SSOT 化 nav，但**各 tab 内部交互仍用命令式 DOM**——见阶段 2 spec §3.1 边界）。

模块入口由 `templates/index.html` 在 pageHistory 内的二级 tab 切换驱动（已有 history.js / index-recent-changes.js 模式）。

UI 结构：

```
[页面顶部]
  员工: [全部 ▼]   显示最近 100 条

[列表]
  ┌─ 2026-04-25 13:00:58 · ALI · 32 行 · CSV 1 · xlsx 1                ▼
  ├─ 2026-04-23 15:51:37 · ALI · 18 行 · CSV 1 · xlsx 1                ▼
  └─ ...
        ↓ 点击展开
  ┌─ 2026-04-25 13:00:58 · ALI · 32 行 · CSV 1 · xlsx 1                ▲
  │   📄 1产品信息导入模板.csv  (32 行 / 4.2 KB)  [下载]
  │   📊 ALI.xlsx  (15.3 KB)                       [下载]
  └─
```

事件流：

1. `init()` 进入 tab 时 fetch `/scan_history/batches`，获得 `employees` + `batches`
2. dropdown change → 用同一个 `batches` 数组前端过滤（不重新请求，因为已经全部在内存里）
3. 行点击 → 切换该行的 expanded 状态（用纯 CSS class 切换，不改全局 state）
4. 下载按钮 → 直接 `<a href>` 触发浏览器下载，不走 fetch

### 3.5 模板挂入点（`templates/index.html`）

pageHistory 现在有 2 个 sub-tab：`🔎 货号查询` + `📊 最近改动`。在二者之后追加：

```html
<button class="..." data-subtab="scan-history">📂 扫描批次</button>

<div class="..." data-subtab-panel="scan-history">
  <div class="scan-history-bar">
    <select id="scanHistoryEmployee">
      <option value="">全部员工</option>
      <!-- 由 JS 填充 -->
    </select>
    <span>显示最近 100 条</span>
  </div>
  <div id="scanHistoryList"></div>
</div>
```

### 3.6 CSS

新建 `static/css/page-scan-history.css`（沿用 page-history 的色调和 spacing token），主样式：

- `.sh-row` 时间线行：flex 布局，时间 + 员工 + 行数 + 文件计数
- `.sh-row.is-open .sh-detail` 展开详情区
- `.sh-file` 单文件行：图标 + 文件名 + 大小 + 下载按钮（复用 `pur-btn-dl` 类，与采购页风格统一）

---

## 4. 测试策略

### 后端单测（`tests/test_scan_history_service.py`）

- `test_list_batches_returns_sorted_descending_by_timestamp`
- `test_list_batches_skips_unrecognized_folder_names`
- `test_list_batches_handles_missing_csv_file`
- `test_list_batches_handles_empty_csv`
- `test_list_batches_truncates_to_limit`
- `test_get_batch_csv_path_returns_none_for_missing_batch`
- `test_get_batch_xlsx_path_rejects_path_traversal`
- `test_list_employees_returns_unique_sorted`

### Routes 单测（`tests/test_scan_history_routes.py`）

- `test_batches_endpoint_returns_list_and_employees`
- `test_download_csv_returns_file`
- `test_download_csv_returns_404_for_missing_batch`
- `test_download_xlsx_returns_file`
- `test_download_xlsx_returns_404_for_path_traversal`

### 测试 fixture

新建 `tests/_fixtures/scan_history/output_sample/` 含 3 个 mock batch 目录（不同员工/时间/行数），让单测在 tmp_path 下复制 fixture 跑。

不复用真实 `output/` 数据（51 个真实扫描包不该进 git）。

### 前端验证

不写自动化测试（与阶段 2 决策一致），手测 checklist 增补到 `docs/verify-checklist.md`：

```markdown
## 阶段 3: feature/scan-history
- [ ] 货号历史 tab 内出现 3 个二级 tab；点 📂 扫描批次切到列表
- [ ] 列表显示最近 N 条批次（按时间倒序）
- [ ] 员工 dropdown 含"全部"+ 实际扫描过的员工名
- [ ] 选员工后列表只剩该员工的批次
- [ ] 点击行展开 → 显示 CSV + xlsx 文件清单 + 下载按钮
- [ ] 点击 CSV 下载链接 → 浏览器拿到原始 CSV 文件，文件名正确
- [ ] 点击 xlsx 下载链接 → 拿到原始 xlsx 文件
```

---

## 5. 风险与回滚

### 已识别风险

1. **大批量目录扫描慢**：当前 51 个，每个 stat + 行数计算 ~1ms，list 一次 < 100ms。如果未来扫到 5000+，引入文件级 mtime 缓存。当前 YAGNI
2. **批次目录被删/损坏**：service 防御性返回 None / 跳过；routes 返回 404
3. **CSV 编码异常**：行数计算用 `utf-8-sig` 读取；如果遇到非 utf-8 文件捕获异常返回 None；不让一个坏 batch 拖垮整个 list
4. **路径穿越**（path traversal）：所有用户输入的 `batch_id` / `filename` 经过 `resolve()` + `is_relative_to(OUTPUT_DIR)` 校验，拒绝含 `..` 或绝对路径的请求
5. **员工名含特殊字符**：当前所有员工名都是 ASCII（ALI / ABDUL 等），不预防 emoji / 中文 / 路径注入。文件夹名做 URL encode 让 Flask 自动 decode 即可

### 回滚预案

- 单 PR，单 revert 即恢复 main 状态
- 不动现有 schema、不写 DB，无数据迁移成本

---

## 6. 文件清单

**新增**（5 个）：

- `scan_history_service.py` (~150 行)
- `routes_scan_history.py` (~50 行)
- `static/js/index-scan-history.js` (~150 行)
- `static/css/page-scan-history.css` (~80 行)
- `tests/test_scan_history_service.py` (~150 行)
- `tests/test_scan_history_routes.py` (~80 行)
- `tests/_fixtures/scan_history/output_sample/...` 测试 fixture
- `docs/verify-checklist.md` 追加阶段 3 段

**修改**（3 个）：

- `routes.py` 注册 `bp_scan_history` blueprint
- `templates/index.html` pageHistory 内追加第 3 个 sub-tab
- `docs/superpowers/plans/2026-04-28-roadmap.md` 阶段 3 完成时打勾

---

## 7. 后续路线（写入 roadmap）

阶段 3 完成后，按下表追加：

| 项 | 归属 | 触发条件 |
|---|------|---------|
| **批次反查（DB 变更 → 源头扫描）** | 阶段 3 后续 | 用户出现"想知道这次 stockpile 改动是哪个员工扫的"具体调查需求 |
| **CSV web 内浏览** | 阶段 3 后续 | 用户反馈"每次都下载到本地太麻烦" |
| **员工产出统计/图表** | 阶段 5 候选 | 跟销售分析 dashboard 一起做 |
| **filesystem 扫描结果缓存** | 性能优化 | batch 数 > 1000 时考虑 |
| **日期范围筛选** | YAGNI | 用户反馈需要按月/季度查时再做 |

---

## 8. 工作量估算

- backend service + routes + 测试：1 天
- frontend module + CSS：0.5 天
- 集成 + verify checklist 手测：0.5 天
- 合计：约 **2 个工作日**

---

## 9. 决策日志

按 Q1-Q4 顺序记录，详见 §2 决策摘要表。这次会话的关键转折：

1. Q1（"模块用来干什么"）—— 用户问"你觉得这个模块用来干什么的"。我反推得出**三类场景**（员工×时间 / 单批次详情 / 跨链反查），用户确认前两类是核心，反查是 YAGNI。这定下了整个 spec 的焦点
2. Q3 中途纠正 —— 我先建议"展示 CSV 关键列含位置"，发现 CSV 模板**不含位置**字段（位置在原始 xlsx 里），重新选 C "只显示 metadata，不展开内容"。避免了一次跨文件 join 的过度设计
3. 阶段 2 §3.1 边界继续生效 —— 各 tab 内部交互仍用命令式 DOM（不强行 Alpine），跟 history.js / index-recent-changes.js 一致风格

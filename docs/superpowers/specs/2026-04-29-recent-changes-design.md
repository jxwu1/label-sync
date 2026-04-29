# 货号历史 - 最近改动 设计文档

**起草日期**：2026-04-29
**所属阶段**：阶段 1.5 之后的小功能（独立分支）
**前置依赖**：阶段 1.5 已完成（stockpile_snapshots、stockpile_changes 已稳定）

---

## 目的

### 主用例（A 类：import 后审计 / 收据）

每次 import 完，用户打开这个页面立刻看一眼：
> 这次同步进来 X 个 location 改动 / Y 个新货号 / Z 个 deactivate / W 个 model 变更，跟我心里预期的量级对得上吗？

如果老系统里有人手抖批量改错（误清空一片库位 / 误删货号），从这里能立刻通过异常峰值发现。

### 次要用例（B 类）

"最近哪些货号搬过家了" —— 这是 A 的副产品（同份数据按"哪些 barcode"重组），不需要专门设计。

### 不做（C 类异常巡检）

跟「数据质量」页职责重叠：
- 数据质量页关注**持续性状态**（snapshot 聚合 "现在 DB 里有多少脏数据"）
- 最近改动页关注**事件流**（时间线 "今天发生了什么"）

强行塞 C 会模糊边界，保持单一职责。

---

## 数据基础

| 数据源 | 用途 |
|---|---|
| `stockpile_snapshots` WHERE `trigger='import'` | 批次锚点；每条 = 一次 import 完成时刻 |
| `stockpile_changes` | 按时间窗关联到批次的明细事件 |

### 批次窗口定义

snapshot 是 import **完成**时刻，所以：
- 当前批次窗口 = `(prev_snapshot.taken_at, current_snapshot.taken_at]`
- 第一个 snapshot 没 prev 时取 `'1970-01-01 00:00:00'`
- changes 落在该窗口内归这次 batch

---

## 真实数据校准（2026-04-29）

| 项 | 数值 |
|---|---|
| 总 stockpile_changes | 3856 |
| 今天产生 | 2929（4 次 import 累计） |
| 今天涉及 barcode | 1172 |
| - 只变 1 次 | 1036 |
| - 变 ≥2 次 | 136（其中 129 是 round-trip：A→B→A 终态等于起始） |
| 实质事件数 | ~1102（1036 + 7 多次但终态变了 + 57 model + 2 新增） |
| Round-trip 噪音 | ~1827 条中间步骤 |

信噪比印证为什么需要"折叠净效应"作为默认视图。

---

## 入口与布局

### 二级 tab

`pageHistory` 内顶部加二级 tab，跟现有"货号查询"并列：

```
[ 🔎 货号查询 ]  [ 📊 最近改动 ]
```

默认进 "🔎 货号查询"（保持现状）。

### 顶部批次选择器

下拉，列出最近 10 次 `trigger='import'` 的 snapshots，按 `taken_at` DESC：

```
最近 import：2026-04-29 14:28:12（43497 条 / 改动 1102 个货号）   ▾
```

每条选项格式：日期时间 / 总条目数 / 该次涉及货号数。切换 = 整页刷新到该批次数据。

默认选中：最近一次。

### Summary 卡片

5 个数字 + 1 行噪音说明：

```
┌──────────────────────────────────────────────┐
│  📦 库位变更  1036    🏷 型号变更  57         │
│  ➕ 新增      2       ❌ 失效     0           │
│                            🔁 来回波动 129 组  │
└──────────────────────────────────────────────┘
```

- 5 个数字 = 折叠后保留下来的实质事件数（按 `(barcode, field_name)` 维度，roundtrip 已剔除）
- 点击数字 = 自动加对应 field/change_type filter
- "🔁 来回波动 N 组"：被折叠剔除的 `(barcode, field_name)` 组数（终态==起始态）；折叠模式下灰色辅助说明，hover tooltip 解释；raw 模式下变实色（噪音此时被展示）

**口径要求**：summary 5 个数字之和 = 折叠模式 list 的总行数；roundtrip_count 跟折叠算法剔除的组数一致。两处共用同一 `(barcode, field_name)` 维度。

### 默认视图（折叠模式）

按 barcode 聚合，每 barcode 一行（同 barcode 同时改了多个字段 = 多行，不合并）：

| 货号 | 型号 | 变化 | 时间 |
|---|---|---|---|
| 5828079176915 | 17691 | 库位 `B06-20-02/XB07-12/XB07-12` → `B06-20-02/XB07-12` | 14:28:09 |
| 5828079123456 | 12345 | 型号 `M1` → `M2` | 14:27:55 |

- 排序：该 barcode 最后一条 change 时间倒序
- 库位 / 型号变化按列分，不混
- "变化"列：库位 / 型号 diff 用 `→` 连接；新增显示 `➕ 新货号`；失效显示 `❌ 失效`
- 点击整行 → **跳到 "🔎 货号查询" tab，预填该 barcode，自动搜索**（复用现有 history search，不重写）

### Raw 切换

Summary 卡片右上角 toggle：

```
[ 折叠净效应 (1102) | 展开 raw 事件 (2929) ]
```

切 raw 模式后：
- 每行 = 一条 `stockpile_changes`，按 `created_at` DESC
- 列：货号 / 字段 / 旧值 / 新值 / 变化类型 / 时间
- 行数 = 该批次原始 changes 总数（含 round-trip 中间步骤）

### 过滤

顶部一排 chip：

折叠模式：
```
[全部] [仅库位] [仅型号] [仅新增] [仅失效]
```

raw 模式追加：
```
[仅 update] [仅 insert] [仅 deactivate] [仅 reactivate]
```

每个 chip 旁边显示当前过滤后的条数；点击 chip = 列表 filter；同时只能激活一个 chip。

不做全文搜索框：搜某个 barcode 应该走"🔎 货号查询" tab。

---

## 后端

### 新文件 `recent_changes_service.py`

三个公共函数：

```python
def list_recent_imports(limit: int = 10) -> list[dict]
    """返回最近 N 次 import snapshot 概览。
    每条 dict: {batch_id, taken_at, total_local, change_count, affected_barcodes}
    """

def get_batch_summary(batch_id: int) -> dict
    """返回该批次的 5 个统计数字 + roundtrip 数。
    {location_changes, model_changes, inserts, deactivates, reactivates, roundtrip_count}
    """

def get_batch_changes(
    batch_id: int,
    mode: Literal["collapsed", "raw"] = "collapsed",
    filter_field: str | None = None,
    filter_change_type: str | None = None,
) -> list[dict]
    """返回批次的明细行。
    
    collapsed 模式：按 barcode 聚合，多字段同 barcode 拆多行；
    raw 模式：原 stockpile_changes 行。
    
    filter_field: 'stockpile_location' | 'product_model' | 'product_barcode' | 'is_active' | None
    filter_change_type: 'update' | 'insert' | 'deactivate' | 'reactivate' | None
    """
```

### 批次窗口工具函数（私有）

```python
def _batch_window(session, batch_id: int) -> tuple[str, str]:
    """返回 (window_start, window_end) 字符串。
    window_end = snapshot[batch_id].taken_at
    window_start = 上一个 trigger='import' snapshot 的 taken_at；不存在时返回 '1970-01-01 00:00:00'
    """
```

### 新 routes 文件 `routes_recent_changes.py`

三个 GET endpoint，全部 jsonify：

```
GET /recent_changes/imports                                       → list_recent_imports
GET /recent_changes/<batch_id>/summary                            → get_batch_summary
GET /recent_changes/<batch_id>/changes?mode=collapsed&field=...   → get_batch_changes
```

### 折叠逻辑细节

`get_batch_changes(mode="collapsed")` 的核心算法：

1. 查询 batch window 内所有 stockpile_changes
2. 按 `(barcode, field_name)` 分组
3. 每组：
   - 取最早那条的 `old_value` 作 from
   - 取最晚那条的 `new_value` 作 to
   - 如果 `from == to` → 全是 round-trip，**整组丢弃**
   - 否则产出一行：`{barcode, field, from, to, latest_changed_at}`
4. 按 `latest_changed_at` DESC 排序

注意：roundtrip 检测是按 `(barcode, field_name)` 维度，不是按 barcode 整体。一个 barcode 可能 location 是 round-trip 但 model 实际变了 —— model 那行保留。

---

## 前端

### 文件

- `static/js/index-recent-changes.js` —— 跟 history.js 同级的 vanilla module
- 入口：`index.js` 的 `switchPage('history')` 中加二级 tab 切换逻辑（或 history.js 内部处理）
- CSS：加到 `static/css/page-history.css`，复用现有 `.timeline-row` 等样式

### 状态

模块内闭包变量：
- `_currentBatchId`
- `_currentMode` ("collapsed" | "raw")
- `_currentFilter` ({field, change_type})
- `_lastSummary` （供数字点击 → 加 filter 用）

切换批次 / 模式 / filter 都触发一次 fetch + 重新 render，不做客户端 cache（数据小，1102 行 / 2929 行 JSON < 200KB）。

### 行点击下钻

点击折叠行 → 调 `switchSubTab('search')` + 触发 history search，跟现有 "🔎 货号查询" tab 共用 input + 查询逻辑，不复制。

---

## 测试

### `tests/test_recent_changes_service.py`

最少覆盖：

1. `list_recent_imports`：插入 3 个 snapshot（2 个 import + 1 个 compare）→ 只返回 2 个 import，按时间倒序
2. `_batch_window`：第一个 snapshot 时 window_start = `'1970-01-01 ...'`；非第一个时 = 上一 import snapshot 的 taken_at
3. `get_batch_summary`：构造 batch 内 5 种类型变更，count 正确；roundtrip 不计入实质 location_changes；summary 5 数之和 == collapsed list 行数；roundtrip_count == 被剔除组数
4. `get_batch_changes(collapsed)`：
   - barcode A 单字段单变更 → 1 行
   - barcode B 同字段多次变更但 round-trip → 0 行
   - barcode C 同字段多次变更但终态不同 → 1 行（合并为 from→to）
   - barcode D 同时改 location 和 model → 2 行
5. `get_batch_changes(raw)`：返回所有原 stockpile_changes 行，含 round-trip 中间步骤
6. filter 参数生效（field / change_type）

---

## 不做的事

明确剔除以避免范围蔓延：

- ❌ 不按"今天"维度合并多次 import（粒度太粗，跟主用例冲突）
- ❌ 不按 barcode 二级展开（点击直接跳搜索更顺）
- ❌ 不做异常检测 / 告警（数据质量页职责）
- ❌ 不做导出 CSV / 修复模板（YAGNI，等真需要再说）
- ❌ 不做 model 变化的 diff 高亮（库位 diff 够用，model 通常是补字符）
- ❌ 不做 stockpile_changes 跨批次时间筛选（如"过去 7 天所有 import"），全按批次切

---

## 实施顺序（供下一步 plan 参考）

1. 后端 service + routes（含单测）
2. 前端 module（先实现折叠模式，跑通批次切换 + summary + 列表）
3. raw toggle + filter chip
4. 行点击下钻到 history search
5. CSS 美化与现有 history 页面统一

每步独立可 review。

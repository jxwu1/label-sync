# 货号历史页 + admin 清理 — 设计文档

**日期**：2026-04-28
**分支**：`feature/model-history`
**作者**：jxwu1
**模型**：Claude Opus 4.7

## 背景

围绕 ~4 万货号的"数据平台"长期路线（4 个子系统：A 型号历史 / B 扫描历史 / C 进出货事件 / D 销售分析），本期只做**第 1 期 = A**：型号搜索 + 库位变更时间线，作为后续纠错与数据展示的基础入口。

同时**顺手清理已成死代码的 admin（B 端）页面** —— `/admin` 路由从未被实际使用（用户一直在两台机器上各开 A 端，互传已通过 A 端 FAB 抽屉完成），且 admin 唯一独占的"月度扫描柱状图"功能用户已确认无意义可删。

## 目标 / 非目标

**目标**：

1. 在 A 端新增第 5 个 tab "📜 货号历史"
2. 输入型号或条码（精确）→ 显示当前状态 + 聚合后的变更时间线
3. 删除 `/admin` 页面及其唯一独占的 `/stats` 路由
4. 不变更数据库 schema，不影响现有 4 个 tab 与互传功能

**非目标**（明确不做，留给后续期）：

- 模糊搜索
- 就地编辑库位 / 型号
- 时间线分页 / 筛选 / 导出
- 扫描批次浏览（第 2 期）
- 进出货事件录入（第 3 期）
- 销售分析（第 4 期）

## 数据现状

```
stockpile          43,497 行   product_barcode (UNIQUE) / product_model / stockpile_location
                              / is_active / source / created_at / updated_at
stockpile_changes     927 行   product_barcode / field_name / old_value / new_value
                              / change_type / created_at
```

**barcode ↔ model 关系**：
- 62% 行 model 是 barcode 的后 5 位（去掉校验位）：`barcode[-6:-1]`
- 37% 行 model == barcode
- 1% 其他长度组合

两列均 UNIQUE，搜索时 `WHERE product_model = ? OR product_barcode = ?` 一条 SQL 解决。

**变更分布**：
- field_name：`stockpile_location` 91% / `is_active` 4% / `product_model` 3% / `product_barcode` 1%
- change_type：`update` 95% / `deactivate` 2% / `reactivate` 2% / `insert` 1%

**时间间隔分布**（相邻变更对，per barcode）：

```
=  0 秒    55.0%   ← batch 操作（同秒多条）
1-5 秒      1.3%   ← 同一操作的边界
6-60 秒     0.0%   ← 干净真空
> 1 分钟   43.8%   ← 真正的独立操作
```

5 秒窗口聚合不会误合并任何独立操作（数据中无 5-60 秒的间隔）。

## 架构

### 后端

| 文件 | 行数预估 | 职责 |
|---|---|---|
| `routes_history.py`（新） | ~30 | 1 个端点 `GET /history?q=` |
| `history_service.py`（新） | ~80 | DB 查询 + 聚合逻辑 |
| `routes.py`（改） | +1 | 注册新 blueprint |
| `tests/test_history_service.py`（新） | ~80 | 聚合 / 查询 / 边界单测 |

**只读访问** `stockpile` + `stockpile_changes`，**无 schema 变更**。

### 前端

| 文件 | 行数预估 | 职责 |
|---|---|---|
| `static/js/history.js`（新） | ~80 | 搜索调用 + 渲染时间线 |
| `static/css/page-history.css`（新） | ~120 | 页面专属样式（沿用 tokens） |
| `templates/index.html`（改） | +30 | 加 nav 项 + page section + css/js 引入 |
| `static/js/index.js`（改） | +5 | tab 切换路由到 history 页 |

样式沿用 filing-cabinet 主题（Solarized 调色 / panel / tokens.css），不引入新设计语言。

### admin 清理

**删除文件**（5 个）：
```
templates/admin.html              98 行
static/css/admin.css             156 行
static/js/admin.js               240 行
static/js/admin-messaging.js      40 行
static/js/admin-transfer.js       61 行
```

**改动文件**（4 个）：
```
routes_pages_tasks.py    删 /admin 路由（3 行）
routes_query.py          删 /stats 路由（4 行）
query_service.py         删 read_monthly_stats() + _YYYYMMDD_LEN 等相关常量
使用文档.md              删 /admin 段落
README.md                删 /admin URL 提及
```

**保留**（仍有其他页面在用）：
- `routes_collab.py` / `routes_transfer.py` —— A 端 FAB 抽屉互传
- `routes_monthly_summary.py` / `monthly_summary_service.py` —— A 端"采购" tab 月度采购总结
- `config.py` 的 `dual_mode = True` —— 控制 transfer 目录创建

## API

### `GET /history?q=<input>`

**入参**：`q` 是用户输入字符串（型号或条码），strip 空白后精确匹配。

**响应**：

未找到：
```json
{ "ok": true, "found": false }
```

找到：
```json
{
  "ok": true,
  "found": true,
  "current": {
    "barcode": "5828079100248",
    "model": "10024",
    "location": "A22-04-04",
    "is_active": true,
    "source": "scan_import",
    "updated_at": "2026-04-27 12:43:08",
    "created_at": "2026-04-25 16:52:43"
  },
  "events": [
    {
      "at": "2026-04-27 12:43:08",
      "source": "scan_import",
      "change_type": "update",
      "changes": [
        { "field": "stockpile_location", "old": "A22-04-04", "new": "" },
        { "field": "product_model",     "old": "...211",     "new": "...462" }
      ]
    }
  ]
}
```

**错误**：
- `q` 缺失或为空 → `400 { ok: false, msg: "缺少查询参数" }`
- 数据库异常 → `500 { ok: false, msg: "..." }`

不返回 404，统一用 `found` 字段标识"查无此货号"，前端判断更顺。

## 聚合算法

```
events_by_barcode(barcode):
    rows = SELECT * FROM stockpile_changes
           WHERE product_barcode = ?
           ORDER BY created_at DESC

    groups = []
    current = None
    for row in rows:
        if current is None:
            current = new_event(row)
        elif (current.at - row.created_at).seconds <= 5:
            current.changes.append(row)
            # source / change_type 取组内首条（最新一条）
        else:
            groups.append(current)
            current = new_event(row)
    if current: groups.append(current)
    return groups
```

聚合窗口为 **5 秒**（基于实际数据间隔分布）。同事件内的 `source` 与 `change_type` 取组内最新一条（DESC 排序下即首条）。

## UI 设计

```
┌─ 📜 货号历史 ─────────────────────────────────────┐
│ [输入条码或型号______________]  [查询]  [清空]     │
├───────────────────────────────────────────────────┤
│ 【当前状态】                                       │
│   型号: 10024     条码: 5828079100248              │
│   库位: A22-04-04  状态: 在架                      │
│   来源: scan_import   最后更新: 2026-04-27 12:43   │
├───────────────────────────────────────────────────┤
│ 【历史时间线】 共 4 次操作                         │
│                                                    │
│  ● 2026-04-27 12:43  scan_import     [update]     │
│     库位  A22-04-04 → 空                           │
│     型号  ...211 → ...462                          │
│                                                    │
│  ● 2026-04-27 12:35  user_correction [update]     │
│     库位  空 → A22-04-04                           │
│  ...                                               │
└───────────────────────────────────────────────────┘
```

**状态文案映射**：
- `is_active=true` → "在架"
- `is_active=false` → "下架"
- `source=scan_import` → "扫描导入"
- `source=user_correction` → "手动修正"
- `source=system_export` → "系统导出"

**空值显示**：库位 `""` 显示为"空"。

**未找到状态**：`未找到 "<query>"，请检查型号或条码是否正确`。

**初始状态**（页面刚切过来时）：搜索框 + 提示语"输入型号或条码后查询历史"。

## 测试计划

### 单元测试 `tests/test_history_service.py`

- `test_search_by_model_returns_record`
- `test_search_by_barcode_returns_record`
- `test_search_not_found_returns_none`
- `test_aggregate_same_second_changes_into_one_event`（4 条同秒 → 1 事件）
- `test_aggregate_5_second_boundary`（4s 合并、6s 拆开各一例）
- `test_events_ordered_desc_by_time`
- `test_event_source_and_change_type_use_latest`

### 手测清单

- [ ] `python server.py` 启动无报错
- [ ] A 端 5 个 tab 显示正常
- [ ] "标签 / 查重 / 采购 / 考勤"四个 tab 功能不退化
- [ ] 货号历史 tab 搜已知 barcode → 显示当前 + 时间线
- [ ] 同一货号搜 model → 显示同一结果
- [ ] 搜不存在的 → 显示"未找到"
- [ ] 切到其他 tab 再切回 → 状态保留 / 输入框可清空
- [ ] FAB 抽屉互传仍正常
- [ ] 采购页月度采购总结仍正常
- [ ] `/admin` 访问 404
- [ ] `/stats` 访问 404
- [ ] 浏览器控制台无报错

### 验收命令

```
pytest tests/test_history_service.py -v
scripts/check-standards.ps1   ← 退出码 0
scripts/check-encoding.ps1    ← 退出码 0
```

## 风险 / 已知问题

1. **聚合窗口对未来数据可能不适用**：当前数据中 5-60 秒区间为空。若后续业务出现 30 秒级别的真实独立操作，5 秒窗口将不再合理。届时需要重新分析时间分布。
2. **`stockpile_changes` 索引**：已有 `idx_changes_barcode`，单货号查询毫秒级。无需新增索引。
3. **大变更链**：极端情况下单货号可能有数百条变更（目前最大未知）。第一期不分页，假设单货号变更 < 100；plan 阶段需要再核数据。

## 后续期接续点

- **第 2 期**（扫描历史）：在 "📜 货号历史" tab 内增加二级 tab "📂 扫描批次"，从 `output/{员工}价格标{时间戳}/` 文件夹读取
- **第 3 期**（进出货事件）：新建 `inventory_events` 表，在 tab 内增加"📥 进出货"二级页
- **第 4 期**（销售分析）：在 tab 内增加"📊 分析"二级页

第 2-4 期均不影响第 1 期已落地的 schema 与 API。

# 员工月度考勤 — 设计文档

**日期**：2026-04-23
**分支**：`feature/attendance`
**目标**：按月手工录入员工每日上下班时间，自动计算工作天数，月底可导出 PDF / CSV。

---

## 1. 使用场景

每月初（通常第二个月 1–5 日），管理员打开"考勤"页，选员工 + 上月月份，在月度网格中逐日录入上/下班时间。周日自动按 1.0 天计；非周日且未录入视为缺勤。月底可下载 PDF 报表和 CSV。

---

## 2. 工作时长规则

- **标准一天**：09:30 – 20:00 = 10.5 小时 = 1.0 天
- **部分工时**：`day_fraction = min(actual_hours / 10.5, 1.0)`，封顶 1.0（超时不累加）
- **周日**：固定 1.0 天，不受录入影响（UI 锁定，展示"自动"）
- **缺勤**：非周日且未录入时间 → 0 天，单独计数

### 计算示例

| 日期 | 星期 | 上班 | 下班 | 实际小时 | 天数 | 状态 |
|------|------|------|------|----------|------|------|
| 04-01 | 三 | 09:30 | 20:00 | 10.5 | 1.00 | 正常 |
| 04-03 | 五 | 09:30 | 15:30 | 6.0 | 0.57 | 正常 |
| 04-04 | 六 | — | — | — | 0 | 缺勤 |
| 04-05 | 日 | 自动 | 自动 | — | 1.00 | 周日 |
| 04-10 | 五 | 09:30 | 21:00 | 11.5 | 1.00 | 封顶 |

---

## 3. 数据模型

### 目录结构

```
attendance/
├── employees.json         # 全局员工列表
└── 2026-04.json           # 每月一份考勤数据
```

### `employees.json`

```json
[
  { "id": "e001", "name": "小王", "created_at": "2026-04-01T09:00:00" }
]
```

**id 生成策略**：`"e" + 3 位递增数字`，取 `employees.json` 现有最大数字 + 1。删除后 id 不复用。

### `YYYY-MM.json`

```json
{
  "e001": {
    "2026-04-01": { "start": "09:30", "end": "20:00" },
    "2026-04-03": { "start": "09:30", "end": "15:30" }
  }
}
```

**规则**：
- 周日不存（计算时自动 1.0）
- 未出现的非周日日期 = 缺勤
- 删除员工：从 `employees.json` 移除，历史月份数据保留但 UI 默认不显示

---

## 4. 后端设计

### 模块划分

| 文件 | 职责 |
|------|------|
| `attendance_service.py` | 员工 CRUD + 月度 CRUD + summary 计算 |
| `attendance_report_service.py` | PDF + CSV 生成 |
| `routes_attendance.py` | HTTP 路由（blueprint）|

**拆分依据**：避免 `attendance_service.py` 超 250 行；后续扩展 Excel/邮件报表时不污染核心逻辑。

### 常量

```python
STANDARD_START = "09:30"
STANDARD_END   = "20:00"
STANDARD_HOURS = 10.5
MONTH_WINDOW   = 12   # 月份下拉列出当前月 + 过去 12 个月（共 13 项）
```

### `attendance_service.py` 对外 API

| 函数 | 签名 | 说明 |
|------|------|------|
| `list_employees()` | `() -> list[dict]` | 返回活跃员工 |
| `create_employee(name)` | `(str) -> dict` | 新建，返回 `{id, name, created_at}` |
| `delete_employee(employee_id)` | `(str) -> None` | 从 employees.json 移除 |
| `set_day(employee_id, date, times)` | `(str, str, dict) -> None` | 写入/覆盖，`times={"start","end"}` |
| `clear_day(employee_id, date)` | `(str, str) -> None` | 删除一天 |
| `compute_summary(employee_id, month)` | `(str, str) -> dict` | 返回 summary + 明细 |

`month` 由 `date[:7]` 派生，不作为独立参数（避免 ≥4 位置参数）。

### `compute_summary` 返回结构

```python
{
  "worked_days": 27.3,          # 累计天数（浮点）
  "absent_days": 2,             # 缺勤天数
  "total_workdays": 28,         # 总工作日（= month_days - absent_days）
  "detail": [
    {
      "date": "2026-04-01",
      "weekday": "三",
      "start": "09:30",
      "end": "20:00",
      "day_fraction": 1.00,
      "status": "normal"        # normal | absent | sunday
    },
    ...
  ]
}
```

### `attendance_report_service.py` 对外 API

| 函数 | 签名 | 说明 |
|------|------|------|
| `build_pdf(month)` | `(str) -> bytes` | 全员月度 PDF |
| `build_csv(month)` | `(str) -> bytes` | 全员月度 CSV（UTF-8 BOM） |

PDF 复用 `monthly_summary_service._register_font()` 的字体加载方式（考虑是否抽取公用字体模块，如果只重复一次先不抽）。

### 路由（blueprint 前缀 `/attendance`）

| Method | Path | Body / 说明 |
|--------|------|-------------|
| GET | `/employees` | 员工列表 |
| POST | `/employees` | `{name}` |
| DELETE | `/employees/<id>` | — |
| GET | `/month/<employee_id>/<month>` | 返回 `compute_summary` |
| POST | `/day/<employee_id>/<date>` | `{start, end}` |
| DELETE | `/day/<employee_id>/<date>` | — |
| GET | `/pdf/<month>` | 下载 PDF |
| GET | `/csv/<month>` | 下载 CSV |

**错误契约**：`{"ok": bool, "msg"?: str, ...data}` 与现有路由一致。

---

## 5. 前端设计

### 导航与页面

- nav 新增"考勤"项，对应 `#pageAttendance`
- 页面模板：新建 `templates/attendance.html` 或复用 `admin.html` 加 section（按现有 purchase 页面注入方式走）

### 文件

```
static/js/attendance.js
static/css/attendance.css
```

### 页面布局

```
┌─ 顶部栏 ─────────────────────────────────────────────────┐
│ 月份 [2026-04 ▼]  员工 [小王 ▼] [+新建] [删除员工]      │
│ 累计 27.3 天 │ 缺勤 2 天 │ 总工作日 28                  │
│                          [下载 PDF] [下载 CSV]           │
├─ 月度表格 ───────────────────────────────────────────────┤
│ 日期   星期  上班       下班       天数   状态          │
│ 04-01  三   [09:30]    [20:00]    1.00   ✓              │
│ 04-04  六   [  —  ]    [  —  ]    0.00   缺勤           │
│ 04-05  日   自动（周日）          1.00   🔒              │
│ ...                                                       │
└──────────────────────────────────────────────────────────┘
```

### 关键函数（每个 ≤ 60 行）

| 函数 | 职责 |
|------|------|
| `init()` | 注入 HTML + 绑定事件 |
| `loadEmployees()` | 拉列表填下拉 |
| `createEmployee()` | prompt 取名 → POST → 刷新 |
| `deleteEmployee()` | confirm → DELETE → 刷新 |
| `loadMonth()` | 拉当前员工 + 月份的 summary + 明细 |
| `renderGrid(detail)` | 渲染表格每行 |
| `onCellChange(date, field, value)` | 时间输入变更 → 保存 → 局部重算 |
| `downloadPdf()` / `downloadCsv()` | 下载 |

### 交互规则

- 时间用 `<input type="time">`（浏览器原生）
- 触发保存：`change` 事件（不是 `input`，避免每按一下都请求）
- 周日：只读灰底 + "自动 1.0"
- 缺勤行：淡灰 + "缺勤" 标签
- 单次保存仅一个 `POST /day/...`，用响应中的 summary 即时更新顶部三个累计数字
- 前端合法性校验：`end > start`，否则拒绝 + 提示

---

## 6. 错误与边界

| 场景 | 处理 |
|------|------|
| `end ≤ start` | 前端拒绝，提示"下班时间必须晚于上班时间" |
| 月份跨度 | 月份下拉仅列当前月 + 过去 12 个月 |
| 并发编辑 | 不考虑（单人场景） |
| 文件缺失 | 自动新建空结构 |
| 员工重名 | 允许（用 id 去重，不限名字） |
| 删员工后查旧月份 | 旧 JSON 保留数据，UI 按 id 未知 → 显示"已删除员工"或隐藏 |

---

## 7. 测试计划

| 模块 | 测试项 |
|------|--------|
| `day_fraction` | 正常 / 部分 / 封顶 / `end ≤ start` 抛异常 |
| `compute_summary` | 含周日自动、缺勤、混合、月份边界 |
| 员工 CRUD | 创建 / 删除 / id 唯一性 |
| 月度 CRUD | `set_day` / `clear_day` / 空月份 |
| PDF / CSV | 只验证不抛异常 + 返回非空 bytes |

---

## 8. 与现有代码的关系

- **复用**：PDF 字体加载逻辑可能抽取到 `fonts.py` 供 `monthly_summary_service` + `attendance_report_service` 共用（第一次复用时再抽，避免过度设计）
- **不影响**：不改动采购、月度采购总结、任务、查询等现有模块
- **注册**：`routes.py` 加一行 `app.register_blueprint(attendance_bp)`

---

## 9. 不做（YAGNI）

- 多班制（午休扣除、中间打卡）
- 员工权限 / 登录
- 打卡机 / Excel 批量导入
- 加班时长单独栏（按规则 3 封顶 1.0）
- 跨月审计 / 历史对比图表
- 节假日默认规则（春节等）

# 考勤请假功能 设计

**日期：** 2026-04-25
**状态：** 已确认
**关联：** 在现有 attendance 系统上增量扩展（参考 2026-04-23-attendance-design.md）

## 目标

为考勤系统增加"请假"维度：员工某天可以请假整天 / 半天 / 自定义小时数。请假**不计入缺勤**，且**独立累计**，不混入 worked_days。

## 设计决策

1. **计算方式**：方案 B —— 请假独立累计，不并入 day_fraction
2. **录入粒度**：小时为底层单位；UI 提供"全天 / 半天 / 自定义"三种快捷输入
3. **状态显示**：只要 leave_hours > 0 → 状态 = "请假 Xh"（覆盖 normal/absent；周日/节假日/特殊日仍优先）
4. **当天是否同时有上班时间**：允许（leave_hours 与 start/end 是独立字段），但 UI 不主动鼓励
5. **缺勤判定**：只要当天有请假记录 → 不算缺勤（简单规则）

## 优先级

`周日 > 节假日 > 特殊日 > 请假 > 常规录入 > 缺勤`

请假优先于常规和缺勤；周日/节假日/特殊日仍按原规则覆盖。

## 数据模型

### 新文件：`attendance_data/<month>/leaves.json`

结构与 attendance.json 平行：

```json
{
  "e001": {
    "2026-04-15": 10.5,
    "2026-04-20": 5.25
  }
}
```

值为请假小时数（float）。

### compute_summary 输出新增字段

每个 detail row 新增：
- `leave_hours: float`（默认 0.0）

summary 顶层新增：
- `leave_hours_total: float`（当月总请假小时）
- `leave_days_equivalent: float`（折算天数 = leave_hours_total / 10.5，特殊日按特殊日时长换算需另计——简化：统一按 10.5 折算用于显示）

### 状态枚举扩展

新增状态：`"leave"`（中文：请假）

判定优先级（在 compute_summary 中）：
1. Sunday → `sunday`
2. Holiday → `holiday`
3. Special day（无论是否有 leave）→ `special` / `special_absent`
4. **leave_hours > 0** → `leave`
5. 有 start/end → `normal`
6. 否则 → `absent`

## API

### 新增路由

- `GET /attendance/leaves/<month>` → `{ok, leaves: {emp_id: {date: hours}}}`
- `POST /attendance/leave/<employee_id>/<date>` body `{hours: float}` → 返回更新后 summary
- `DELETE /attendance/leave/<employee_id>/<date>` → 返回更新后 summary

## 前端

### 月度网格新增

每行新增"请假"列：
- 显示当天 leave_hours（无则空）
- 操作按钮："请假"——点击弹出快捷选择：全天 / 半天 / 自定义小时
- 已有请假时按钮变为"取消请假"

行底色：leave 状态用蓝色（`#1e3a8a` 系，区别于绿色节假日 / 橙色特殊日）。

### 总览统计区

在现有"累计天数 / 缺勤天数 / 总工作日 / 本月天数"后新增：
- "请假：X.X 小时（约 Y.Y 天）"

## PDF / CSV

### PDF
- 总览表新增列："请假天数"（折算天数，1 位小数）
- 每员工详情表新增列："请假"（小时，空则 "—"）

### CSV
表头新增 "请假小时" 列，放在"天数"和"状态"之间。

## 测试

新增 `TestLeaves` 测试类，覆盖：
1. 空状态：list_leaves 返回 {}
2. 增删：set_leave / clear_leave
3. 请假不计缺勤：set_leave 后 absent_days 减少
4. 请假独立累计：worked_days 不受影响
5. leave_hours_total 累计正确
6. 优先级：节假日覆盖请假；请假覆盖普通缺勤
7. 同一天可同时有 leave_hours 和打卡（worked_days 仅算打卡部分）

## 不做的事（YAGNI）

- 不做请假审批流程
- 不区分病假/事假/年假类型（一个 hours 字段统一）
- 不做请假上限校验
- 不做特殊日上请假按特殊日标准换算（统一按 10.5h 换算天数）

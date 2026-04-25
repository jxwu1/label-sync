# 考勤请假功能 实施计划

**Goal:** 在 attendance 系统上增加请假维度（小时为单位，独立累计，不计缺勤）

**Architecture:** 模仿现有 special_days 模式 —— 新增 `leaves.json` 月度存储 + service 函数 + 路由 + 前端列。compute_summary 增加 leave 分支。

**Tech Stack:** 同现有（Flask + ReportLab + 原生 JS）

---

## Task 1: service 层 —— leaves 存储 + CRUD

**Files:** Modify `attendance_service.py`, `tests/test_attendance_service.py`

- [ ] 新增 `_leaves_path(month)`、`list_leaves(month)`、`set_leave(emp_id, date, hours)`、`clear_leave(emp_id, date)`
- [ ] 测试：空 / 增 / 改 / 删 / hours <= 0 抛 ValueError

## Task 2: compute_summary 集成 leave

**Files:** Modify `attendance_service.py`, `tests/test_attendance_service.py`

- [ ] detail row 新增 `leave_hours` 字段
- [ ] summary 顶层新增 `leave_hours_total`、`leave_days_equivalent`（= total/10.5）
- [ ] 优先级：sunday > holiday > special > leave > normal > absent
- [ ] leave 状态：当 leave_hours > 0 且当天非 sunday/holiday/special → status="leave"
- [ ] absent 判定：leave_hours > 0 不算缺勤；worked_days 仍按打卡算（不并入 leave）
- [ ] 测试：请假不计缺勤 / 不影响 worked_days / 节假日覆盖请假 / 请假覆盖普通缺勤 / 同天打卡+请假

## Task 3: 路由

**Files:** Modify `routes_attendance.py`

- [ ] `GET /attendance/leaves/<month>`
- [ ] `POST /attendance/leave/<emp_id>/<date>` body `{hours}`
- [ ] `DELETE /attendance/leave/<emp_id>/<date>`
- [ ] 校验 hours > 0；返回更新后 summary

## Task 4: 前端 —— grid 列 + 操作

**Files:** Modify `static/js/attendance.js`, `static/css/attendance.css`

- [ ] grid 新增"请假"列：显示小时数 + 操作按钮
- [ ] 按钮逻辑：未请假 → 显示"请假" → click 弹快捷选择（全天 / 半天 / 自定义）；已请假 → 显示"取消"
- [ ] leave 行底色：`tr.leave td { background:#1e3a8a; color:#bfdbfe }`
- [ ] 总览统计区追加"请假：X.X 小时（约 Y.Y 天）"
- [ ] 状态列显示"请假 Xh"

## Task 5: PDF/CSV

**Files:** Modify `attendance_report_service.py`

- [ ] PDF overview 新增"请假天数"列（折算）
- [ ] PDF 详情表新增"请假"列
- [ ] CSV 表头加"请假小时"
- [ ] `_STATUS_CN["leave"] = "请假"`

## Task 6: 手动验证 + commit + push

- [ ] 启动 Flask，请假快捷按钮全部测试
- [ ] PDF / CSV 下载验证
- [ ] commit & push & merge to main

# 企业微信考勤导入 — 设计

**Date:** 2026-05-28
**Status:** Approved
**Scope:** 单个功能模块,一个实现计划即可覆盖。

## 目标

从企业微信导出的「打卡时间记录」xlsx 一键读取并填写考勤,只覆盖用户负责的
百货城工作组。导入按月重复执行,首次需一次性绑定/忽略账号,之后全自动。

`(action, verify)`:
- action: 实现 xlsx → 考勤库 的导入流程(解析 + 预览 + 绑定/忽略 + 应用)
- verify: 解析层 / 计划层 / 路由三段 单测全绿;真实导出文件跑通 preview→apply 后,
  对应员工当月已填天数与文件一致,非本组/单次打卡/已有天不被写入。

## 源文件格式(`打卡时间记录` sheet)

矩阵布局,一行一员工,列为当月每一天:

- 行 0-1:标题 + `统计时间:05-01 ～ 05-27`(只有 MM-DD,无年份)
- 行 2:分组表头(`姓名` / `账号` / `基础信息` / `打卡时间记录`)
- 行 3:列头。基础信息 = `部门`/`职务`/`工号`;之后每列形如 `1\n星期五`(day-of-month)
- 行 4+:数据。每个单元格是当天的打卡时刻,用 `、` 分隔:
  - `09:21、20:00` → start 09:21 / end 20:00
  - `09:22、09:22、20:00` → 去重后 start=最早 end=最晚
  - `09:21、09:21、20:00(管理员校准)` → 先剥离 `（…）`/`(…)` 注释再解析
  - `--` 或空 → 无记录(周日整列也是 `--`)
  - 单个时间(`09:40` / `17:35`)→ 凑不出 start+end

注意:本文件**没有 `所属规则` 列**,部门也不是干净的百货城过滤条件
(张婧雯属希腊销售部但班次不同,方茹属采购部)。因此**不用工作组过滤**,
改用「账号绑定即过滤」。

## 关键决策

| 议题 | 决策 |
|---|---|
| 身份匹配 | 企业微信`账号`为稳定唯一 join key;在 `Employee` 加 `wecom_account` 列 |
| 账号是否露出前端 | 否。`wecom_account` 纯后台 join key,UI 任何地方只显示员工姓名 |
| 工作组过滤 | 不用 `所属规则`。**未绑定账号的行自动跳过**,绑定即过滤 |
| 非本组的人(噪音) | 绑定界面提供「忽略(非本组)」动作,记入忽略清单,以后预览不再出现 |
| 结束时间 | 用文件里真实最晚打卡(本文件已含下班时刻) |
| 单次打卡的天 | 跳过 + 进「需手动」清单,不猜 |
| 覆盖策略 | 只填空白天:系统已有考勤或请假的天一律跳过,不覆盖手填修正 |
| 年份/月份 | 从文件名(`20260501`)+`统计时间`推导,UI 让用户确认目标月 |

## 架构

### 1. 数据模型(`app/models.py` + alembic)
- `Employee.wecom_account`:`TEXT NULL`,后台 join key。一员工 1:1 一账号。
- 忽略账号清单:不属于任何员工,存为一条 `SystemSetting`(key 如
  `wecom_ignored_accounts`,value = JSON list of account strings)。**不建新表**。

### 2. 解析层 `app/services/attendance_import.py`(纯函数,无 DB)

- `parse_cell(text) -> ("ok", start, end) | ("single", t) | ("empty",)`
  - 剥离 `（…）`/`(…)` → 按 `、`(兼容 `,`/`，`)拆 → 正则抓 `\d{1,2}:\d{2}` → 去重排序
  - 0 个 → empty;1 个 → single;≥2 → start=min end=max
- `parse_period(period_text, filename) -> (year, month)`:文件名优先取年,
  period 取月;无法解析时返回 None 让 UI 兜底。
- `parse_workbook(xlsx_bytes, filename) -> ParsedFile`
  - `ParsedFile`: `month`(YYYY-MM) + `rows: list[{account, name, days: {date: ("ok",s,e)|("single",t)}}]`

### 3. 计划层(`attendance_import.py`,需要 DB 只读)

`build_plan(parsed, month) -> ImportPlan`:
- 读 `Employee.wecom_account` 映射、忽略清单、`load_month(month)`(已有考勤)、
  `list_leaves(month)`。
- 对每行账号分类:
  - 已绑定 → 逐天归类:`to_write`(空白且 ok)/`skip_existing`(已有考勤或请假)/
    `skip_single`(单次打卡,进需手动)/`skip_empty`
  - 已忽略 → 不出现
  - 未知 → 进 `unbound`,附按姓名精确匹配的 `suggested_employee_id`(可空)
- 返回:`matched`(每员工 to_write 天列表 + 各跳过计数)、`unbound`(account+name+建议)、
  `needs_manual`(单次打卡的 员工×日期)、汇总计数。

### 4. 路由(`app/routes/attendance.py`,前缀 `/attendance/import`)
- `POST /attendance/import/preview` — multipart 上传 xlsx。解析 + build_plan,返回预览 JSON。**不落库**。
- `POST /attendance/import/bind` — body `{account, employee_id}`,写 `Employee.wecom_account`。
- `POST /attendance/import/ignore` — body `{account}`,加入忽略清单。
- `POST /attendance/import/apply` — multipart 重传 xlsx + `{month}`,只对 `to_write` 天调 `set_day`。返回 `{written, skipped_*}`。
  - 实现取舍:apply 重新解析上传文件 + build_plan(保证落库前用最新绑定/忽略状态),
    只写 `to_write`,避免预览与应用之间状态漂移。

### 5. 前端(考勤页弹窗,`templates/` + `static/js/`)
- "导入企业微信"按钮 → 选文件上传 → 预览弹窗:
  - 顶部:目标月份(可改)+「已匹配 X 人 / 待绑定 Y 人 / 需手动 Z 天」
  - 待绑定区:每个**姓名**一行,配 [员工下拉(默认选中建议)] + [忽略] 按钮;选完即调 bind/ignore 并重算预览
  - 需手动区:列出 员工×日期(单次打卡),提示手动补
  - 底部:确认 → apply → toast 写入/跳过计数,刷新当前月视图
- 全程不显示账号字符串。

## 测试

- 解析层单测:多次打卡 / 注释剥离 / 单次 / `--` / 迟到 / 表头日期推导 / period+filename 年份推导。
- 计划层单测:绑定过滤、忽略过滤、fill-blank-only(已有考勤/请假跳过)、单次进 needs_manual。
- 路由集成测:preview→bind→ignore→apply 三段;apply 只写空白天。
- 真实文件冒烟:用 `打卡时间记录_20260501-20260527.xlsx` 跑通,核对某员工当月填写结果。

## 不做(YAGNI)
- 不解析第二个 sheet / 不依赖 `所属规则` 列。
- 不自动建员工(新人走现有手动建档 + 绑定)。
- 不做跨月文件;一次一个月。

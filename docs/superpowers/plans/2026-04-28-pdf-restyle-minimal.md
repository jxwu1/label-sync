# PDF 极简留白风重构 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development.

**Goal:** 把 `attendance_report_service.py` 生成的两份 PDF（考勤报表 + 工资单）重新做成「极简留白风」（方向 A）。

**Architecture:** 单文件重构。不改任何接口，不改 schema，不改 routes。仅 ReportLab 的 TableStyle / Paragraph 渲染逻辑改写。Python 侧 4 个 pytest smoke tests 必须仍然通过。

**Tech Stack:** ReportLab（已在用），Python 3。

**已确认设计（来自对话）：**
- 方向：A · 极简留白风（无完整网格、thead 一根 1.5pt 粗线、行间 0.3pt 浅灰线、标题大字左对齐）
- Q1：状态列 = **符号 + 文字**（`● 正常` / `✕ 缺勤` / `○ 周日` / `△ 节假日` / `◐ 特殊日` / `◐ 请假` / `✕ 特殊日缺勤`）
- Q2：**不加合计行**（保持极简）
- Q3：工资单的"实际工资 / 应付工资"列 = **空白 + 一条 0.5pt 横线**（限定手写位置）

**色调：**
- 标题：黑 `#111827`
- meta 副标题：灰 `#9ca3af`
- thead 文字 + 底线：深灰 `#1f2937`
- 行间分隔：浅灰 `#e5e7eb` 0.3pt
- 状态符号配色：normal `#059669` / absent `#b91c1c` / leave `#b45309` / special `#6d28d9` / sunday/holiday `#6b7280`

**Mockup 参考：** `C:\Users\jxwu2002\Desktop\attendance_pdf_mockup.html` 方向 A 的 3 张页面。

---

## File Structure

| 文件 | 操作 | 说明 |
|---|---|---|
| `attendance_report_service.py` | 改写 | 添加 `_STATUS_DISPLAY` 映射 + 颜色映射；重写 `_build_overview` / `_build_employee_block` / `build_payroll_pdf` 的 TableStyle；title/meta 用新 Paragraph style；状态列改为 colored Paragraph |
| `tests/test_attendance_report_service.py` | 不动 | 4 个 smoke tests 已覆盖"PDF 非空 / 空月也能跑"，对样式无要求 |
| `attendance_service.py` / `routes_attendance.py` | 不动 | 接口完全不变 |

---

## Verification Strategy

1. **后端 pytest 必过**：`pytest tests/test_attendance_report_service.py -v` 全 PASS。
2. **生成真 PDF 用眼检查**：写一个一次性脚本（仅本地跑、不入库），用真实数据库生成两份 PDF 到桌面，用户人工对比 mockup A。
3. **回归**：考勤页 UI 上的"下载 PDF / 工资单 PDF"两个按钮在浏览器仍能正常下载（之前 Task 5 已验证流程，本次只看 PDF 内容）。

---

## Task 1: 添加状态显示常量 + 重构 _build_overview 和 _build_employee_block

**Files:**
- Modify: `attendance_report_service.py`

- [ ] **Step 1：在文件顶部 `_STATUS_CN` 字典之后追加新常量**

定位锚点：当前 `_STATUS_CN` 定义在文件第 25-29 行。在它的右花括号 `}` 后面加一个空行，然后追加：

```python
# 状态符号 + 文字 + 配色（极简风 PDF 用）
_STATUS_DISPLAY = {
    "normal":         ("● 正常",      "#059669"),
    "absent":         ("✕ 缺勤",      "#b91c1c"),
    "sunday":         ("○ 周日",      "#6b7280"),
    "holiday":        ("△ 节假日",    "#6b7280"),
    "special":        ("◐ 特殊日",    "#6d28d9"),
    "special_absent": ("✕ 特殊日缺勤", "#b91c1c"),
    "leave":          ("◐ 请假",      "#b45309"),
}

# 通用极简风颜色
_C_TITLE   = colors.HexColor("#111827")
_C_META    = colors.HexColor("#9ca3af")
_C_HEAD    = colors.HexColor("#1f2937")
_C_LINE    = colors.HexColor("#e5e7eb")
```

- [ ] **Step 2：在文件顶部追加共享样式辅助函数**

在 `_register_font()` 函数之前添加：

```python
def _make_title_paragraph(text: str, font_name: str):
    """大标题：左对齐、加粗、深黑。"""
    from reportlab.lib.enums import TA_LEFT
    styles = getSampleStyleSheet()
    s = styles["Title"].clone("attn_title_minimal")
    s.fontName = font_name
    s.fontSize = 16
    s.leading = 20
    s.alignment = TA_LEFT
    s.textColor = _C_TITLE
    s.spaceAfter = 2
    return Paragraph(text, s)


def _make_meta_paragraph(text: str, font_name: str):
    """副标题/meta：左对齐、灰色小字。"""
    from reportlab.lib.enums import TA_LEFT
    styles = getSampleStyleSheet()
    s = styles["Normal"].clone("attn_meta_minimal")
    s.fontName = font_name
    s.fontSize = 9
    s.alignment = TA_LEFT
    s.textColor = _C_META
    s.spaceAfter = 12
    return Paragraph(text, s)


def _make_status_cell(status: str, font_name: str):
    """状态单元格：彩色符号+文字 Paragraph。未知状态用默认中灰。"""
    label, color = _STATUS_DISPLAY.get(status, (_STATUS_CN.get(status, status), "#6b7280"))
    styles = getSampleStyleSheet()
    s = styles["Normal"].clone("attn_status_cell")
    s.fontName = font_name
    s.fontSize = 9
    s.textColor = colors.HexColor(color)
    s.alignment = 1  # TA_CENTER
    return Paragraph(label, s)


def _minimal_table_style(font_name: str, header_row: int = 0, font_size: int = 9):
    """极简风通用 TableStyle：无网格，thead 1.5pt 底线，行间 0.3pt 浅灰线。"""
    return TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), font_name),
        ("FONTSIZE", (0, 0), (-1, -1), font_size),
        ("FONTSIZE", (0, header_row), (-1, header_row), font_size + 1),
        ("FONTNAME", (0, header_row), (-1, header_row), font_name),
        ("TEXTCOLOR", (0, header_row), (-1, header_row), _C_HEAD),
        ("LINEBELOW", (0, header_row), (-1, header_row), 1.5, _C_HEAD),
        ("LINEBELOW", (0, header_row + 1), (-1, -1), 0.3, _C_LINE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ])
```

- [ ] **Step 3：重写 `_build_overview`**（约现行 48-83 行整体替换）

```python
def _build_overview(month: str, employees: list, summaries: dict, font_name: str) -> list:
    name_style = getSampleStyleSheet()["Normal"].clone("attn_name_link")
    name_style.fontName = font_name
    name_style.fontSize = 10
    elements = [
        _make_title_paragraph(f"{month} 月度考勤总览", font_name),
        _make_meta_paragraph(f"共 {len(employees)} 名员工", font_name),
    ]
    rows = [_OVERVIEW_HEADER]
    for idx, emp in enumerate(employees, start=1):
        s = summaries[emp["id"]]
        name_link = (
            f'<link href="#{_employee_anchor(emp["id"])}" color="#4f46e5">'
            f'<u>{idx}. {emp["name"]}</u></link>'
        )
        rows.append([
            Paragraph(name_link, name_style),
            f"{s['month_days']}",
            f"{s['total_workdays']}",
            f"{s['absent_days']}",
            f"{s.get('leave_days_equivalent', 0):.1f}",
            f"{s['worked_days']}",
        ])
    table = Table(rows, colWidths=[40 * mm, 22 * mm, 22 * mm, 22 * mm, 22 * mm, 22 * mm])
    style = _minimal_table_style(font_name, header_row=0, font_size=10)
    style.add("ALIGN", (1, 0), (-1, -1), "RIGHT")
    style.add("ALIGN", (0, 0), (0, 0), "LEFT")
    table.setStyle(style)
    elements.append(table)
    return elements
```

- [ ] **Step 4：重写 `_build_employee_block`**（约现行 102-129 行整体替换）

```python
def _build_employee_block(emp: dict, summary: dict) -> list:
    anchor_para = Paragraph(f'<a name="{_employee_anchor(emp["id"])}"/>', getSampleStyleSheet()["Normal"])
    title = _make_title_paragraph(emp["name"], _FONT_NAME)
    meta_text = (
        f'{summary.get("month", "")} · 累计 {summary["worked_days"]} 天 · '
        f'缺勤 {summary["absent_days"]} 天 · 请假 {summary.get("leave_hours_total", 0)}h'
    )
    meta = _make_meta_paragraph(meta_text, _FONT_NAME)

    rows = [_PDF_TABLE_HEADER]
    for r in summary["detail"]:
        leave_h = r.get("leave_hours", 0) or 0
        rows.append([
            r["date"],
            r["weekday"],
            r["start"] or "—",
            r["end"] or "—",
            f"{r['day_fraction']:.2f}",
            _format_leave_pdf(r) if leave_h else "—",
            _make_status_cell(r["status"], _FONT_NAME),
        ])
    table = Table(rows, colWidths=[26 * mm, 12 * mm, 18 * mm, 18 * mm, 14 * mm, 22 * mm, 26 * mm])
    style = _minimal_table_style(_FONT_NAME, header_row=0, font_size=9)
    # 列对齐：date/weekday/start/end/状态 居中；天数 右；请假 左
    style.add("ALIGN", (0, 0), (4, -1), "CENTER")
    style.add("ALIGN", (4, 1), (4, -1), "RIGHT")  # 天数列覆盖为右对齐
    style.add("ALIGN", (5, 0), (5, -1), "LEFT")
    style.add("ALIGN", (6, 0), (6, -1), "CENTER")
    table.setStyle(style)
    return [anchor_para, title, meta, table, Spacer(1, 10 * mm)]
```

注：`summary` 字典里没有 `month` 键。该字段当前不存在，meta 文案不显示月份就行 — 把 `f'{summary.get("month", "")} · 累计 ...'` 改成 `f'累计 {summary["worked_days"]} 天 · 缺勤 ...'`，去掉前面的 month 引用。

**最终 meta_text 应为：**
```python
    meta_text = (
        f'累计 {summary["worked_days"]} 天 · '
        f'缺勤 {summary["absent_days"]} 天 · '
        f'请假 {summary.get("leave_hours_total", 0)}h'
    )
```

- [ ] **Step 5：跑 pytest**

```bash
python -m pytest tests/test_attendance_report_service.py -v
```

预期：4/4 PASS。

- [ ] **Step 6：Commit**

```bash
git add attendance_report_service.py
git commit -m "refactor(pdf): 考勤报表改为极简留白风（A 方向）"
```

---

## Task 2: 重构 build_payroll_pdf（工资单极简风 + 横线手写位）

**Files:**
- Modify: `attendance_report_service.py`

- [ ] **Step 1：重写 `build_payroll_pdf` 函数**（约现行 135-200 行整体替换）

```python
def build_payroll_pdf(month: str) -> bytes:
    """工资单 PDF：仅总览页，横版 A4，含两列空白工资栏供手填。"""
    _register_font()
    employees = attendance_service.list_employees()

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=landscape(A4),
        topMargin=14 * mm, bottomMargin=14 * mm,
        leftMargin=14 * mm, rightMargin=14 * mm,
    )

    elements = [
        _make_title_paragraph(f"{month} 月度工资单", _FONT_NAME),
        _make_meta_paragraph(f"共 {len(employees)} 名员工 · 实际/应付工资请手填", _FONT_NAME),
    ]

    if not employees:
        empty = getSampleStyleSheet()["Normal"].clone("payroll_empty")
        empty.fontName = _FONT_NAME
        elements.append(Paragraph("暂无员工", empty))
        doc.build(elements)
        return buf.getvalue()

    name_style = getSampleStyleSheet()["Normal"].clone("payroll_name")
    name_style.fontName = _FONT_NAME
    name_style.fontSize = 10

    rows = [_PAYROLL_HEADER]
    for idx, emp in enumerate(employees, start=1):
        s = attendance_service.compute_summary(emp["id"], month)
        leave_h = s.get("leave_hours_total", 0)
        leave_d = s.get("leave_days_equivalent", 0)
        leave_text = f"{leave_h:.2f}h (≈{leave_d:.2f}d)" if leave_h else "—"
        rows.append([
            Paragraph(f"{idx}. {emp['name']}", name_style),
            f"{s['month_days']}",
            f"{s['total_workdays']}",
            f"{s['absent_days']}",
            leave_text,
            f"{s['worked_days']}",
            "",  # 实际工资（横线由 TableStyle 画）
            "",  # 应付工资
        ])

    col_widths = [40 * mm, 22 * mm, 24 * mm, 22 * mm, 30 * mm, 22 * mm, 50 * mm, 50 * mm]
    table = Table(rows, colWidths=col_widths)
    style = _minimal_table_style(_FONT_NAME, header_row=0, font_size=10)
    # 列对齐：员工 左；数字列 右；请假 中
    style.add("ALIGN", (1, 0), (5, -1), "RIGHT")
    style.add("ALIGN", (4, 0), (4, -1), "CENTER")
    style.add("ALIGN", (6, 0), (-1, -1), "CENTER")
    # 工资栏（最后两列）的数据行加 0.5pt 横线占位
    for row_idx in range(1, len(rows)):
        style.add("LINEBELOW", (6, row_idx), (-1, row_idx), 0.5, _C_HEAD)
    table.setStyle(style)
    elements.append(table)

    doc.build(elements)
    return buf.getvalue()
```

注意：`_minimal_table_style` 已经为数据行设置了 LINEBELOW 0.3 浅灰线；上面循环的 LINEBELOW 0.5 深色线会覆盖工资栏两列对应行的底线，让它们看起来比其他行更"实"，便于手写。

- [ ] **Step 2：跑 pytest**

```bash
python -m pytest tests/test_attendance_report_service.py -v
```

预期：4/4 PASS。

- [ ] **Step 3：Commit**

```bash
git add attendance_report_service.py
git commit -m "refactor(pdf): 工资单改为极简留白风 + 工资栏 0.5pt 手写横线"
```

---

## Task 3: 视觉验证 — 生成真 PDF 给用户看

**Files:** 无修改。

- [ ] **Step 1：用现成数据生成两份真 PDF 到桌面**

不写一次性脚本入库，直接用 `python -c` 一次性命令：

```bash
python -c "from attendance_report_service import build_pdf, build_payroll_pdf; import attendance_service; m = attendance_service.list_employees(); month='2026-04'; open(r'C:/Users/jxwu2002/Desktop/preview_attendance.pdf','wb').write(build_pdf(month)); open(r'C:/Users/jxwu2002/Desktop/preview_payroll.pdf','wb').write(build_payroll_pdf(month))"
```

如果当前数据库里 `2026-04` 月没有数据，换个有数据的月份：先列出有员工的，挑任意一个，然后用其月份。如果数据库完全空，PDF 还是会生成（empty 分支），同样能验证布局。

- [ ] **Step 2：等用户人工核对**

用户打开 `preview_attendance.pdf` 和 `preview_payroll.pdf`，对照 mockup A 检查：
- [ ] 标题大字左对齐、下方一行灰色 meta
- [ ] thead 一根 1.5pt 深线、无完整网格、行间淡灰线
- [ ] 状态列彩色符号 + 文字（● 正常 / ✕ 缺勤 / ○ 周日 / △ 节假日 / ◐ 特殊日 / ◐ 请假）
- [ ] 总览页员工名是蓝色下划线链接（点击跳到详情）
- [ ] 工资单"实际工资 / 应付工资"两列每行有一条 0.5pt 横线
- [ ] 中文字体不糊（msyh.ttc 或 NotoSansSC fallback 生效）

- [ ] **Step 3：浏览器回归**

```bash
python server.py
```

考勤页 → 点"下载 PDF" / "下载工资单 PDF" → 文件正常下载、内容与 Step 1 生成的一致。

- [ ] **Step 4：删除桌面上的 preview PDF**

```bash
rm /c/Users/jxwu2002/Desktop/preview_attendance.pdf /c/Users/jxwu2002/Desktop/preview_payroll.pdf
```

- [ ] **Step 5：（可选）若发现微调点（行高、列宽、字号），独立 commit**

```bash
git add attendance_report_service.py
git commit -m "style(pdf): 视觉微调"
```

---

## 完成判据

3 个 Task 全部完成、pytest 全过、用户视觉确认 OK → 任务完成。


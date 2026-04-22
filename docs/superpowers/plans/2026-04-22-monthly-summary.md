# 采购订单月度财务总结 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在采购订单导出前收集财务信息（供应商名、税金、开票日期），按自然月存储，支持补录历史月份，生成 PDF 报表。

**Architecture:** 新增 `monthly_summary_service.py` 处理 JSON 存取和 PDF 生成，`routes_monthly_summary.py` 提供 API。前端在 `purchase.js` 导出前弹出模态框收集数据，页面底部增加月度总结区域。数据以 JSON 文件按月存储在 `monthly_summary/` 目录，保留 6 个月。

**Tech Stack:** Python (reportlab for PDF), Flask Blueprint, vanilla JS

---

## File Structure

| 文件 | 职责 |
|------|------|
| **Create:** `monthly_summary_service.py` | JSON 读写、记录增删、PDF 生成、过期清理 |
| **Create:** `routes_monthly_summary.py` | API 路由 (保存/列表/补录/下载 PDF) |
| **Create:** `tests/test_monthly_summary_service.py` | 服务层单元测试 |
| **Create:** `monthly_summary/` | 数据目录（JSON 文件） |
| **Modify:** `routes.py` | 注册新 blueprint |
| **Modify:** `server.py` | 启动时创建 `monthly_summary/` 目录 + 清理过期数据 |
| **Modify:** `requirements.txt` | 添加 reportlab |
| **Modify:** `static/js/purchase.js` | 导出前模态框 + 月度总结 UI |

---

### Task 1: 安装 reportlab + 更新依赖

**Files:**
- Modify: `requirements.txt`

- [ ] **Step 1: 添加 reportlab 到 requirements.txt**

```
flask
pandas
openpyxl
reportlab
```

- [ ] **Step 2: 安装依赖**

Run: `pip install reportlab`
Expected: Successfully installed reportlab

- [ ] **Step 3: Commit**

```bash
git add requirements.txt
git commit -m "chore: 添加 reportlab 依赖"
```

---

### Task 2: monthly_summary_service.py — JSON 存取

**Files:**
- Create: `monthly_summary_service.py`
- Create: `tests/test_monthly_summary_service.py`

- [ ] **Step 1: Write failing tests for JSON storage**

```python
# tests/test_monthly_summary_service.py
import json
import shutil
import unittest
from datetime import date
from pathlib import Path

import monthly_summary_service as svc

_TEST_DIR = Path(__file__).resolve().parent / "_test_monthly_summary"


class TestSaveRecord(unittest.TestCase):
    def setUp(self):
        _TEST_DIR.mkdir(exist_ok=True)
        svc._SUMMARY_DIR = _TEST_DIR

    def tearDown(self):
        shutil.rmtree(_TEST_DIR, ignore_errors=True)

    def test_save_creates_file_and_appends_record(self):
        record = svc.save_record(
            supplier_name="ABC贸易",
            total_price=12000.0,
            tax=1560.0,
            invoice_date="2026-04-15",
            month="2026-04",
        )
        self.assertEqual(record["supplier_name"], "ABC贸易")
        self.assertAlmostEqual(record["total_price"], 12000.0)
        self.assertAlmostEqual(record["tax"], 1560.0)
        self.assertAlmostEqual(record["total_with_tax"], 13560.0)
        self.assertEqual(record["invoice_date"], "2026-04-15")

        records = svc.load_records("2026-04")
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["supplier_name"], "ABC贸易")

    def test_save_appends_multiple_records(self):
        svc.save_record("A", 100.0, 10.0, "2026-04-01", "2026-04")
        svc.save_record("B", 200.0, 20.0, "2026-04-02", "2026-04")
        records = svc.load_records("2026-04")
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["supplier_name"], "A")
        self.assertEqual(records[1]["supplier_name"], "B")

    def test_load_returns_empty_for_nonexistent_month(self):
        records = svc.load_records("2099-01")
        self.assertEqual(records, [])


class TestListMonths(unittest.TestCase):
    def setUp(self):
        _TEST_DIR.mkdir(exist_ok=True)
        svc._SUMMARY_DIR = _TEST_DIR

    def tearDown(self):
        shutil.rmtree(_TEST_DIR, ignore_errors=True)

    def test_lists_months_sorted_descending(self):
        svc.save_record("A", 100.0, 10.0, "2026-02-01", "2026-02")
        svc.save_record("B", 200.0, 20.0, "2026-04-01", "2026-04")
        svc.save_record("C", 300.0, 30.0, "2026-03-01", "2026-03")
        months = svc.list_months()
        self.assertEqual(months, ["2026-04", "2026-03", "2026-02"])


class TestCleanupExpired(unittest.TestCase):
    def setUp(self):
        _TEST_DIR.mkdir(exist_ok=True)
        svc._SUMMARY_DIR = _TEST_DIR

    def tearDown(self):
        shutil.rmtree(_TEST_DIR, ignore_errors=True)

    def test_removes_files_older_than_six_months(self):
        old_file = _TEST_DIR / "2025-08.json"
        old_file.write_text("[]", encoding="utf-8")
        recent_file = _TEST_DIR / "2026-04.json"
        recent_file.write_text("[]", encoding="utf-8")
        svc.cleanup_expired(reference_date=date(2026, 4, 1))
        self.assertFalse(old_file.exists())
        self.assertTrue(recent_file.exists())
```

- [ ] **Step 2: Run tests to verify RED**

Run: `python -m pytest tests/test_monthly_summary_service.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'monthly_summary_service'`

- [ ] **Step 3: Implement monthly_summary_service.py**

```python
# monthly_summary_service.py
import json
from datetime import date, datetime
from pathlib import Path

_SUMMARY_DIR = Path(__file__).resolve().parent / "monthly_summary"

_MONTHS_TO_KEEP = 6


def _month_file(month: str) -> Path:
    return _SUMMARY_DIR / f"{month}.json"


def _read_json(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, data: list[dict]) -> None:
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def save_record(
    supplier_name: str,
    total_price: float,
    tax: float,
    invoice_date: str,
    month: str,
) -> dict:
    record = {
        "supplier_name": supplier_name,
        "total_price": total_price,
        "tax": tax,
        "total_with_tax": total_price + tax,
        "invoice_date": invoice_date,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    path = _month_file(month)
    records = _read_json(path)
    records.append(record)
    _write_json(path, records)
    return record


def load_records(month: str) -> list[dict]:
    return _read_json(_month_file(month))


def list_months() -> list[str]:
    if not _SUMMARY_DIR.exists():
        return []
    months = [
        f.stem for f in _SUMMARY_DIR.glob("*.json")
        if f.stem[:4].isdigit()
    ]
    months.sort(reverse=True)
    return months


def cleanup_expired(reference_date: date | None = None) -> None:
    ref = reference_date or date.today()
    cutoff_year = ref.year
    cutoff_month = ref.month - _MONTHS_TO_KEEP
    if cutoff_month <= 0:
        cutoff_year -= 1
        cutoff_month += 12
    cutoff = f"{cutoff_year:04d}-{cutoff_month:02d}"
    if not _SUMMARY_DIR.exists():
        return
    for f in _SUMMARY_DIR.glob("*.json"):
        if f.stem < cutoff:
            f.unlink()
```

- [ ] **Step 4: Run tests to verify GREEN**

Run: `python -m pytest tests/test_monthly_summary_service.py -v`
Expected: All 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add monthly_summary_service.py tests/test_monthly_summary_service.py
git commit -m "feat: monthly_summary_service — JSON 存取与过期清理"
```

---

### Task 3: monthly_summary_service.py — PDF 生成

**Files:**
- Modify: `monthly_summary_service.py`
- Modify: `tests/test_monthly_summary_service.py`

- [ ] **Step 1: Write failing test for PDF generation**

Append to `tests/test_monthly_summary_service.py`:

```python
class TestBuildPdf(unittest.TestCase):
    def setUp(self):
        _TEST_DIR.mkdir(exist_ok=True)
        svc._SUMMARY_DIR = _TEST_DIR

    def tearDown(self):
        shutil.rmtree(_TEST_DIR, ignore_errors=True)

    def test_builds_pdf_bytes(self):
        svc.save_record("ABC贸易", 12000.0, 1560.0, "2026-04-15", "2026-04")
        svc.save_record("XYZ国际", 8500.0, 1105.0, "2026-04-18", "2026-04")
        pdf_bytes = svc.build_pdf("2026-04")
        self.assertGreater(len(pdf_bytes), 100)
        self.assertTrue(pdf_bytes[:5] == b"%PDF-")

    def test_empty_month_returns_pdf_with_no_records_note(self):
        pdf_bytes = svc.build_pdf("2099-01")
        self.assertTrue(pdf_bytes[:5] == b"%PDF-")
```

- [ ] **Step 2: Run test to verify RED**

Run: `python -m pytest tests/test_monthly_summary_service.py::TestBuildPdf -v`
Expected: FAIL — `AttributeError: module 'monthly_summary_service' has no attribute 'build_pdf'`

- [ ] **Step 3: Implement build_pdf**

Add to `monthly_summary_service.py`:

```python
import io
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Spacer, Paragraph
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib import colors

_FONT_NAME = "NotoSansSC"
_FONT_REGISTERED = False


def _register_font() -> None:
    global _FONT_REGISTERED
    if _FONT_REGISTERED:
        return
    font_path = Path(__file__).resolve().parent / "static" / "fonts" / "NotoSansSC-Regular.ttf"
    if font_path.exists():
        pdfmetrics.registerFont(TTFont(_FONT_NAME, str(font_path)))
    else:
        global _FONT_NAME
        _FONT_NAME = "Helvetica"
    _FONT_REGISTERED = True


def _format_euro(amount: float) -> str:
    return f"€{amount:,.2f}"


def build_pdf(month: str) -> bytes:
    _register_font()
    records = load_records(month)

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=20 * mm, bottomMargin=20 * mm)
    elements = []

    styles = getSampleStyleSheet()
    title_style = styles["Title"].clone("title_cn")
    title_style.fontName = _FONT_NAME
    title_style.fontSize = 16

    elements.append(Paragraph(f"{month} 月度采购财务总结", title_style))
    elements.append(Spacer(1, 10 * mm))

    if not records:
        no_data_style = styles["Normal"].clone("nodata_cn")
        no_data_style.fontName = _FONT_NAME
        elements.append(Paragraph("本月暂无记录", no_data_style))
    else:
        for rec in records:
            data = [
                ["供应商", rec["supplier_name"]],
                ["开票日期", rec["invoice_date"]],
                ["总价", _format_euro(rec["total_price"])],
                ["税金", _format_euro(rec["tax"])],
                ["加税总价", _format_euro(rec["total_with_tax"])],
            ]
            table = Table(data, colWidths=[40 * mm, 80 * mm])
            table.setStyle(TableStyle([
                ("FONTNAME", (0, 0), (-1, -1), _FONT_NAME),
                ("FONTSIZE", (0, 0), (-1, -1), 11),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("BACKGROUND", (0, 0), (0, -1), colors.Color(0.95, 0.95, 0.95)),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]))
            elements.append(table)
            elements.append(Spacer(1, 8 * mm))

    doc.build(elements)
    return buf.getvalue()
```

- [ ] **Step 4: Run tests to verify GREEN**

Run: `python -m pytest tests/test_monthly_summary_service.py -v`
Expected: All 7 tests PASS

- [ ] **Step 5: Commit**

```bash
git add monthly_summary_service.py tests/test_monthly_summary_service.py
git commit -m "feat: monthly_summary_service — PDF 报表生成"
```

---

### Task 4: routes_monthly_summary.py — API 路由

**Files:**
- Create: `routes_monthly_summary.py`

- [ ] **Step 1: Create routes_monthly_summary.py**

```python
# routes_monthly_summary.py
import io

from flask import Blueprint, jsonify, request, send_file

import monthly_summary_service

bp = Blueprint("monthly_summary", __name__, url_prefix="/monthly-summary")


@bp.post("/save")
def save():
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"ok": False, "msg": "缺少 JSON 数据"}), 400
    required = ("supplier_name", "total_price", "tax", "invoice_date", "month")
    missing = [k for k in required if not data.get(k) and data.get(k) != 0]
    if missing:
        return jsonify({"ok": False, "msg": f"缺少字段：{', '.join(missing)}"}), 400
    try:
        record = monthly_summary_service.save_record(
            supplier_name=data["supplier_name"],
            total_price=float(data["total_price"]),
            tax=float(data["tax"]),
            invoice_date=data["invoice_date"],
            month=data["month"],
        )
    except Exception as exc:
        return jsonify({"ok": False, "msg": f"保存失败：{exc}"}), 500
    return jsonify({"ok": True, "record": record})


@bp.get("/months")
def list_months():
    months = monthly_summary_service.list_months()
    return jsonify({"ok": True, "months": months})


@bp.get("/records/<month>")
def get_records(month: str):
    records = monthly_summary_service.load_records(month)
    return jsonify({"ok": True, "records": records, "count": len(records)})


@bp.get("/pdf/<month>")
def download_pdf(month: str):
    try:
        pdf_bytes = monthly_summary_service.build_pdf(month)
    except Exception as exc:
        return jsonify({"ok": False, "msg": f"生成 PDF 失败：{exc}"}), 500
    return send_file(
        io.BytesIO(pdf_bytes),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=f"月度采购总结_{month}.pdf",
    )
```

- [ ] **Step 2: Commit**

```bash
git add routes_monthly_summary.py
git commit -m "feat: routes_monthly_summary — API 路由"
```

---

### Task 5: 注册 Blueprint + 启动清理

**Files:**
- Modify: `routes.py`
- Modify: `server.py`

- [ ] **Step 1: Register blueprint in routes.py**

In `routes.py`, add import and registration:

```python
from routes_pages_tasks import bp as pages_tasks_bp
from routes_purchase import bp as purchase_bp
from routes_query import bp as query_bp
from routes_monthly_summary import bp as monthly_summary_bp

from config import CONFIG


def register_routes(app) -> None:
    app.register_blueprint(pages_tasks_bp)
    app.register_blueprint(query_bp)
    app.register_blueprint(purchase_bp)
    app.register_blueprint(monthly_summary_bp)
    if CONFIG.dual_mode:
        from routes_transfer import bp as transfer_bp
        from routes_collab import bp as collab_bp
        app.register_blueprint(transfer_bp)
        app.register_blueprint(collab_bp)
```

- [ ] **Step 2: Add directory creation and cleanup in server.py**

In `server.py`, add to `create_app()`:

```python
import socket

from flask import Flask

import monthly_summary_service
import storage_service
from config import CONFIG
from routes import register_routes
from state import INPUT_DIR, OUTPUT_DIR, TRANSFER_DIR


def create_app() -> Flask:
    app = Flask(__name__, template_folder=str(CONFIG.templates_dir))

    dirs = [INPUT_DIR, OUTPUT_DIR, CONFIG.trash_dir]
    if CONFIG.dual_mode:
        dirs.append(TRANSFER_DIR)
    for folder in dirs:
        folder.mkdir(exist_ok=True)

    storage_service.startup_cleanup()
    monthly_summary_service.cleanup_expired()
    register_routes(app)
    return app
```

- [ ] **Step 3: Run all tests to verify no regression**

Run: `python -m pytest -v`
Expected: All tests PASS

- [ ] **Step 4: Commit**

```bash
git add routes.py server.py
git commit -m "feat: 注册月度总结 blueprint，启动时清理过期数据"
```

---

### Task 6: 中文字体文件

**Files:**
- Create: `static/fonts/` 目录

PDF 需要中文字体支持。reportlab 默认字体不支持中文。

- [ ] **Step 1: 下载 Noto Sans SC Regular 字体**

Run: `mkdir -p static/fonts && curl -L -o static/fonts/NotoSansSC-Regular.ttf "https://github.com/google/fonts/raw/main/ofl/notosanssc/NotoSansSC%5Bwght%5D.ttf"` 或手动放置。

如果下载不可用，使用系统自带中文字体。在 `monthly_summary_service.py` 的 `_register_font()` 中添加回退：

```python
def _register_font() -> None:
    global _FONT_REGISTERED, _FONT_NAME
    if _FONT_REGISTERED:
        return
    candidates = [
        Path(__file__).resolve().parent / "static" / "fonts" / "NotoSansSC-Regular.ttf",
        Path("C:/Windows/Fonts/msyh.ttc"),  # 微软雅黑 (Windows)
        Path("C:/Windows/Fonts/simsun.ttc"),  # 宋体 (Windows)
    ]
    for font_path in candidates:
        if font_path.exists():
            try:
                pdfmetrics.registerFont(TTFont(_FONT_NAME, str(font_path)))
                _FONT_REGISTERED = True
                return
            except Exception:
                continue
    _FONT_NAME = "Helvetica"
    _FONT_REGISTERED = True
```

- [ ] **Step 2: Commit**

```bash
git add monthly_summary_service.py static/fonts/ 2>/dev/null
git commit -m "feat: PDF 中文字体支持（NotoSansSC + Windows 回退）"
```

---

### Task 7: 前端 — 导出前模态框

**Files:**
- Modify: `static/js/purchase.js`

- [ ] **Step 1: 在 init() 的 page.innerHTML 中添加模态框 HTML**

在 `</div>` (pur-actions) 之后追加：

```html
<div class="pur-modal-overlay" id="purModalOverlay" style="display:none">
  <div class="pur-modal">
    <div class="pur-modal-title">记录到月度总结</div>
    <label>供应商名称<input class="pur-inp" id="purMsSupplier" placeholder="必填"></label>
    <label>总价 (€)<input class="pur-inp" id="purMsTotal" type="number" step="0.01"></label>
    <label>税金 (€)<input class="pur-inp" id="purMsTax" type="number" step="0.01" placeholder="必填"></label>
    <label>加税总价 (€)<input class="pur-inp" id="purMsTotalTax" disabled></label>
    <label>开票日期<input class="pur-inp" id="purMsDate" type="date"></label>
    <label>目标月份<input class="pur-inp" id="purMsMonth" type="month"></label>
    <div class="pur-modal-actions">
      <button class="pur-btn-dl" id="purMsConfirm">确认并导出</button>
      <button class="pur-btn-copy" id="purMsSkip">跳过，直接导出</button>
    </div>
  </div>
</div>
```

- [ ] **Step 2: 修改 downloadZip 函数，先弹出模态框**

Replace `downloadZip` function body — show modal instead of immediate export:

```javascript
async function downloadZip() {
  if (!storedSupplierFile) return;
  const totalPrice = rows.reduce((sum, r) => sum + r.price * r.quantity, 0);
  const rounded = Math.round(totalPrice * 100) / 100;
  document.getElementById('purMsTotal').value = rounded.toFixed(2);
  document.getElementById('purMsTax').value = '';
  document.getElementById('purMsTotalTax').value = '';
  document.getElementById('purMsDate').value = new Date().toISOString().slice(0, 10);
  document.getElementById('purMsMonth').value = new Date().toISOString().slice(0, 7);
  document.getElementById('purMsSupplier').value = '';
  document.getElementById('purModalOverlay').style.display = 'flex';
}
```

- [ ] **Step 3: 添加模态框事件绑定到 init()**

在 `init()` 中 `document.getElementById('purDl')` 之后添加：

```javascript
document.getElementById('purMsTax').addEventListener('input', updateTotalTax);
document.getElementById('purMsTotal').addEventListener('input', updateTotalTax);
document.getElementById('purMsConfirm').addEventListener('click', confirmWithSummary);
document.getElementById('purMsSkip').addEventListener('click', skipAndExport);
```

- [ ] **Step 4: 添加模态框逻辑函数**

在 `downloadZip` 之后添加：

```javascript
function updateTotalTax() {
  const total = parseFloat(document.getElementById('purMsTotal').value) || 0;
  const tax = parseFloat(document.getElementById('purMsTax').value) || 0;
  document.getElementById('purMsTotalTax').value = (total + tax).toFixed(2);
}

async function confirmWithSummary() {
  const supplier = document.getElementById('purMsSupplier').value.trim();
  const total = parseFloat(document.getElementById('purMsTotal').value);
  const tax = parseFloat(document.getElementById('purMsTax').value);
  const invoiceDate = document.getElementById('purMsDate').value;
  const month = document.getElementById('purMsMonth').value;
  if (!supplier || isNaN(tax) || !invoiceDate || !month) {
    setStatus('请填写所有必填字段', true);
    return;
  }
  try {
    const res = await fetch('/monthly-summary/save', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        supplier_name: supplier,
        total_price: total,
        tax: tax,
        invoice_date: invoiceDate,
        month: month,
      }),
    });
    const body = await res.json();
    if (!body.ok) { setStatus(body.msg, true); return; }
  } catch (e) {
    setStatus('保存月度记录失败：' + e.message, true);
    return;
  }
  document.getElementById('purModalOverlay').style.display = 'none';
  await doExport();
}

function skipAndExport() {
  document.getElementById('purModalOverlay').style.display = 'none';
  doExport();
}
```

- [ ] **Step 5: 提取原导出逻辑到 doExport()**

将原来 `downloadZip` 的导出逻辑提取为 `doExport()`：

```javascript
async function doExport() {
  if (!storedSupplierFile) return;
  const btn = document.getElementById('purDl');
  btn.disabled = true;
  const fd = new FormData();
  fd.append('file', storedSupplierFile);
  fd.append('rows', JSON.stringify(rows));
  const entriesForExport = newEntries.map(e => ({
    barcode: e.barcode, name: e.name, invoice_name: e.invoice_name,
    supplier_id: supplierInfo.id, supplier_name: supplierInfo.name,
  }));
  fd.append('new_entries', JSON.stringify(entriesForExport));
  try {
    const res = await fetch('/purchase/export', { method: 'POST', body: fd });
    if (!res.ok) { const b = await res.json(); setStatus(b.msg, true); return; }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `采购订单${new Date().toISOString().slice(0,10).replace(/-/g,'')}.zip`;
    a.click();
    URL.revokeObjectURL(url);
  } catch (e) { setStatus('下载失败：' + e.message, true); }
  finally { updateButtons(); }
}
```

- [ ] **Step 6: Commit**

```bash
git add static/js/purchase.js
git commit -m "feat: 采购订单导出前弹出月度总结模态框"
```

---

### Task 8: 前端 — 月度总结区域 + 补录

**Files:**
- Modify: `static/js/purchase.js`

- [ ] **Step 1: 在 init() 的 page.innerHTML 中添加月度总结区域**

在模态框 `</div>` 之后、闭合标签之前追加：

```html
<div class="pur-summary-section" id="purSummarySection">
  <div class="pur-summary-hd">月度总结</div>
  <div class="pur-summary-controls">
    <select class="pur-inp" id="purSumMonth"></select>
    <span id="purSumCount"></span>
    <button class="pur-btn-copy" id="purSumAdd">补录</button>
    <button class="pur-btn-dl" id="purSumDl">下载 PDF</button>
  </div>
</div>
```

- [ ] **Step 2: 添加月度总结初始化和刷新函数**

```javascript
async function loadSummaryMonths() {
  try {
    const res = await fetch('/monthly-summary/months');
    const body = await res.json();
    const sel = document.getElementById('purSumMonth');
    if (!sel) return;
    const current = new Date().toISOString().slice(0, 7);
    const months = body.months || [];
    if (!months.includes(current)) months.unshift(current);
    sel.innerHTML = months.map(m => `<option value="${m}">${m}</option>`).join('');
    await loadSummaryCount();
  } catch (e) { /* silent */ }
}

async function loadSummaryCount() {
  const month = document.getElementById('purSumMonth')?.value;
  if (!month) return;
  try {
    const res = await fetch(`/monthly-summary/records/${month}`);
    const body = await res.json();
    const el = document.getElementById('purSumCount');
    if (el) el.textContent = `${body.count || 0} 条记录`;
  } catch (e) { /* silent */ }
}

async function downloadSummaryPdf() {
  const month = document.getElementById('purSumMonth')?.value;
  if (!month) return;
  try {
    const res = await fetch(`/monthly-summary/pdf/${month}`);
    if (!res.ok) { setStatus('下载 PDF 失败', true); return; }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `月度采购总结_${month}.pdf`;
    a.click();
    URL.revokeObjectURL(url);
  } catch (e) { setStatus('下载 PDF 失败：' + e.message, true); }
}

function openAddRecord() {
  const month = document.getElementById('purSumMonth')?.value || new Date().toISOString().slice(0, 7);
  document.getElementById('purMsTotal').value = '';
  document.getElementById('purMsTax').value = '';
  document.getElementById('purMsTotalTax').value = '';
  document.getElementById('purMsDate').value = '';
  document.getElementById('purMsMonth').value = month;
  document.getElementById('purMsSupplier').value = '';
  document.getElementById('purModalOverlay').style.display = 'flex';
  // 补录模式：确认后不触发导出
  document.getElementById('purMsConfirm').onclick = async () => {
    await confirmWithSummary();
    document.getElementById('purMsConfirm').onclick = () => confirmWithSummary();
    await loadSummaryCount();
  };
  document.getElementById('purMsSkip').style.display = 'none';
}
```

- [ ] **Step 3: 在 init() 中绑定月度总结事件**

```javascript
document.getElementById('purSumMonth').addEventListener('change', loadSummaryCount);
document.getElementById('purSumDl').addEventListener('click', downloadSummaryPdf);
document.getElementById('purSumAdd').addEventListener('click', openAddRecord);
loadSummaryMonths();
```

- [ ] **Step 4: 在 confirmWithSummary 成功后恢复"跳过"按钮可见**

在 `confirmWithSummary` 函数中 `document.getElementById('purModalOverlay').style.display = 'none'` 之后添加：

```javascript
document.getElementById('purMsSkip').style.display = '';
```

- [ ] **Step 5: Commit**

```bash
git add static/js/purchase.js
git commit -m "feat: 月度总结区域 — 月份选择、记录计数、补录、PDF 下载"
```

---

### Task 9: 模态框 CSS 样式

**Files:**
- 需要在现有 CSS 文件中添加模态框和月度总结区域样式

- [ ] **Step 1: 查找并确认 CSS 文件路径**

Run: `ls static/css/` or check the HTML template for stylesheet links.

- [ ] **Step 2: 添加模态框和月度总结样式**

```css
.pur-modal-overlay {
  position: fixed; inset: 0; background: rgba(0,0,0,0.5);
  display: flex; align-items: center; justify-content: center; z-index: 1000;
}
.pur-modal {
  background: #1e293b; border-radius: 12px; padding: 24px;
  min-width: 360px; display: flex; flex-direction: column; gap: 12px;
}
.pur-modal-title { font-size: 16px; font-weight: bold; color: #f1f5f9; margin-bottom: 4px; }
.pur-modal label { display: flex; flex-direction: column; gap: 4px; color: #94a3b8; font-size: 13px; }
.pur-modal-actions { display: flex; gap: 8px; margin-top: 8px; }

.pur-summary-section {
  margin-top: 16px; padding: 12px; border: 1px solid #334155; border-radius: 8px;
}
.pur-summary-hd { font-size: 14px; font-weight: bold; color: #f1f5f9; margin-bottom: 8px; }
.pur-summary-controls { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
```

- [ ] **Step 3: Commit**

```bash
git add static/css/
git commit -m "style: 月度总结模态框和总结区域样式"
```

---

### Task 10: 端到端验证

- [ ] **Step 1: 启动服务**

Run: `python server.py`
Expected: 服务正常启动，无报错

- [ ] **Step 2: 测试采购订单导出流程**

1. 上传供应商 Excel + stockpile CSV
2. 点击「下载全部」→ 模态框弹出
3. 填写供应商名称、税金、开票日期 → 点「确认并导出」
4. 验证 ZIP 正常下载
5. 验证 `monthly_summary/` 下生成了当月 JSON 文件

- [ ] **Step 3: 测试月度总结区域**

1. 月份选择器显示当月
2. 记录条数正确
3. 点「下载 PDF」→ PDF 正常下载，中文显示正确
4. 点「补录」→ 模态框弹出（无"跳过"按钮），填写后保存
5. 记录条数更新

- [ ] **Step 4: 测试跳过导出**

1. 点击「下载全部」→ 模态框弹出
2. 点「跳过，直接导出」→ ZIP 正常下载，无月度记录保存

- [ ] **Step 5: 运行全部测试**

Run: `python -m pytest -v`
Expected: All tests PASS

- [ ] **Step 6: Final commit**

```bash
git add -A
git commit -m "feat: 采购订单月度财务总结功能完成"
```

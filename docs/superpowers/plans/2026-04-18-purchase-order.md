# Purchase Order Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "采购订单" tab that parses a supplier Excel, formats each row as `barcode,price,,quantity`, lets users fix flagged prices, then copies all lines and downloads the original Excel with a new "导入信息" column appended.

**Architecture:** New Flask Blueprint `purchase_bp` in `routes_purchase.py`. `purchase_service.py` handles parsing and Excel mutation. Frontend is a self-contained IIFE in `purchase.js` that stores the uploaded file in memory and re-sends it on export.

**Tech Stack:** Flask, pandas, openpyxl, unittest + unittest.mock

---

### Task 1: purchase_service.py — parse, format, export

**Files:**
- Create: `purchase_service.py`
- Create: `tests/test_purchase_service.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_purchase_service.py`:

```python
import io
import unittest

import openpyxl

from purchase_service import PurchaseRow, parse_purchase_excel, build_output_excel


def _make_excel(data_rows: list[list]) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["条码", "col2", "价格", "col4", "col5", "数量", "col7"])
    for row in data_rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


class TestPurchaseRow(unittest.TestCase):
    def test_formatted_two_decimal(self):
        row = PurchaseRow(barcode="1234567890123", price_raw="9.48", price=9.48, quantity=144, price_flagged=False)
        self.assertEqual(row.formatted(), "1234567890123,9.48,,144")

    def test_formatted_pads_whole_number_to_two_decimal(self):
        row = PurchaseRow(barcode="1234567890123", price_raw="12", price=12.0, quantity=36, price_flagged=False)
        self.assertEqual(row.formatted(), "1234567890123,12.00,,36")

    def test_to_dict_has_expected_keys(self):
        row = PurchaseRow(barcode="1111", price_raw="5.0", price=5.0, quantity=10, price_flagged=False)
        d = row.to_dict()
        self.assertEqual(d["barcode"], "1111")
        self.assertAlmostEqual(d["price"], 5.0)
        self.assertEqual(d["quantity"], 10)
        self.assertFalse(d["price_flagged"])
        self.assertEqual(d["formatted"], "1111,5.00,,10")


class TestParsePurchaseExcel(unittest.TestCase):
    def test_parses_basic_row(self):
        data = _make_excel([["1234567890123", "x", 9.48, "x", "x", 144, "x"]])
        rows = parse_purchase_excel(data)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].barcode, "1234567890123")
        self.assertAlmostEqual(rows[0].price, 9.48)
        self.assertEqual(rows[0].quantity, 144)
        self.assertFalse(rows[0].price_flagged)

    def test_flags_price_with_more_than_two_decimals(self):
        data = _make_excel([["1234567890123", "x", 9.4812, "x", "x", 10, "x"]])
        rows = parse_purchase_excel(data)
        self.assertTrue(rows[0].price_flagged)

    def test_does_not_flag_trailing_zeros(self):
        data = _make_excel([["1234567890123", "x", 9.480, "x", "x", 10, "x"]])
        rows = parse_purchase_excel(data)
        self.assertFalse(rows[0].price_flagged)

    def test_parses_multiple_data_rows_skips_header(self):
        data = _make_excel([
            ["BC1", "x", 1.0, "x", "x", 5, "x"],
            ["BC2", "x", 2.0, "x", "x", 3, "x"],
        ])
        rows = parse_purchase_excel(data)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0].barcode, "BC1")
        self.assertEqual(rows[1].barcode, "BC2")


class TestBuildOutputExcel(unittest.TestCase):
    def test_appends_header_and_data(self):
        file_bytes = _make_excel([["BC1", "x", 9.48, "x", "x", 10, "x"]])
        rows_data = [{"formatted": "BC1,9.48,,10"}]
        result = build_output_excel(file_bytes, rows_data)
        wb = openpyxl.load_workbook(io.BytesIO(result))
        ws = wb.active
        self.assertEqual(ws.cell(row=1, column=8).value, "导入信息")
        self.assertEqual(ws.cell(row=2, column=8).value, "BC1,9.48,,10")

    def test_original_data_preserved(self):
        file_bytes = _make_excel([["BC1", "x", 9.48, "x", "x", 10, "x"]])
        result = build_output_excel(file_bytes, [{"formatted": "BC1,9.48,,10"}])
        wb = openpyxl.load_workbook(io.BytesIO(result))
        ws = wb.active
        self.assertEqual(ws.cell(row=2, column=1).value, "BC1")
        self.assertAlmostEqual(ws.cell(row=2, column=3).value, 9.48)
```

- [ ] **Step 2: Run tests — confirm they FAIL**

```bash
cd "C:\Users\jxwu2002\Desktop\双端处理" && python -m pytest tests/test_purchase_service.py -v 2>&1 | head -10
```

Expected: `ModuleNotFoundError: No module named 'purchase_service'`

- [ ] **Step 3: Create `purchase_service.py`**

```python
import io
from dataclasses import dataclass

import openpyxl
import pandas as pd


def _decimal_places(value) -> int:
    s = str(float(value))
    if '.' in s:
        return len(s.split('.')[1].rstrip('0'))
    return 0


@dataclass
class PurchaseRow:
    barcode: str
    price_raw: str
    price: float
    quantity: int
    price_flagged: bool

    def formatted(self) -> str:
        return f"{self.barcode},{self.price:.2f},,{self.quantity}"

    def to_dict(self) -> dict:
        return {
            "barcode": self.barcode,
            "price": self.price,
            "quantity": self.quantity,
            "price_flagged": self.price_flagged,
            "formatted": self.formatted(),
        }


def parse_purchase_excel(file_bytes: bytes) -> list[PurchaseRow]:
    df = pd.read_excel(io.BytesIO(file_bytes), header=0)
    rows = []
    for _, row in df.iterrows():
        barcode = str(row.iloc[0]).strip()
        price_val = row.iloc[2]
        qty_val = row.iloc[5]
        try:
            price = float(price_val)
            price_flagged = _decimal_places(price) > 2
        except (ValueError, TypeError):
            price = 0.0
            price_flagged = True
        try:
            quantity = int(qty_val)
        except (ValueError, TypeError):
            quantity = 0
        rows.append(PurchaseRow(
            barcode=barcode,
            price_raw=str(price_val),
            price=price,
            quantity=quantity,
            price_flagged=price_flagged,
        ))
    return rows


def build_output_excel(file_bytes: bytes, rows_data: list[dict]) -> bytes:
    wb = openpyxl.load_workbook(io.BytesIO(file_bytes))
    ws = wb.active
    col = ws.max_column + 1
    ws.cell(row=1, column=col, value="导入信息")
    for i, row in enumerate(rows_data):
        ws.cell(row=i + 2, column=col, value=row["formatted"])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
```

- [ ] **Step 4: Run tests — confirm all PASS**

```bash
python -m pytest tests/test_purchase_service.py -v
```

Expected: 9 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add purchase_service.py tests/test_purchase_service.py
git commit -m "feat: add purchase_service — parse Excel, format rows, append 导入信息 column"
```

---

### Task 2: routes_purchase.py — process + export

**Files:**
- Create: `routes_purchase.py`
- Create: `tests/test_purchase_routes.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_purchase_routes.py`:

```python
import io
import json
import unittest
from unittest.mock import patch

import openpyxl
from flask import Flask

from routes_purchase import bp


def make_app():
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(bp)
    return app


def _excel_bytes():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["条码", "col2", "价格", "col4", "col5", "数量"])
    ws.append(["1234567890123", "x", 9.48, "x", "x", 144])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


class TestPurchaseRoutes(unittest.TestCase):
    def setUp(self):
        self.client = make_app().test_client()

    def test_process_requires_file(self):
        response = self.client.post("/purchase/process")
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.get_json()["ok"])

    def test_process_returns_rows(self):
        from purchase_service import PurchaseRow
        mock_rows = [
            PurchaseRow(barcode="1234567890123", price_raw="9.48",
                        price=9.48, quantity=144, price_flagged=False)
        ]
        with patch("routes_purchase.purchase_service.parse_purchase_excel", return_value=mock_rows):
            response = self.client.post(
                "/purchase/process",
                data={"file": (io.BytesIO(b"fake"), "test.xlsx")},
                content_type="multipart/form-data",
            )
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertTrue(body["ok"])
        self.assertEqual(len(body["rows"]), 1)
        self.assertEqual(body["rows"][0]["barcode"], "1234567890123")
        self.assertEqual(body["rows"][0]["formatted"], "1234567890123,9.48,,144")

    def test_export_requires_file(self):
        response = self.client.post("/purchase/export",
                                    data={"rows": "[]"},
                                    content_type="multipart/form-data")
        self.assertEqual(response.status_code, 400)

    def test_export_returns_xlsx(self):
        rows_json = json.dumps([{"formatted": "1234567890123,9.48,,144"}])
        response = self.client.post(
            "/purchase/export",
            data={
                "file": (io.BytesIO(_excel_bytes()), "test.xlsx"),
                "rows": rows_json,
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("spreadsheet", response.content_type)
```

- [ ] **Step 2: Run tests — confirm they FAIL**

```bash
python -m pytest tests/test_purchase_routes.py -v 2>&1 | head -10
```

Expected: `ModuleNotFoundError: No module named 'routes_purchase'`

- [ ] **Step 3: Create `routes_purchase.py`**

```python
import io
import json
from datetime import date

from flask import Blueprint, jsonify, request, send_file

import purchase_service

bp = Blueprint("purchase", __name__, url_prefix="/purchase")


@bp.post("/process")
def process():
    f = request.files.get("file")
    if not f or f.filename == "":
        return jsonify({"ok": False, "msg": "请先上传 Excel 文件"}), 400
    try:
        rows = purchase_service.parse_purchase_excel(f.read())
    except Exception as exc:
        return jsonify({"ok": False, "msg": f"解析失败：{exc}"}), 500
    return jsonify({"ok": True, "rows": [r.to_dict() for r in rows]})


@bp.post("/export")
def export():
    f = request.files.get("file")
    if not f or f.filename == "":
        return jsonify({"ok": False, "msg": "请先上传 Excel 文件"}), 400
    rows_data = json.loads(request.form.get("rows", "[]"))
    try:
        xlsx_bytes = purchase_service.build_output_excel(f.read(), rows_data)
    except Exception as exc:
        return jsonify({"ok": False, "msg": f"导出失败：{exc}"}), 500
    filename = f"采购订单{date.today().strftime('%Y%m%d')}.xlsx"
    return send_file(
        io.BytesIO(xlsx_bytes),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name=filename,
    )
```

- [ ] **Step 4: Run all tests — confirm PASS**

```bash
python -m pytest tests/ -v 2>&1 | tail -8
```

Expected: all existing tests + 4 new purchase route tests PASS.

- [ ] **Step 5: Commit**

```bash
git add routes_purchase.py tests/test_purchase_routes.py
git commit -m "feat: add purchase blueprint with /process and /export routes"
```

---

### Task 3: Register blueprint + wire nav in index.html

**Files:**
- Modify: `routes.py`
- Modify: `templates/index.html`

- [ ] **Step 1: Register purchase_bp in routes.py**

Current `routes.py`:
```python
from routes_pages_tasks import bp as pages_tasks_bp
from routes_query import bp as query_bp

from config import CONFIG


def register_routes(app) -> None:
    app.register_blueprint(pages_tasks_bp)
    app.register_blueprint(query_bp)
    if CONFIG.dual_mode:
        from routes_transfer import bp as transfer_bp
        from routes_collab import bp as collab_bp
        app.register_blueprint(transfer_bp)
        app.register_blueprint(collab_bp)
```

Replace with:

```python
from routes_pages_tasks import bp as pages_tasks_bp
from routes_purchase import bp as purchase_bp
from routes_query import bp as query_bp

from config import CONFIG


def register_routes(app) -> None:
    app.register_blueprint(pages_tasks_bp)
    app.register_blueprint(query_bp)
    app.register_blueprint(purchase_bp)
    if CONFIG.dual_mode:
        from routes_transfer import bp as transfer_bp
        from routes_collab import bp as collab_bp
        app.register_blueprint(transfer_bp)
        app.register_blueprint(collab_bp)
```

- [ ] **Step 2: Edit `templates/index.html` — three edits**

**Edit A:** In `<head>`, after the `index.css` link, add:
```html
<link rel="stylesheet" href="{{ url_for('static', filename='css/purchase.css') }}">
```

**Edit B:** In the nav div, find:
```html
<div class="nav-item" id="navDup" onclick="switchPage('dup')">重复检查</div></div>
```
Replace with:
```html
<div class="nav-item" id="navDup" onclick="switchPage('dup')">重复检查</div><div class="nav-item" id="navPurchase" onclick="switchPage('purchase')">采购订单</div></div>
```

**Edit C:** After the closing `</div>` of `id="pageDup"`, before the closing `</div>` of `.pages`, add:
```html
      <div class="page" id="pagePurchase"></div>
```

**Edit D:** Before `</body>`, add:
```html
<script src="{{ url_for('static', filename='js/purchase.js') }}"></script>
```

- [ ] **Step 3: Verify existing tests still pass**

```bash
python -m pytest tests/ -q 2>&1 | tail -3
```

Expected: all PASS.

- [ ] **Step 4: Commit**

```bash
git add routes.py templates/index.html
git commit -m "feat: register purchase blueprint and add nav item"
```

---

### Task 4: Frontend — purchase.css + purchase.js

**Files:**
- Create: `static/css/purchase.css`
- Create: `static/js/purchase.js`

- [ ] **Step 1: Create `static/css/purchase.css`**

```css
#pagePurchase.active{display:flex;flex-direction:column;gap:16px;height:100%;min-height:0}
.pur-drop{border:2px dashed #2d3148;border-radius:8px;padding:28px;text-align:center;cursor:pointer;transition:.2s}
.pur-drop:hover,.pur-drop.drag{border-color:#4f46e5;background:#1e1b4b22}
.pur-drop input{display:none}
.pur-results{flex:1;min-height:0;overflow:auto;background:#0d0f1a;border:1px solid #2d3148;border-radius:8px;padding:10px 12px;font-family:"Cascadia Code","Consolas",monospace;font-size:13px;line-height:1.8}
.pur-row{display:flex;align-items:center;gap:8px;padding:2px 0}
.pur-row.flagged{color:#f87171}
.pur-row .pur-text{flex:1;color:#e2e8f0}
.pur-row.flagged .pur-text{color:#f87171}
.pur-price-input{width:80px;background:#1a1d27;border:1px solid #f87171;border-radius:4px;color:#fbbf24;font-size:13px;padding:2px 6px;font-family:inherit}
.pur-price-input.valid{border-color:#4ade80;color:#4ade80}
.pur-actions{display:flex;gap:8px;justify-content:flex-end;align-items:center;flex-shrink:0}
.pur-status{font-size:12px;color:#64748b;flex:1}
.pur-status.error{color:#f87171}
.pur-btn-copy{background:#0e7490;color:#fff;border:none;border-radius:8px;padding:10px 20px;font-size:13px;font-weight:600;cursor:pointer}
.pur-btn-copy:hover:not(:disabled){background:#0c6578}
.pur-btn-copy.copied{background:#059669}
.pur-btn-dl{background:#4f46e5;color:#fff;border:none;border-radius:8px;padding:10px 20px;font-size:13px;font-weight:600;cursor:pointer}
.pur-btn-dl:hover:not(:disabled){background:#4338ca}
.pur-btn-copy:disabled,.pur-btn-dl:disabled{opacity:.45;cursor:not-allowed}
```

- [ ] **Step 2: Create `static/js/purchase.js`**

```javascript
(function () {
  let storedFile = null;
  let rows = [];

  function init() {
    const page = document.getElementById('pagePurchase');
    if (!page) return;
    page.innerHTML = `
      <div class="pur-drop" id="purDrop">
        <input type="file" id="purInput" accept=".xlsx,.xls">
        <div>拖入或点击选择供应商 Excel 文件</div>
        <div class="hint">第1列条码 · 第3列价格 · 第6列数量</div>
      </div>
      <div class="pur-results" id="purResults"><div class="empty">上传文件后显示结果</div></div>
      <div class="pur-actions">
        <div class="pur-status" id="purStatus"></div>
        <button class="pur-btn-copy" id="purCopy" disabled>一键复制</button>
        <button class="pur-btn-dl" id="purDl" disabled>下载采购订单</button>
      </div>`;

    const drop = document.getElementById('purDrop');
    const input = document.getElementById('purInput');
    drop.addEventListener('click', () => input.click());
    drop.addEventListener('dragover', e => { e.preventDefault(); drop.classList.add('drag'); });
    drop.addEventListener('dragleave', () => drop.classList.remove('drag'));
    drop.addEventListener('drop', e => { e.preventDefault(); drop.classList.remove('drag'); handleFile(e.dataTransfer.files[0]); });
    input.addEventListener('change', () => { handleFile(input.files[0]); input.value = ''; });
    document.getElementById('purCopy').addEventListener('click', copyAll);
    document.getElementById('purDl').addEventListener('click', downloadExcel);
  }

  async function handleFile(file) {
    if (!file) return;
    storedFile = file;
    setStatus('解析中...');
    const fd = new FormData();
    fd.append('file', file);
    try {
      const res = await fetch('/purchase/process', { method: 'POST', body: fd });
      const body = await res.json();
      if (!body.ok) { setStatus(body.msg, true); return; }
      rows = body.rows;
      renderResults();
      setStatus(`共 ${rows.length} 条，${rows.filter(r => r.price_flagged).length} 条需修改价格`);
    } catch (e) {
      setStatus('解析失败：' + e.message, true);
    }
  }

  function renderResults() {
    const container = document.getElementById('purResults');
    if (!rows.length) { container.innerHTML = '<div class="empty">未解析到数据</div>'; updateButtons(); return; }
    container.innerHTML = rows.map((r, i) => {
      if (r.price_flagged) {
        const parts = r.formatted.split(',');
        return `<div class="pur-row flagged" data-i="${i}">
          <span class="pur-text">${parts[0]},</span>
          <input class="pur-price-input" data-i="${i}" value="${parts[1]}" title="价格小数超2位，请修改">
          <span class="pur-text">,,${parts[3]}</span>
        </div>`;
      }
      return `<div class="pur-row" data-i="${i}"><span class="pur-text">${r.formatted}</span></div>`;
    }).join('');
    container.querySelectorAll('.pur-price-input').forEach(el => {
      el.addEventListener('input', onPriceEdit);
      el.addEventListener('change', onPriceEdit);
    });
    updateButtons();
  }

  function onPriceEdit(e) {
    const i = +e.target.dataset.i;
    const val = e.target.value.trim();
    const price = parseFloat(val);
    const decimals = val.includes('.') ? val.split('.')[1].replace(/0+$/, '').length : 0;
    const valid = !isNaN(price) && decimals <= 2;
    e.target.classList.toggle('valid', valid);
    if (valid) {
      rows[i].price = price;
      rows[i].price_flagged = false;
      rows[i].formatted = `${rows[i].barcode},${price.toFixed(2)},,${rows[i].quantity}`;
    } else {
      rows[i].price_flagged = true;
    }
    updateButtons();
  }

  function updateButtons() {
    const anyFlagged = rows.some(r => r.price_flagged);
    const hasRows = rows.length > 0;
    document.getElementById('purCopy').disabled = anyFlagged || !hasRows;
    document.getElementById('purDl').disabled = anyFlagged || !hasRows;
  }

  async function copyAll() {
    const text = rows.map(r => r.formatted).join('\n');
    try {
      await navigator.clipboard.writeText(text);
      const btn = document.getElementById('purCopy');
      btn.textContent = '已复制 ✓';
      btn.classList.add('copied');
      setTimeout(() => { btn.textContent = '一键复制'; btn.classList.remove('copied'); }, 2000);
    } catch (e) {
      setStatus('复制失败：' + e.message, true);
    }
  }

  async function downloadExcel() {
    if (!storedFile) return;
    const btn = document.getElementById('purDl');
    btn.disabled = true;
    const fd = new FormData();
    fd.append('file', storedFile);
    fd.append('rows', JSON.stringify(rows));
    try {
      const res = await fetch('/purchase/export', { method: 'POST', body: fd });
      if (!res.ok) { const b = await res.json(); setStatus(b.msg, true); return; }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `采购订单${new Date().toISOString().slice(0,10).replace(/-/g,'')}.xlsx`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setStatus('下载失败：' + e.message, true);
    } finally {
      updateButtons();
    }
  }

  function setStatus(msg, isError = false) {
    const el = document.getElementById('purStatus');
    if (!el) return;
    el.textContent = msg;
    el.className = 'pur-status' + (isError ? ' error' : '');
  }

  document.addEventListener('DOMContentLoaded', function () {
    init();
    const orig = window.switchPage;
    window.switchPage = function (pg) {
      if (typeof orig === 'function') orig(pg);
      if (pg === 'purchase') {
        document.querySelectorAll('.nav-item').forEach(el => el.classList.remove('active'));
        document.getElementById('navPurchase')?.classList.add('active');
        document.querySelectorAll('.page').forEach(el => el.classList.remove('active'));
        document.getElementById('pagePurchase')?.classList.add('active');
      }
    };
  });
})();
```

- [ ] **Step 3: Run full test suite**

```bash
python -m pytest tests/ -q 2>&1 | tail -3
```

Expected: all PASS (no JS tests — frontend verified manually).

- [ ] **Step 4: Commit**

```bash
git add static/css/purchase.css static/js/purchase.js
git commit -m "feat: add purchase order frontend — upload, format, copy, download"
```

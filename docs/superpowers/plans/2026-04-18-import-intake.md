# Import Intake Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "进货识别" tab that lets users upload invoice photos, extract structured data via Gemini Vision, review in an editable table, and export to Excel.

**Architecture:** New Flask Blueprint `import_bp` in `routes_import.py` handles upload/recognize/export. `import_service.py` encapsulates Gemini Vision calls and result parsing. Frontend lives in `static/js/import.js` + `static/css/import.css` with a new `templates/import.html` page fragment rendered inside the existing `index.html` SPA shell.

**Tech Stack:** Flask, google-generativeai (Gemini 1.5 Flash), openpyxl, unittest + unittest.mock

---

### Task 1: Config + requirements

**Files:**
- Modify: `config.py`
- Modify: `requirements.txt`

- [ ] **Step 1: Add gemini_api_key to AppConfig**

In `config.py`, add `gemini_api_key` field (reads from env `GEMINI_API_KEY`):

```python
import os
# at the top, after existing imports

@dataclass(frozen=True)
class AppConfig:
    base_dir: Path
    resource_dir: Path
    host: str = "0.0.0.0"
    port: int = 5000
    debug: bool = False
    child_process_encoding: str = "utf-8"
    csv_fallback_encoding: str = "gbk"
    web_poll_interval_ms: int = 5000
    dual_mode: bool = True
    gemini_api_key: str = ""
```

Then update the bottom of `config.py` to read from env:

```python
CONFIG = AppConfig(
    base_dir=_data_dir(),
    resource_dir=_resource_dir(),
    gemini_api_key=os.environ.get("GEMINI_API_KEY", ""),
)
```

- [ ] **Step 2: Add google-generativeai to requirements.txt**

```
flask
pandas
openpyxl
google-generativeai
```

- [ ] **Step 3: Commit**

```bash
git add config.py requirements.txt
git commit -m "feat: add gemini_api_key config + google-generativeai dependency"
```

---

### Task 2: import_service.py — data model + parsing + export

**Files:**
- Create: `import_service.py`
- Create: `tests/test_import_service.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_import_service.py`:

```python
import unittest
from unittest.mock import MagicMock, patch

from import_service import ImportItem, parse_gemini_response, build_excel_bytes


class TestImportItem(unittest.TestCase):
    def test_unit_price_computed_when_both_present(self):
        item = ImportItem(barcode="1234567890123", quantity=10, total_price=250.0)
        self.assertAlmostEqual(item.unit_price, 25.0)

    def test_unit_price_none_when_quantity_none(self):
        item = ImportItem(barcode="1234567890123", quantity=None, total_price=250.0)
        self.assertIsNone(item.unit_price)

    def test_unit_price_none_when_total_price_none(self):
        item = ImportItem(barcode="1234567890123", quantity=10, total_price=None)
        self.assertIsNone(item.unit_price)

    def test_flagged_when_barcode_none(self):
        item = ImportItem(barcode=None, quantity=10, total_price=100.0)
        self.assertTrue(item.flagged)

    def test_not_flagged_when_all_present(self):
        item = ImportItem(barcode="1234567890123", quantity=10, total_price=100.0)
        self.assertFalse(item.flagged)

    def test_barcode_suspect_when_wrong_length(self):
        item = ImportItem(barcode="123", quantity=10, total_price=100.0)
        self.assertTrue(item.barcode_suspect)

    def test_barcode_not_suspect_when_13_digits(self):
        item = ImportItem(barcode="1234567890123", quantity=10, total_price=100.0)
        self.assertFalse(item.barcode_suspect)


class TestParseGeminiResponse(unittest.TestCase):
    def test_parses_valid_json(self):
        raw = '[{"barcode": "1234567890123", "quantity": 5, "total_price": 100.0}]'
        items = parse_gemini_response(raw)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].barcode, "1234567890123")
        self.assertEqual(items[0].quantity, 5)
        self.assertAlmostEqual(items[0].total_price, 100.0)

    def test_parses_null_fields(self):
        raw = '[{"barcode": null, "quantity": 3, "total_price": null}]'
        items = parse_gemini_response(raw)
        self.assertIsNone(items[0].barcode)
        self.assertIsNone(items[0].total_price)
        self.assertTrue(items[0].flagged)

    def test_strips_markdown_code_fence(self):
        raw = '```json\n[{"barcode": "111", "quantity": 1, "total_price": 10.0}]\n```'
        items = parse_gemini_response(raw)
        self.assertEqual(len(items), 1)

    def test_returns_empty_on_invalid_json(self):
        items = parse_gemini_response("not json at all")
        self.assertEqual(items, [])


class TestBuildExcelBytes(unittest.TestCase):
    def test_returns_bytes(self):
        items = [ImportItem(barcode="1234567890123", quantity=2, total_price=50.0)]
        result = build_excel_bytes(items)
        self.assertIsInstance(result, bytes)
        self.assertGreater(len(result), 0)

    def test_sorted_by_barcode(self):
        import io
        import openpyxl
        items = [
            ImportItem(barcode="9999999999999", quantity=1, total_price=10.0),
            ImportItem(barcode="1111111111111", quantity=2, total_price=20.0),
        ]
        data = build_excel_bytes(items)
        wb = openpyxl.load_workbook(io.BytesIO(data))
        ws = wb.active
        rows = list(ws.iter_rows(min_row=2, values_only=True))
        self.assertEqual(rows[0][0], "1111111111111")
        self.assertEqual(rows[1][0], "9999999999999")
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd "C:\Users\jxwu2002\Desktop\双端处理" && python -m pytest tests/test_import_service.py -v 2>&1 | head -20
```

Expected: `ModuleNotFoundError: No module named 'import_service'`

- [ ] **Step 3: Implement import_service.py**

Create `import_service.py`:

```python
import io
import json
import re
from dataclasses import dataclass, field

import openpyxl


@dataclass
class ImportItem:
    barcode: str | None
    quantity: int | None
    total_price: float | None
    unit_price: float | None = field(init=False)
    flagged: bool = field(init=False)
    barcode_suspect: bool = field(init=False)

    def __post_init__(self):
        if self.quantity and self.total_price is not None:
            self.unit_price = round(self.total_price / self.quantity, 4)
        else:
            self.unit_price = None
        self.flagged = self.barcode is None or self.quantity is None or self.total_price is None
        self.barcode_suspect = (
            self.barcode is not None and not re.fullmatch(r"\d{8}|\d{13}", self.barcode)
        )

    def to_dict(self) -> dict:
        return {
            "barcode": self.barcode,
            "quantity": self.quantity,
            "total_price": self.total_price,
            "unit_price": self.unit_price,
            "flagged": self.flagged,
            "barcode_suspect": self.barcode_suspect,
        }


def parse_gemini_response(raw: str) -> list[ImportItem]:
    text = raw.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return []
    items = []
    for row in data:
        barcode = row.get("barcode")
        quantity = row.get("quantity")
        total_price = row.get("total_price")
        items.append(ImportItem(
            barcode=str(barcode) if barcode is not None else None,
            quantity=int(quantity) if quantity is not None else None,
            total_price=float(total_price) if total_price is not None else None,
        ))
    return items


def recognize_images(image_bytes_list: list[bytes], api_key: str) -> list[ImportItem]:
    import google.generativeai as genai
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(
        model_name="gemini-1.5-flash",
        system_instruction=(
            "You are a data extraction assistant. Given one or more supplier invoice images "
            "(possibly in Greek, English, or other languages), extract all line items. "
            "Return ONLY a JSON array with objects: "
            '{"barcode": "...", "quantity": N, "total_price": N.NN}. '
            "If a field is uncertain or missing, use null. Do not guess. No extra text."
        ),
    )
    parts = []
    for img_bytes in image_bytes_list:
        parts.append({"mime_type": "image/jpeg", "data": img_bytes})
    parts.append("Extract all line items from these invoice images.")
    response = model.generate_content(parts)
    return parse_gemini_response(response.text)


def build_excel_bytes(items: list[ImportItem]) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Barcode", "数量", "单价(€)", "总价(€)"])
    for item in sorted(items, key=lambda x: x.barcode or ""):
        ws.append([item.barcode, item.quantity, item.unit_price, item.total_price])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_import_service.py -v
```

Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add import_service.py tests/test_import_service.py
git commit -m "feat: add ImportItem model, Gemini response parser, and Excel export"
```

---

### Task 3: routes_import.py — upload / recognize / export

**Files:**
- Create: `routes_import.py`
- Create: `tests/test_import_routes.py`

- [ ] **Step 1: Write failing route tests**

Create `tests/test_import_routes.py`:

```python
import unittest
from unittest.mock import patch, MagicMock

from flask import Flask

from routes_import import bp


def make_app():
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(bp)
    return app


class TestImportRoutes(unittest.TestCase):
    def setUp(self):
        self.client = make_app().test_client()

    def test_recognize_requires_files(self):
        response = self.client.post("/import/recognize")
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.get_json()["ok"])

    def test_recognize_calls_service_and_returns_items(self):
        from import_service import ImportItem
        mock_item = ImportItem(barcode="1234567890123", quantity=5, total_price=100.0)
        with patch("routes_import.import_service.recognize_images", return_value=[mock_item]), \
             patch("routes_import.CONFIG") as mock_cfg:
            mock_cfg.gemini_api_key = "test-key"
            data = {"files": (b"\xff\xd8\xff", "invoice.jpg", "image/jpeg")}
            from io import BytesIO
            response = self.client.post(
                "/import/recognize",
                data={"files": (BytesIO(b"\xff\xd8\xff"), "invoice.jpg")},
                content_type="multipart/form-data",
            )
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertTrue(body["ok"])
        self.assertEqual(len(body["items"]), 1)
        self.assertEqual(body["items"][0]["barcode"], "1234567890123")

    def test_export_returns_xlsx(self):
        payload = {
            "items": [
                {"barcode": "1234567890123", "quantity": 3, "total_price": 75.0, "unit_price": 25.0}
            ]
        }
        response = self.client.post("/import/export", json=payload)
        self.assertEqual(response.status_code, 200)
        self.assertIn("spreadsheet", response.content_type)

    def test_export_rejects_flagged_items(self):
        payload = {
            "items": [
                {"barcode": None, "quantity": 3, "total_price": 75.0, "unit_price": 25.0}
            ]
        }
        response = self.client.post("/import/export", json=payload)
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.get_json()["ok"])
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_import_routes.py -v 2>&1 | head -10
```

Expected: `ModuleNotFoundError: No module named 'routes_import'`

- [ ] **Step 3: Implement routes_import.py**

Create `routes_import.py`:

```python
import io
from datetime import datetime

from flask import Blueprint, jsonify, request, send_file

import import_service
from config import CONFIG

bp = Blueprint("import", __name__, url_prefix="/import")


@bp.post("/recognize")
def recognize():
    files = request.files.getlist("files")
    if not files or all(f.filename == "" for f in files):
        return jsonify({"ok": False, "msg": "请先上传图片"}), 400
    image_bytes_list = [f.read() for f in files]
    try:
        items = import_service.recognize_images(image_bytes_list, CONFIG.gemini_api_key)
    except Exception as exc:
        return jsonify({"ok": False, "msg": f"识别失败：{exc}"}), 500
    return jsonify({"ok": True, "items": [item.to_dict() for item in items]})


@bp.post("/export")
def export():
    data = request.get_json(silent=True) or {}
    rows = data.get("items", [])
    if any(row.get("barcode") is None or row.get("quantity") is None or row.get("total_price") is None for row in rows):
        return jsonify({"ok": False, "msg": "存在未填写的红色单元格，请补全后再导出"}), 400
    items = [
        import_service.ImportItem(
            barcode=row["barcode"],
            quantity=int(row["quantity"]),
            total_price=float(row["total_price"]),
        )
        for row in rows
    ]
    xlsx_bytes = import_service.build_excel_bytes(items)
    filename = f"import_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    return send_file(
        io.BytesIO(xlsx_bytes),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name=filename,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_import_routes.py -v
```

Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add routes_import.py tests/test_import_routes.py
git commit -m "feat: add import blueprint with recognize and export routes"
```

---

### Task 4: Register blueprint + wire nav in index.html

**Files:**
- Modify: `routes.py`
- Modify: `templates/index.html`

- [ ] **Step 1: Register import_bp in routes.py**

Replace the content of `routes.py`:

```python
from routes_import import bp as import_bp
from routes_pages_tasks import bp as pages_tasks_bp
from routes_query import bp as query_bp

from config import CONFIG


def register_routes(app) -> None:
    app.register_blueprint(pages_tasks_bp)
    app.register_blueprint(query_bp)
    app.register_blueprint(import_bp)
    if CONFIG.dual_mode:
        from routes_transfer import bp as transfer_bp
        from routes_collab import bp as collab_bp
        app.register_blueprint(transfer_bp)
        app.register_blueprint(collab_bp)
```

- [ ] **Step 2: Add nav item and page div in index.html**

In `templates/index.html`, find the nav div:
```html
<div class="nav" id="nav"><div class="nav-item active" id="navMain" onclick="switchPage('main')">标签处理</div><div class="nav-item" id="navDup" onclick="switchPage('dup')">重复检查</div></div>
```
Replace with:
```html
<div class="nav" id="nav"><div class="nav-item active" id="navMain" onclick="switchPage('main')">标签处理</div><div class="nav-item" id="navDup" onclick="switchPage('dup')">重复检查</div><div class="nav-item" id="navImport" onclick="switchPage('import')">进货识别</div></div>
```

After the `pageDup` div closing tag (before `</div>` closing `.pages`), add:
```html
      <div class="page" id="pageImport">
        <div class="panel" style="height:100%"><div class="panel-hd">进货识别</div><div class="panel-bd" id="importContent"></div></div>
      </div>
```

Also add the import CSS link in `<head>`:
```html
<link rel="stylesheet" href="{{ url_for('static', filename='css/import.css') }}">
```

And add the import JS before `</body>`:
```html
<script src="{{ url_for('static', filename='js/import.js') }}"></script>
```

- [ ] **Step 3: Verify existing route tests still pass**

```bash
python -m pytest tests/test_routes.py -v
```

Expected: All PASS.

- [ ] **Step 4: Commit**

```bash
git add routes.py templates/index.html
git commit -m "feat: register import blueprint and add nav item"
```

---

### Task 5: Frontend — import.css + import.js

**Files:**
- Create: `static/css/import.css`
- Create: `static/js/import.js`

- [ ] **Step 1: Create import.css**

Create `static/css/import.css`:

```css
#pageImport.active{display:flex;gap:16px;height:100%}
.import-left{width:260px;flex-shrink:0;display:flex;flex-direction:column;gap:12px}
.import-right{flex:1;display:flex;flex-direction:column;gap:12px;min-width:0}
.img-drop{border:2px dashed #2d3148;border-radius:8px;padding:24px;text-align:center;cursor:pointer;transition:.2s}
.img-drop:hover,.img-drop.drag{border-color:#4f46e5;background:#1e1b4b22}
.img-drop input{display:none}
.thumb-list{display:flex;flex-direction:column;gap:6px;overflow:auto;max-height:260px}
.thumb-item{display:flex;align-items:center;gap:8px;background:#13151f;border:1px solid #2d3148;border-radius:6px;padding:6px 8px;font-size:12px}
.thumb-item img{width:40px;height:40px;object-fit:cover;border-radius:4px;border:1px solid #2d3148}
.thumb-name{flex:1;color:#cbd5e1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.thumb-rm{cursor:pointer;color:#4a5568;font-size:16px}.thumb-rm:hover{color:#f87171}
.import-tbl{width:100%;border-collapse:collapse;font-size:13px}
.import-tbl th{text-align:left;padding:8px 10px;background:#1a1d27;color:#64748b;font-size:11px;border-bottom:1px solid #2d3148}
.import-tbl td{padding:6px 8px;border-bottom:1px solid #1a1d27}
.import-tbl td input{width:100%;background:transparent;border:none;color:#e2e8f0;outline:none;font-size:13px}
.import-tbl td input:focus{background:#13151f;border-radius:4px}
.cell-null{background:#450a0a22}
.cell-null input{color:#f87171}
.cell-suspect{background:#42200622}
.cell-suspect input{color:#fbbf24}
.tbl-wrap{overflow:auto;flex:1}
.import-actions{display:flex;gap:8px;justify-content:flex-end;margin-top:8px}
```

- [ ] **Step 2: Create import.js**

Create `static/js/import.js`:

```javascript
(function () {
  let uploadedFiles = [];
  let recognizedItems = [];

  function init() {
    const page = document.getElementById('pageImport');
    if (!page) return;
    page.innerHTML = `
      <div class="import-left">
        <div class="img-drop" id="imgDrop">
          <input type="file" id="imgInput" multiple accept="image/*">
          <div>拖入图片或点击选择</div>
          <div class="hint">支持 JPG / PNG / WEBP</div>
        </div>
        <div class="thumb-list" id="thumbList"></div>
        <button class="btn r" id="btnRecognize" disabled>开始识别</button>
      </div>
      <div class="import-right">
        <div class="tbl-wrap" id="tblWrap"><div class="empty">上传图片后点击"开始识别"</div></div>
        <div class="import-actions">
          <div class="status" id="importStatus"></div>
          <button class="btn d" id="btnExport" style="width:auto;padding:10px 24px;margin:0" disabled>导出 Excel</button>
        </div>
      </div>`;

    const drop = document.getElementById('imgDrop');
    const input = document.getElementById('imgInput');
    drop.addEventListener('click', () => input.click());
    drop.addEventListener('dragover', e => { e.preventDefault(); drop.classList.add('drag'); });
    drop.addEventListener('dragleave', () => drop.classList.remove('drag'));
    drop.addEventListener('drop', e => { e.preventDefault(); drop.classList.remove('drag'); addFiles(e.dataTransfer.files); });
    input.addEventListener('change', () => addFiles(input.files));
    document.getElementById('btnRecognize').addEventListener('click', recognize);
    document.getElementById('btnExport').addEventListener('click', exportExcel);
  }

  function addFiles(fileList) {
    for (const f of fileList) {
      if (!f.type.startsWith('image/')) continue;
      uploadedFiles.push(f);
    }
    renderThumbs();
    document.getElementById('btnRecognize').disabled = uploadedFiles.length === 0;
  }

  function renderThumbs() {
    const list = document.getElementById('thumbList');
    list.innerHTML = uploadedFiles.map((f, i) => `
      <div class="thumb-item">
        <img src="${URL.createObjectURL(f)}">
        <span class="thumb-name">${f.name}</span>
        <span class="thumb-rm" data-i="${i}">✕</span>
      </div>`).join('');
    list.querySelectorAll('.thumb-rm').forEach(el => {
      el.addEventListener('click', () => { uploadedFiles.splice(+el.dataset.i, 1); renderThumbs(); });
    });
  }

  async function recognize() {
    const btn = document.getElementById('btnRecognize');
    btn.disabled = true;
    btn.textContent = '识别中…';
    setStatus('');
    const fd = new FormData();
    uploadedFiles.forEach(f => fd.append('files', f));
    try {
      const res = await fetch('/import/recognize', { method: 'POST', body: fd });
      const body = await res.json();
      if (!body.ok) { setStatus(body.msg, true); return; }
      recognizedItems = body.items;
      renderTable();
    } catch (e) {
      setStatus('网络错误：' + e.message, true);
    } finally {
      btn.disabled = false;
      btn.textContent = '开始识别';
    }
  }

  function renderTable() {
    const wrap = document.getElementById('tblWrap');
    if (!recognizedItems.length) { wrap.innerHTML = '<div class="empty">未识别到任何条目</div>'; return; }
    wrap.innerHTML = `<table class="import-tbl">
      <thead><tr><th>Barcode</th><th>数量</th><th>单价(€)</th><th>总价(€)</th></tr></thead>
      <tbody>${recognizedItems.map((it, i) => `
        <tr>
          <td class="${it.flagged && it.barcode == null ? 'cell-null' : it.barcode_suspect ? 'cell-suspect' : ''}"><input data-i="${i}" data-f="barcode" value="${it.barcode ?? ''}"></td>
          <td class="${it.quantity == null ? 'cell-null' : ''}"><input data-i="${i}" data-f="quantity" type="number" value="${it.quantity ?? ''}"></td>
          <td><input data-i="${i}" data-f="unit_price" type="number" readonly tabindex="-1" value="${it.unit_price != null ? it.unit_price.toFixed(2) : ''}"></td>
          <td class="${it.total_price == null ? 'cell-null' : ''}"><input data-i="${i}" data-f="total_price" type="number" value="${it.total_price != null ? it.total_price.toFixed(2) : ''}"></td>
        </tr>`).join('')}
      </tbody></table>`;
    wrap.querySelectorAll('input[data-f]').forEach(el => el.addEventListener('change', onCellChange));
    updateExportBtn();
  }

  function onCellChange(e) {
    const i = +e.target.dataset.i;
    const f = e.target.dataset.f;
    const val = e.target.value.trim();
    if (f === 'barcode') recognizedItems[i].barcode = val || null;
    else if (f === 'quantity') recognizedItems[i].quantity = val ? +val : null;
    else if (f === 'total_price') recognizedItems[i].total_price = val ? +val : null;
    const it = recognizedItems[i];
    it.flagged = it.barcode == null || it.quantity == null || it.total_price == null;
    it.unit_price = (it.quantity && it.total_price != null) ? +(it.total_price / it.quantity).toFixed(4) : null;
    renderTable();
  }

  async function exportExcel() {
    const btn = document.getElementById('btnExport');
    btn.disabled = true;
    try {
      const res = await fetch('/import/export', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ items: recognizedItems }),
      });
      if (!res.ok) { const b = await res.json(); setStatus(b.msg, true); return; }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `import_${new Date().toISOString().replace(/[-:T]/g, '').slice(0, 15)}.xlsx`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setStatus('导出失败：' + e.message, true);
    } finally {
      btn.disabled = false;
    }
  }

  function updateExportBtn() {
    const anyFlagged = recognizedItems.some(it => it.flagged);
    document.getElementById('btnExport').disabled = anyFlagged || recognizedItems.length === 0;
  }

  function setStatus(msg, isError = false) {
    const el = document.getElementById('importStatus');
    el.textContent = msg;
    el.className = 'status' + (isError ? ' error' : '');
  }

  // Hook into existing switchPage if available
  const _origSwitch = window.switchPage;
  window.switchPage = function (page) {
    if (_origSwitch) _origSwitch(page);
    document.querySelectorAll('.nav-item').forEach(el => el.classList.remove('active'));
    const navId = { main: 'navMain', dup: 'navDup', import: 'navImport' }[page];
    if (navId) document.getElementById(navId)?.classList.add('active');
    document.querySelectorAll('.page').forEach(el => el.classList.remove('active'));
    const pageEl = { main: 'pageMain', dup: 'pageDup', import: 'pageImport' }[page];
    if (pageEl) document.getElementById(pageEl)?.classList.add('active');
  };

  document.addEventListener('DOMContentLoaded', init);
})();
```

- [ ] **Step 3: Commit**

```bash
git add static/css/import.css static/js/import.js
git commit -m "feat: add import-intake frontend (upload, table, export)"
```

---

### Task 6: Smoke test in browser

- [ ] **Step 1: Install dependency**

```bash
pip install google-generativeai
```

- [ ] **Step 2: Start the server**

```bash
set GEMINI_API_KEY=your_key_here && python server.py
```

- [ ] **Step 3: Manual verification checklist**

Open `http://localhost:5000` and verify:
1. "进货识别" nav item appears
2. Clicking it shows the two-panel layout
3. Dragging an image into the drop zone shows a thumbnail
4. "开始识别" button becomes enabled
5. (With a real API key) clicking recognize shows the results table
6. Red cells appear for null fields; yellow for suspect barcodes
7. Editing a cell recalculates unit_price
8. "导出 Excel" is disabled while red cells exist
9. After filling all red cells, "导出 Excel" enables and clicking downloads the file

- [ ] **Step 4: Run full test suite**

```bash
python -m pytest tests/ -v
```

Expected: All tests PASS.

- [ ] **Step 5: Final commit**

```bash
git add .
git commit -m "feat: complete import-intake feature"
```

# Purchase Order v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task.

**Goal:** Extend 采购订单 page to accept supplier xlsx + stockpile csv, identify new barcodes, let user fill supplier/name fields inline, and return a zip of purchase xlsx + filled template csv.

**Architecture:** Backend adds 4 functions to `purchase_service.py`, extends 2 routes in `routes_purchase.py`. Frontend rewrites upload/results flow in `purchase.js`, adds new-barcode UI in `purchase.css`. Template lives at `static/templates/产品信息导入模板.csv` (GBK, already committed).

**Tech Stack:** Python (stdlib `csv`, `zipfile`), Flask, vanilla JS.

**Reference files already read by controller:**
- `purchase_service.py` — has `PurchaseRow`, `parse_purchase_excel`, `build_output_excel`
- `routes_purchase.py` — has `/purchase/process`, `/purchase/export`
- `static/js/purchase.js` — has `init`, `handleFile`, `renderResults`, `copyAll`, `downloadExcel`
- `static/css/purchase.css` — purchase page styles
- `config.py` — `CONFIG.csv_fallback_encoding = "gbk"`
- Spec: `docs/superpowers/specs/2026-04-18-purchase-order-v2-design.md`

---

## Task 1: Backend — `parse_stockpile_csv` + `find_new_barcodes`

**Files:**
- Modify: `purchase_service.py` (add functions at bottom, and add `csv` import at top)
- Test: `tests/test_purchase_service.py` (add two new test classes)

- [ ] **Step 1: Write failing tests**

Append to `tests/test_purchase_service.py`:

```python
from purchase_service import parse_stockpile_csv, find_new_barcodes, PurchaseRow


def _stockpile_bytes(rows: list[list[str]], encoding: str = "utf-8") -> bytes:
    lines = [",".join(r) for r in rows]
    return "\n".join(lines).encode(encoding)


class TestParseStockpileCsv(unittest.TestCase):
    def test_header_only_returns_empty_set(self):
        data = _stockpile_bytes([["c1", "c2", "c3", "barcode"]])
        self.assertEqual(parse_stockpile_csv(data), set())

    def test_reads_column_4_barcodes(self):
        data = _stockpile_bytes([
            ["c1", "c2", "c3", "barcode"],
            ["a", "b", "c", "1234567890123"],
            ["a", "b", "c", "9876543210987"],
        ])
        self.assertEqual(parse_stockpile_csv(data), {"1234567890123", "9876543210987"})

    def test_falls_back_to_gbk_when_not_utf8(self):
        data = _stockpile_bytes([
            ["型号", "c2", "c3", "条码"],
            ["甲", "b", "c", "1111111111111"],
        ], encoding="gbk")
        self.assertEqual(parse_stockpile_csv(data), {"1111111111111"})

    def test_skips_rows_shorter_than_4_columns(self):
        data = _stockpile_bytes([
            ["c1", "c2", "c3", "barcode"],
            ["a", "b"],
            ["a", "b", "c", "1234567890123"],
        ])
        self.assertEqual(parse_stockpile_csv(data), {"1234567890123"})

    def test_strips_whitespace(self):
        data = _stockpile_bytes([
            ["c1", "c2", "c3", "barcode"],
            ["a", "b", "c", "  1234567890123  "],
        ])
        self.assertEqual(parse_stockpile_csv(data), {"1234567890123"})


class TestFindNewBarcodes(unittest.TestCase):
    def _row(self, barcode):
        return PurchaseRow(barcode=barcode, price_raw="1", price=1.0, quantity=1, price_flagged=False)

    def test_all_new_when_system_empty(self):
        rows = [self._row("A"), self._row("B")]
        self.assertEqual(find_new_barcodes(rows, set()), ["A", "B"])

    def test_returns_only_rows_not_in_system(self):
        rows = [self._row("A"), self._row("B"), self._row("C")]
        self.assertEqual(find_new_barcodes(rows, {"B"}), ["A", "C"])

    def test_dedupes_preserving_order(self):
        rows = [self._row("A"), self._row("A"), self._row("B"), self._row("A")]
        self.assertEqual(find_new_barcodes(rows, set()), ["A", "B"])

    def test_empty_rows_returns_empty(self):
        self.assertEqual(find_new_barcodes([], {"X"}), [])
```

- [ ] **Step 2: Run tests, confirm they fail**

`python -m pytest tests/test_purchase_service.py -v`
Expected: ImportError for `parse_stockpile_csv`, `find_new_barcodes`.

- [ ] **Step 3: Implement**

Edit `purchase_service.py`:
- Add `import csv` near top
- Add `from config import CONFIG` near top
- Add at bottom:

```python
def parse_stockpile_csv(file_bytes: bytes) -> set[str]:
    try:
        text = file_bytes.decode("utf-8")
    except UnicodeDecodeError:
        text = file_bytes.decode(CONFIG.csv_fallback_encoding)
    reader = csv.reader(io.StringIO(text))
    result = set()
    for i, row in enumerate(reader):
        if i == 0:
            continue
        if len(row) < 4:
            continue
        bc = row[3].strip()
        if bc:
            result.add(bc)
    return result


def find_new_barcodes(rows: list[PurchaseRow], system_set: set[str]) -> list[str]:
    seen = set()
    out = []
    for r in rows:
        bc = r.barcode
        if bc in system_set or bc in seen:
            continue
        seen.add(bc)
        out.append(bc)
    return out
```

- [ ] **Step 4: Run tests, confirm green**

`python -m pytest tests/test_purchase_service.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add purchase_service.py tests/test_purchase_service.py
git commit -m "feat: stockpile csv 解析和新条码比对"
```

---

## Task 2: Backend — `build_template_csv` + `build_zip`

**Files:**
- Modify: `purchase_service.py`
- Test: `tests/test_purchase_service.py`

- [ ] **Step 1: Write failing tests**

Append to test file:

```python
import zipfile
from purchase_service import build_template_csv, build_zip


class TestBuildTemplateCsv(unittest.TestCase):
    def test_single_entry_has_correct_indices(self):
        entries = [{
            "barcode": "1234567890123",
            "name": "测试品",
            "supplier_id": "S01",
            "supplier_name": "某供应商",
        }]
        out = build_template_csv(entries)
        text = out.decode("gbk")
        lines = text.splitlines()
        self.assertEqual(len(lines), 2)  # header + 1 data
        fields = next(csv.reader([lines[1]]))
        self.assertEqual(fields[0], "1234567890123")   # 型号
        self.assertEqual(fields[1], "1234567890123")   # 唯一码
        self.assertEqual(fields[3], "测试品")          # 品名
        self.assertEqual(fields[4], "测试品")          # 品名2
        self.assertEqual(fields[10], "1234567890123") # 条形码
        self.assertEqual(fields[38], "S01")
        self.assertEqual(fields[39], "某供应商")
        # other columns empty
        for i in [2, 5, 6, 7, 8, 9, 11, 12, 37]:
            self.assertEqual(fields[i], "")

    def test_column_count_matches_header(self):
        out = build_template_csv([{
            "barcode": "X", "name": "Y", "supplier_id": "S", "supplier_name": "N"
        }])
        lines = out.decode("gbk").splitlines()
        header_fields = next(csv.reader([lines[0]]))
        data_fields = next(csv.reader([lines[1]]))
        self.assertEqual(len(data_fields), len(header_fields))

    def test_multiple_entries(self):
        entries = [
            {"barcode": "A", "name": "品A", "supplier_id": "S1", "supplier_name": "N1"},
            {"barcode": "B", "name": "品B", "supplier_id": "S1", "supplier_name": "N1"},
        ]
        out = build_template_csv(entries)
        lines = out.decode("gbk").splitlines()
        self.assertEqual(len(lines), 3)


class TestBuildZip(unittest.TestCase):
    def test_xlsx_only_when_template_none(self):
        out = build_zip(b"fake-xlsx", None, "20260418")
        with zipfile.ZipFile(io.BytesIO(out)) as zf:
            names = zf.namelist()
        self.assertEqual(names, ["采购订单20260418.xlsx"])

    def test_both_files_when_template_provided(self):
        out = build_zip(b"fake-xlsx", b"fake-csv", "20260418")
        with zipfile.ZipFile(io.BytesIO(out)) as zf:
            names = sorted(zf.namelist())
        self.assertEqual(names, sorted(["采购订单20260418.xlsx", "产品信息导入模板.csv"]))

    def test_xlsx_content_preserved(self):
        out = build_zip(b"HELLO", None, "20260101")
        with zipfile.ZipFile(io.BytesIO(out)) as zf:
            self.assertEqual(zf.read("采购订单20260101.xlsx"), b"HELLO")
```

- [ ] **Step 2: Run tests, confirm fail** (ImportError)

- [ ] **Step 3: Implement**

Add to `purchase_service.py`:

```python
import zipfile
from pathlib import Path

_TEMPLATE_PATH = Path(__file__).resolve().parent / "static" / "templates" / "产品信息导入模板.csv"

_FIELD_INDICES = {
    "barcode_cols": (0, 1, 10),   # 型号, 唯一码, 条形码
    "name_cols": (3, 4),           # 品名, 品名2
    "supplier_id_col": 38,
    "supplier_name_col": 39,
}


def _read_template_header() -> list[str]:
    with _TEMPLATE_PATH.open("rb") as f:
        raw = f.read()
    try:
        text = raw.decode("gbk")
    except UnicodeDecodeError:
        text = raw.decode("utf-8")
    first_line = text.splitlines()[0]
    return next(csv.reader([first_line]))


def build_template_csv(new_entries: list[dict]) -> bytes:
    header = _read_template_header()
    n_cols = len(header)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(header)
    for entry in new_entries:
        row = [""] * n_cols
        for i in _FIELD_INDICES["barcode_cols"]:
            if i < n_cols:
                row[i] = entry["barcode"]
        for i in _FIELD_INDICES["name_cols"]:
            if i < n_cols:
                row[i] = entry["name"]
        if _FIELD_INDICES["supplier_id_col"] < n_cols:
            row[_FIELD_INDICES["supplier_id_col"]] = entry["supplier_id"]
        if _FIELD_INDICES["supplier_name_col"] < n_cols:
            row[_FIELD_INDICES["supplier_name_col"]] = entry["supplier_name"]
        writer.writerow(row)
    return buf.getvalue().encode("gbk")


def build_zip(purchase_xlsx: bytes, template_csv: bytes | None, date_str: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"采购订单{date_str}.xlsx", purchase_xlsx)
        if template_csv is not None:
            zf.writestr("产品信息导入模板.csv", template_csv)
    return buf.getvalue()
```

- [ ] **Step 4: Run tests, green**

- [ ] **Step 5: Commit**

```bash
git add purchase_service.py tests/test_purchase_service.py
git commit -m "feat: 产品信息模板填充 + zip 打包"
```

---

## Task 3: Routes — update `/process` and `/export`

**Files:**
- Modify: `routes_purchase.py`
- Test: `tests/test_purchase_routes.py`

- [ ] **Step 1: Write failing tests**

Replace/extend `tests/test_purchase_routes.py` with (after the existing imports, replace the two old tests for `/export` and keep other cases; the new tests are):

```python
def _stockpile_bytes():
    return b"c1,c2,c3,barcode\na,b,c,EXIST-IN-SYSTEM\n"


class TestProcessTwoFiles(unittest.TestCase):
    def setUp(self):
        self.client = make_app().test_client()

    def test_requires_two_files(self):
        response = self.client.post(
            "/purchase/process",
            data={"files": (io.BytesIO(_excel_bytes()), "supplier.xlsx")},
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 400)

    def test_requires_stockpile_file(self):
        response = self.client.post(
            "/purchase/process",
            data={
                "files": [
                    (io.BytesIO(_excel_bytes()), "supplier.xlsx"),
                    (io.BytesIO(b"x,y"), "other.csv"),
                ]
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 400)

    def test_returns_rows_and_new_barcodes(self):
        response = self.client.post(
            "/purchase/process",
            data={
                "files": [
                    (io.BytesIO(_excel_bytes()), "supplier.xlsx"),
                    (io.BytesIO(_stockpile_bytes()), "stockpile_export.csv"),
                ]
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertTrue(body["ok"])
        self.assertEqual(len(body["rows"]), 1)
        self.assertEqual(body["new_barcodes"], ["1234567890123"])
        self.assertIn("EXIST-IN-SYSTEM", body["system_barcodes"])


class TestExportZip(unittest.TestCase):
    def setUp(self):
        self.client = make_app().test_client()

    def test_export_no_new_entries_returns_zip_with_only_xlsx(self):
        import zipfile as _z
        response = self.client.post(
            "/purchase/export",
            data={
                "file": (io.BytesIO(_excel_bytes()), "test.xlsx"),
                "rows": json.dumps([{"formatted": "1234567890123,9.48,,144"}]),
                "new_entries": "[]",
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content_type, "application/zip")
        with _z.ZipFile(io.BytesIO(response.data)) as zf:
            names = zf.namelist()
        self.assertEqual(len(names), 1)
        self.assertTrue(names[0].startswith("采购订单") and names[0].endswith(".xlsx"))

    def test_export_with_new_entries_returns_zip_with_both(self):
        import zipfile as _z
        entries = [{
            "barcode": "NEW1", "name": "测试品",
            "supplier_id": "S01", "supplier_name": "某供应商",
        }]
        response = self.client.post(
            "/purchase/export",
            data={
                "file": (io.BytesIO(_excel_bytes()), "test.xlsx"),
                "rows": json.dumps([{"formatted": "NEW1,9.48,,144"}]),
                "new_entries": json.dumps(entries),
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 200)
        with _z.ZipFile(io.BytesIO(response.data)) as zf:
            names = sorted(zf.namelist())
        self.assertEqual(len(names), 2)
        self.assertIn("产品信息导入模板.csv", names)
```

Delete the old `test_export_returns_xlsx` test (replaced by zip-based tests). Keep `test_process_requires_file` (still valid — no files at all).

- [ ] **Step 2: Run tests, confirm fail**

- [ ] **Step 3: Implement**

Replace body of `routes_purchase.py`:

```python
import io
import json
from datetime import date

from flask import Blueprint, jsonify, request, send_file

import purchase_service

bp = Blueprint("purchase", __name__, url_prefix="/purchase")


def _classify_files(files):
    stockpile, supplier = None, None
    for f in files:
        if not f or not f.filename:
            continue
        if f.filename.lower().startswith("stockpile"):
            stockpile = f
        else:
            supplier = f
    return supplier, stockpile


@bp.post("/process")
def process():
    files = request.files.getlist("files")
    if not files:
        single = request.files.get("file")
        if single:
            files = [single]
    if len(files) < 2:
        return jsonify({"ok": False, "msg": "请同时上传供应商 Excel 和 stockpile CSV"}), 400
    supplier, stockpile = _classify_files(files)
    if not supplier or not stockpile:
        return jsonify({"ok": False, "msg": "缺少供应商 Excel 或 stockpile CSV"}), 400
    try:
        rows = purchase_service.parse_purchase_excel(supplier.read())
        system_set = purchase_service.parse_stockpile_csv(stockpile.read())
        new_bcs = purchase_service.find_new_barcodes(rows, system_set)
    except Exception as exc:
        return jsonify({"ok": False, "msg": f"解析失败：{exc}"}), 500
    return jsonify({
        "ok": True,
        "rows": [r.to_dict() for r in rows],
        "system_barcodes": list(system_set),
        "new_barcodes": new_bcs,
    })


@bp.post("/export")
def export():
    f = request.files.get("file")
    if not f or f.filename == "":
        return jsonify({"ok": False, "msg": "请先上传 Excel 文件"}), 400
    rows_data = json.loads(request.form.get("rows", "[]"))
    new_entries = json.loads(request.form.get("new_entries", "[]"))
    try:
        xlsx_bytes = purchase_service.build_output_excel(f.read(), rows_data)
        template_csv = purchase_service.build_template_csv(new_entries) if new_entries else None
        date_str = date.today().strftime("%Y%m%d")
        zip_bytes = purchase_service.build_zip(xlsx_bytes, template_csv, date_str)
    except Exception as exc:
        return jsonify({"ok": False, "msg": f"导出失败：{exc}"}), 500
    return send_file(
        io.BytesIO(zip_bytes),
        mimetype="application/zip",
        as_attachment=True,
        download_name=f"采购订单{date_str}.zip",
    )
```

- [ ] **Step 4: Run tests, green**

`python -m pytest tests/test_purchase_routes.py tests/test_purchase_service.py -v`

- [ ] **Step 5: Commit**

```bash
git add routes_purchase.py tests/test_purchase_routes.py
git commit -m "feat: /purchase/process 双文件 + /purchase/export 返回 zip"
```

---

## Task 4: Frontend — multi-file upload + new-barcode UI + delete/modify

**Files:**
- Modify: `static/js/purchase.js` (rewrite most of it)
- Modify: `static/css/purchase.css` (add new-barcode section styles)

- [ ] **Step 1: Rewrite `purchase.js`**

Replace contents with:

```js
(function () {
  let storedSupplierFile = null;
  let rows = [];
  let systemBarcodes = new Set();
  let newEntries = [];  // [{barcode, name}]
  let supplierInfo = { id: '', name: '' };

  function init() {
    const page = document.getElementById('pagePurchase');
    if (!page) return;
    page.innerHTML = `
      <div class="pur-drop" id="purDrop">
        <input type="file" id="purInput" accept=".xlsx,.xls,.csv" multiple>
        <div>拖入或点击选择：供应商 Excel + 系统 stockpile CSV</div>
        <div class="hint">供应商：第1列条码 · 第3列价格 · 第6列数量　|　系统：文件名以 stockpile 开头</div>
      </div>
      <div class="pur-results" id="purResults"><div class="empty">上传文件后显示结果</div></div>
      <div class="pur-newbox" id="purNewBox" style="display:none">
        <div class="pur-newbox-hd">新条码处理</div>
        <div class="pur-supplier">
          供应商 ID: <input class="pur-inp" id="purSupId" placeholder="必填">
          供应商名称: <input class="pur-inp" id="purSupName" placeholder="必填">
        </div>
        <div id="purNewList"></div>
      </div>
      <div class="pur-actions">
        <div class="pur-status" id="purStatus"></div>
        <button class="pur-btn-copy" id="purCopy" disabled>一键复制</button>
        <button class="pur-btn-dl" id="purDl" disabled>下载全部</button>
      </div>`;
    const drop = document.getElementById('purDrop');
    const input = document.getElementById('purInput');
    drop.addEventListener('click', () => input.click());
    drop.addEventListener('dragover', e => { e.preventDefault(); drop.classList.add('drag'); });
    drop.addEventListener('dragleave', () => drop.classList.remove('drag'));
    drop.addEventListener('drop', e => { e.preventDefault(); drop.classList.remove('drag'); handleFiles(e.dataTransfer.files); });
    input.addEventListener('change', () => { handleFiles(input.files); input.value = ''; });
    document.getElementById('purCopy').addEventListener('click', copyAll);
    document.getElementById('purDl').addEventListener('click', downloadZip);
    document.getElementById('purSupId').addEventListener('input', e => { supplierInfo.id = e.target.value.trim(); updateButtons(); });
    document.getElementById('purSupName').addEventListener('input', e => { supplierInfo.name = e.target.value.trim(); updateButtons(); });
  }

  async function handleFiles(files) {
    files = Array.from(files || []);
    if (files.length < 2) { setStatus('需要 2 个文件：供应商 Excel + stockpile CSV', true); return; }
    let supplier = null, stockpile = null;
    for (const f of files) {
      if (f.name.toLowerCase().startsWith('stockpile')) stockpile = f;
      else supplier = f;
    }
    if (!supplier || !stockpile) { setStatus('未能识别：需要 1 个 stockpile 开头的 csv + 1 个供应商文件', true); return; }
    storedSupplierFile = supplier;
    setStatus('解析中...');
    const fd = new FormData();
    fd.append('files', supplier);
    fd.append('files', stockpile);
    try {
      const res = await fetch('/purchase/process', { method: 'POST', body: fd });
      const body = await res.json();
      if (!body.ok) { setStatus(body.msg, true); return; }
      rows = body.rows;
      systemBarcodes = new Set(body.system_barcodes);
      newEntries = body.new_barcodes.map(bc => ({ barcode: bc, name: '' }));
      renderResults();
      renderNewBox();
      const flagCount = rows.filter(r => r.price_flagged).length;
      setStatus(`共 ${rows.length} 条，${newEntries.length} 个新条码${flagCount ? `，${flagCount} 条需改价` : ''}`);
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

  function renderNewBox() {
    const box = document.getElementById('purNewBox');
    const list = document.getElementById('purNewList');
    if (!newEntries.length) { box.style.display = 'none'; updateButtons(); return; }
    box.style.display = '';
    list.innerHTML = newEntries.map((e, i) => `
      <div class="pur-new-row" data-i="${i}">
        <span class="pur-new-bc">${e.barcode}</span>
        品名: <input class="pur-inp pur-new-name" data-i="${i}" value="${escapeAttr(e.name)}" placeholder="必填">
        <button class="pur-new-mod" data-i="${i}">修改</button>
        <button class="pur-new-del" data-i="${i}">删除</button>
      </div>`).join('');
    list.querySelectorAll('.pur-new-name').forEach(el => {
      el.addEventListener('input', ev => { newEntries[+ev.target.dataset.i].name = ev.target.value.trim(); updateButtons(); });
    });
    list.querySelectorAll('.pur-new-mod').forEach(el => {
      el.addEventListener('click', ev => {
        const i = +ev.target.dataset.i;
        const inp = list.querySelector(`.pur-new-name[data-i="${i}"]`);
        inp && inp.focus();
      });
    });
    list.querySelectorAll('.pur-new-del').forEach(el => {
      el.addEventListener('click', ev => startDelete(+ev.target.dataset.i));
    });
    updateButtons();
  }

  function startDelete(i) {
    const list = document.getElementById('purNewList');
    const rowEl = list.querySelector(`.pur-new-row[data-i="${i}"]`);
    if (!rowEl) return;
    const oldBc = newEntries[i].barcode;
    rowEl.innerHTML = `<input class="pur-inp pur-new-correct" placeholder="输入修正后的条码，回车确认 / Esc 取消" autofocus>`;
    const inp = rowEl.querySelector('.pur-new-correct');
    inp.focus();
    const finish = (commit) => {
      const val = inp.value.trim();
      if (!commit || !val) { renderNewBox(); return; }
      applyCorrection(oldBc, val);
    };
    inp.addEventListener('keydown', ev => {
      if (ev.key === 'Enter') finish(true);
      else if (ev.key === 'Escape') finish(false);
    });
    inp.addEventListener('blur', () => finish(true));
  }

  function applyCorrection(oldBc, newBc) {
    rows.forEach(r => {
      if (r.barcode === oldBc) {
        r.barcode = newBc;
        const parts = r.formatted.split(',');
        r.formatted = `${newBc},${parts[1]},,${parts[3]}`;
      }
    });
    newEntries = newEntries.filter(e => e.barcode !== oldBc);
    if (!systemBarcodes.has(newBc) && !newEntries.some(e => e.barcode === newBc)) {
      newEntries.push({ barcode: newBc, name: '' });
    }
    renderResults();
    renderNewBox();
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
    const newOk = newEntries.length === 0 ||
      (supplierInfo.id && supplierInfo.name && newEntries.every(e => e.name));
    document.getElementById('purCopy').disabled = anyFlagged || !hasRows;
    document.getElementById('purDl').disabled = anyFlagged || !hasRows || !newOk;
  }

  async function copyAll() {
    const text = rows.map(r => r.formatted).join('\n');
    const done = () => {
      const btn = document.getElementById('purCopy');
      btn.textContent = '已复制 ✓'; btn.classList.add('copied');
      setTimeout(() => { btn.textContent = '一键复制'; btn.classList.remove('copied'); }, 2000);
    };
    try {
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(text); done(); return;
      }
      const ta = document.createElement('textarea');
      ta.value = text; ta.style.position = 'fixed'; ta.style.left = '-9999px';
      document.body.appendChild(ta); ta.select();
      const ok = document.execCommand('copy'); document.body.removeChild(ta);
      if (ok) done(); else setStatus('复制失败：浏览器不允许', true);
    } catch (e) { setStatus('复制失败：' + e.message, true); }
  }

  async function downloadZip() {
    if (!storedSupplierFile) return;
    const btn = document.getElementById('purDl');
    btn.disabled = true;
    const fd = new FormData();
    fd.append('file', storedSupplierFile);
    fd.append('rows', JSON.stringify(rows));
    const entriesForExport = newEntries.map(e => ({
      barcode: e.barcode, name: e.name,
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

  function setStatus(msg, isError = false) {
    const el = document.getElementById('purStatus');
    if (!el) return;
    el.textContent = msg;
    el.className = 'pur-status' + (isError ? ' error' : '');
  }

  function escapeAttr(s) {
    return String(s).replace(/&/g,'&amp;').replace(/"/g,'&quot;').replace(/</g,'&lt;');
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

- [ ] **Step 2: Add CSS**

Append to `static/css/purchase.css`:

```css
.pur-newbox{background:#0d0f1a;border:1px solid #2d3148;border-radius:8px;padding:12px;flex-shrink:0;max-height:40%;overflow:auto}
.pur-newbox-hd{font-size:11px;font-weight:700;color:#fbbf24;text-transform:uppercase;margin-bottom:8px}
.pur-supplier{display:flex;gap:10px;align-items:center;font-size:12px;color:#94a3b8;margin-bottom:10px;flex-wrap:wrap}
.pur-inp{background:#1a1d27;border:1px solid #2d3148;border-radius:4px;color:#e2e8f0;font-size:13px;padding:4px 8px;font-family:inherit;min-width:120px}
.pur-inp:focus{outline:none;border-color:#4f46e5}
.pur-new-row{display:flex;align-items:center;gap:8px;padding:4px 0;font-size:13px;color:#e2e8f0;flex-wrap:wrap}
.pur-new-bc{color:#fbbf24;font-family:"Cascadia Code","Consolas",monospace;min-width:140px}
.pur-new-mod,.pur-new-del{font-size:12px;padding:3px 10px;border-radius:4px;cursor:pointer;border:1px solid;background:transparent}
.pur-new-mod{border-color:#4f46e5;color:#818cf8}
.pur-new-mod:hover{background:#1e1b4b}
.pur-new-del{border-color:#7f1d1d;color:#f87171}
.pur-new-del:hover{background:#450a0a}
.pur-new-correct{width:100%}
```

- [ ] **Step 3: Commit**

```bash
git add static/js/purchase.js static/css/purchase.css
git commit -m "feat: 采购订单 v2 前端（双文件 + 新条码处理 + zip 下载）"
```

---

## Task 5: Manual verification via dev server

**Files:** none (runtime smoke test)

- [ ] **Step 1: Start server**

`python server.py`

- [ ] **Step 2: Prepare test inputs**

Use a real supplier Excel + a real `stockpile*.csv` that overlaps partially.

- [ ] **Step 3: Verify end-to-end**

1. Open 采购订单 tab, drop both files at once
2. Confirm:
   - 采购订单 list renders as before
   - "新条码处理" panel appears with the correct barcodes (diff of supplier ∖ system)
   - Top 供应商 ID / 名称 inputs work
   - Per-row 品名 input works
   - "修改" button focuses 品名 input
   - "删除" → input corrected barcode → row in 采购订单 updates, list shrinks (or grows if corrected barcode still missing)
   - 下载 全部 button stays disabled until all required fields filled
3. Download zip, open locally, verify:
   - Contains 采购订单YYYYMMDD.xlsx with "导入信息" column intact
   - Contains 产品信息导入模板.csv (GBK) with correct rows
4. Test with a supplier where all barcodes already in system → new-barcode panel hidden, zip has only xlsx

- [ ] **Step 4: Report results**

Note any regressions to main page / scroll behavior.

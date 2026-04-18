# Purchase Order v2 — System Export Compare & New-Barcode Template

**Date:** 2026-04-18
**Branch:** feature/purchase-order (continued)
**Status:** Approved

## Overview

Extends the existing 采购订单 page. Instead of uploading one supplier Excel, the user uploads the supplier Excel **together with** a system export CSV (file name starts with `stockpile`). The app compares barcodes, and for any barcode that is in the supplier file but not the system export, the user fills in missing fields inline; those new barcodes are exported as a `产品信息导入模板.csv`. The download button returns a single zip containing both the 采购订单 xlsx and (when applicable) the template CSV.

## User Flow

1. User opens the "采购订单" tab
2. Drops or selects **two files at once**: supplier `.xlsx` + system export `.csv` (filename starts with `stockpile`)
3. Frontend posts both files to `/purchase/process`; backend parses supplier rows, parses stockpile barcodes, computes the list of new barcodes (supplier ∖ system, deduped, preserving first-occurrence order)
4. Existing 采购订单 area renders formatted rows (red rows for >2-decimal prices, editable — unchanged)
5. **New section "新条码处理" appears iff `new_barcodes` is non-empty**
   - Top: one `供应商 ID` + `供应商名称` input pair (batch default applied to every new-barcode row)
   - Per new-barcode row: barcode (read-only) + `品名` text input + `修改` (focus 品名) + `删除` button
6. **"删除"** on a new-barcode row → row turns into a single `<input>`; user types the corrected barcode and presses Enter / blur:
   - Purchase-order row with the old barcode updates its barcode to the corrected value (formatted string rebuilds)
   - Entry removed from new-barcode list
   - If corrected barcode is still missing from `system_barcodes`, a fresh new-barcode entry is appended to the bottom of the list
7. User clicks "一键复制" — copies the formatted purchase-order text (unchanged behavior)
8. User clicks "下载全部" — zip download `采购订单YYYYMMDD.zip`

## Input Formats

### Supplier Excel (unchanged from v1)
| Column | Index | Field |
|--------|-------|-------|
| 1st | 0 | Barcode |
| 3rd | 2 | Price |
| 6th | 5 | Quantity |

### System Export CSV (new)
- Single file, name starts with `stockpile` (case-insensitive)
- Encoding: UTF-8 first, fall back to `CONFIG.csv_fallback_encoding` (GBK) — mirrors `update_location.py:21-23`
- Row 1 = header, data starts row 2
- Column index 3 (4th column) = barcode
- Only this column is used

### Template CSV (project-internal, not uploaded)
- Path: `static/templates/产品信息导入模板.csv`
- Encoding: GBK
- 1 header row
- Columns of interest (1-based → 0-based):
  - Col 1 → idx 0: 型号 (auto = barcode)
  - Col 2 → idx 1: 唯一码 (auto = barcode)
  - Col 4 → idx 3: 品名 (manual)
  - Col 5 → idx 4: 品名 — 铭牌上的品名 (manual, same value as 品名)
  - Col 11 → idx 10: 条形码 (auto = barcode)
  - Col 39 → idx 38: 供应商 ID (manual, batch)
  - Col 40 → idx 39: 供应商名称 (manual, batch)
  - All other columns: empty string

## Output

**Zip file**: `采购订单YYYYMMDD.zip` (one date per download)
- Always contains: `采购订单YYYYMMDD.xlsx` (existing build logic, unchanged)
- Contains iff new-barcode list is non-empty: `产品信息导入模板.csv` (original filename, no date suffix)

Template CSV body: header row copied verbatim from the template; one data row per new-barcode entry.

## Validation & Button-Enable Rules

| Situation | Behaviour |
|-----------|-----------|
| User uploaded < 2 files, or not exactly 1 stockpile-prefixed file | Error status, no processing |
| Any supplier row still has price > 2 decimals | Copy/download disabled (existing v1 rule) |
| new_barcodes non-empty, and (supplier_id empty OR supplier_name empty OR any 品名 empty) | Download disabled, status explains what's missing |
| new_barcodes empty | Only purchase-order xlsx in zip |

Copy button rule unchanged (blocked only by flagged prices; doesn't depend on new-barcode completeness, since copy is only the purchase-order text).

## Architecture

### New Files
| File | Purpose |
|------|---------|
| `static/templates/产品信息导入模板.csv` | Read-only template, copied from user's desktop |

### Modified Files
| File | Change |
|------|--------|
| `purchase_service.py` | Add `parse_stockpile_csv`, `find_new_barcodes`, `build_template_csv`, `build_zip` |
| `routes_purchase.py` | `/process` accepts 2 files and returns `system_barcodes` + `new_barcodes`; `/export` accepts `new_entries` JSON and returns zip |
| `static/js/purchase.js` | Multi-file upload, new-barcode UI, modify/delete logic, zip download |
| `static/css/purchase.css` | Styles for 新条码处理 area |

### Backend Function Signatures

```python
def parse_stockpile_csv(file_bytes: bytes) -> set[str]:
    """Decode as GBK (fallback UTF-8), skip header, return column-4 barcodes as set of stripped strings."""

def find_new_barcodes(rows: list[PurchaseRow], system_set: set[str]) -> list[str]:
    """Return barcodes from rows that are not in system_set, deduped, first-occurrence order."""

def build_template_csv(
    new_entries: list[dict],
    template_path: str = "static/templates/产品信息导入模板.csv",
) -> bytes:
    """
    new_entries items: {"barcode": str, "name": str, "supplier_id": str, "supplier_name": str}
    Returns GBK-encoded CSV: original header + one row per entry.
    Fields by 0-based index: 0=barcode, 1=barcode, 3=name, 4=name, 10=barcode, 38=supplier_id, 39=supplier_name; rest=''.
    Column width = len(header_columns).
    """

def build_zip(
    purchase_xlsx: bytes,
    template_csv: bytes | None,
    date_str: str,  # "YYYYMMDD"
) -> bytes:
    """Create in-memory zip: 采购订单{date}.xlsx always; 产品信息导入模板.csv if template_csv not None."""
```

### Route Contracts

**POST `/purchase/process`**
- Body: `multipart/form-data` with `files` (repeated)
- Backend classifies by filename (case-insensitive `startswith('stockpile')`)
- Require: 1 stockpile + 1 non-stockpile; else return `{"ok": false, "msg": "..."}`
- Response on success:
  ```json
  {
    "ok": true,
    "rows": [ {barcode, price, quantity, price_flagged, formatted}, ... ],
    "system_barcodes": ["...", "..."],
    "new_barcodes": ["...", "..."]
  }
  ```

**POST `/purchase/export`**
- Body: `multipart/form-data`
  - `file`: supplier xlsx (frontend re-uploads)
  - `rows`: JSON string (current purchase-order rows after edits)
  - `new_entries`: JSON string (possibly empty list)
- Response: `application/zip`, `Content-Disposition: attachment; filename=采购订单YYYYMMDD.zip`

### Frontend State (`purchase.js`)
```js
let storedSupplierFile = null;
let systemBarcodes = new Set();     // populated from /process response
let rows = [];                       // purchase-order rows (existing)
let newEntries = [];                 // [{barcode, name}] — supplier info held separately
let supplierInfo = { id: '', name: '' };
```

### "Delete" interaction (frontend-only)
1. Click 删除 on new-barcode row with barcode `B_old`
2. Row DOM is replaced with an inline `<input placeholder="输入正确条码">`
3. On Enter or blur with non-empty value `B_new`:
   - Find `row` in `rows` where `row.barcode === B_old`; set `row.barcode = B_new`; rebuild `row.formatted`
   - Re-render purchase-order list (that row updates)
   - Remove current entry from `newEntries`
   - If `!systemBarcodes.has(B_new)` and `B_new` not already in `newEntries` → push `{barcode: B_new, name: ''}`
   - Re-render new-barcode list
4. On Escape: restore the original row
5. Empty input on Enter: restore the original row (no change)

## UI Layout

```
┌──────────────────────────────────────────────────────────┐
│ [拖拽区] 拖入或点击 — 供应商 Excel + 系统 stockpile.csv   │
├──────────────────────────────────────────────────────────┤
│ [采购订单格式化区]  (现有)                                │
│  1234567890123,9.48,,144                                  │
│  ...                                                      │
├──────────────────────────────────────────────────────────┤
│ [新条码处理] (仅当有新条码)                               │
│  供应商 ID: [____]   供应商名称: [____]                   │
│  · 1234567890123  品名: [____]         [修改] [删除]       │
│  · 9876543210987  品名: [____]         [修改] [删除]       │
├──────────────────────────────────────────────────────────┤
│  状态提示           [一键复制]  [下载全部]                 │
└──────────────────────────────────────────────────────────┘
```

## Testing

- **`parse_stockpile_csv`**: header-only → empty set; multiple rows → set of col-4 barcodes; GBK-encoded bytes decode correctly; row with missing col-4 → skip
- **`find_new_barcodes`**: empty system → all rows returned; some overlap → only non-system; duplicates in supplier → deduped; ordering preserved
- **`build_template_csv`**: single entry → 2 lines (header + 1); correct indices populated; correct number of columns; GBK decodable
- **`build_zip`**: template None → zip has only xlsx; template bytes → zip has both with correct names
- **Route `/purchase/process`**: wrong file count → 400-ish JSON error; classify by filename; returns all three arrays
- **Route `/purchase/export`**: with new_entries=[] → single-file zip; with entries → dual-file zip
- **Frontend**: visual test via dev server — upload 2 files, verify new-barcode area, try 修改 and 删除 with a barcode already in system (list should shrink) and one not in system (list should re-add), download zip and inspect contents

## Out of Scope
- Uploading multiple stockpile files / merge
- Validating barcode format or supplier id format
- Per-row supplier override (batch only)
- Editing already-in-system rows (untouched, only flagged as "new" or not)
- Template upload override (fixed project-internal template)

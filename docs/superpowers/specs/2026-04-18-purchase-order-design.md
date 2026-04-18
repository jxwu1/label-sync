# Purchase Order — Design Spec

**Date:** 2026-04-18
**Branch:** feature/purchase-order
**Status:** Approved

## Overview

A new "采购订单" tab that accepts a supplier Excel file, appends a "导入信息" column to it with each row formatted as `barcode,price,,quantity`, displays the results in a copyable list, and returns the modified Excel file as a download.

## User Flow

1. User opens the "采购订单" tab
2. Drags or selects an Excel file
3. App parses the file and displays each row's formatted string
4. Rows with price > 2 decimal places are highlighted red — user corrects the price inline before copying/downloading
5. User clicks "一键复制" to copy all formatted strings to clipboard
6. User clicks "下载采购订单" to download the original Excel with a new "导入信息" column appended (`采购订单YYYYMMDD.xlsx`)

## Input Format

| Column | Index | Field | Notes |
|--------|-------|-------|-------|
| 1st | 0 | Barcode | String, copied as-is |
| 3rd | 2 | Price | Decimal; flag if > 2 decimal places |
| 6th | 5 | Quantity | Integer |
| Others | — | — | Preserved in output, not used in formatting |

- Row 0 is a header row, always skipped for processing.
- All data rows are processed.

## Output Format

### Formatted string per row
```
barcode,price,,quantity
```
Example: `1234567890123,9.48,,144`

- Price rendered with exactly 2 decimal places (`9.48`, `12.00`)
- Rows with price > 2 decimal places are flagged red; copy and download are blocked until all fixed

### Excel download
- Original file with one new column appended at the end
- New column header: `导入信息`
- Each cell contains the formatted string for that row
- Filename: `采购订单YYYYMMDD.xlsx` (date only, no time)

## Architecture

### New Files

| File | Purpose |
|------|---------|
| `purchase_service.py` | Parse input Excel, validate price precision, format rows, build output Excel bytes |
| `routes_purchase.py` | Flask Blueprint: POST `/purchase/process`, POST `/purchase/export` |
| `static/js/purchase.js` | Upload, display editable results, copy, download |
| `static/css/purchase.css` | Styles (reuses CSS variables from index.css) |

### Changes to Existing Files

- `routes.py` — register `purchase_bp`
- `templates/index.html` — add "采购订单" nav item and `#pagePurchase` div

### No Changes To

Config, requirements, state, or any other existing service.

## Data Model

```python
@dataclass
class PurchaseRow:
    barcode: str
    price_raw: str        # original string from cell, for round-trip fidelity
    price: float          # parsed float
    quantity: int
    price_flagged: bool   # True if price_raw has > 2 decimal places

    def formatted(self) -> str:
        return f"{self.barcode},{self.price:.2f},,{self.quantity}"
```

## Validation & Error Handling

| Situation | Behaviour |
|-----------|-----------|
| Price has > 2 decimal places | Row shown in red; copy and download blocked until all fixed |
| Missing value in barcode/price/quantity | Row shown in red with empty field |
| File parse error | Error message shown, no results |
| No file selected | Process button disabled |

## API Routes

**POST `/purchase/process`**
- Body: `multipart/form-data` with `file`
- Response: `{"ok": true, "rows": [{"barcode": "...", "price": 9.48, "quantity": 144, "price_flagged": false, "formatted": "...", "row_index": 1}, ...]}`

**POST `/purchase/export`**
- Body: JSON `{"rows": [...], "original_filename": "..."}`
- Response: Excel file download (`采购订单YYYYMMDD.xlsx`)
- Backend re-reads the uploaded file (stored temporarily in session or re-sent as base64) and appends the "导入信息" column

> Implementation note: to avoid re-upload, the process route stores the parsed workbook in a server-side temp file keyed by a session token returned in the process response. Export reads that temp file, appends the column, and streams it back.

## UI Layout

```
┌──────────────────────────────────────────────────────┐
│ nav: [标签处理] [重复检查] [采购订单 ←]               │
├──────────────────────────────────────────────────────┤
│  拖入或点击选择 Excel 文件                             │
│  ─────────────────────────────────────────────────   │
│  1234567890123,9.48,,144                              │
│  9876543210987,12.00,,36                              │
│  [红色行] 1111111111111,9.4812,,60  ← 价格超2位小数   │
│  ...                                                  │
│  ─────────────────────────────────────────────────   │
│                    [一键复制]  [下载采购订单]          │
└──────────────────────────────────────────────────────┘
```

## Out of Scope

- Validating barcode format
- Any integration with existing inventory/label processing
- Multi-file upload

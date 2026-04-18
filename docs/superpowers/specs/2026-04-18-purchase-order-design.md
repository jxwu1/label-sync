# Purchase Order — Design Spec

**Date:** 2026-04-18
**Branch:** feature/purchase-order
**Status:** Approved

## Overview

A new "采购订单" tab that accepts a supplier Excel file, formats each line as `barcode,price,,quantity`, shows the result in a copyable text area, and exports a clean purchase-order Excel file.

## User Flow

1. User opens the "采购订单" tab
2. Drags or selects an Excel file
3. App parses the file and displays the formatted lines in a text area
4. Rows with price > 2 decimal places are highlighted red — user corrects them inline before copying/downloading
5. User clicks "一键复制" to copy all lines to clipboard
6. User clicks "下载采购订单" to download `采购订单YYYYMMDD.xlsx`

## Input Format

| Column | Index | Field | Notes |
|--------|-------|-------|-------|
| 1st | 0 | Barcode | String, copied as-is |
| 3rd | 2 | Price | Decimal; flag if > 2 decimal places |
| 6th | 5 | Quantity | Integer |
| Others | — | — | Ignored |

- Row 0 is a header row and is always skipped.
- All other rows are processed regardless of content.

## Output Format

### Formatted text (one line per item)
```
barcode,price,,quantity
```
Example: `1234567890123,9.48,,144`

- Price always rendered with exactly 2 decimal places (e.g. `9.48`, `12.00`)
- Rows flagged for price precision are shown red and blocked from copy/download until fixed

### Excel file
- Filename: `采购订单YYYYMMDD.xlsx` (date only, no time)
- Sheet: one sheet, no name requirement
- Columns: `Barcode` | `价格` | `折扣` | `数量`
- Discount column is always empty

## Architecture

### New Files

| File | Purpose |
|------|---------|
| `purchase_service.py` | Parse input Excel, validate price precision, format rows, build output Excel |
| `routes_purchase.py` | Flask Blueprint: POST `/purchase/process` |
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
    price: float
    quantity: int
    price_flagged: bool   # True if raw price string has > 2 decimal places
```

## Validation & Error Handling

| Situation | Behaviour |
|-----------|-----------|
| Price has > 2 decimal places | Row shown in red; copy and download blocked until all fixed |
| Missing value in required column | Row shown in red with empty field |
| File parse error | Error message shown, no results |
| No file selected | Process button disabled |

## API Route

**POST `/purchase/process`**
- Body: `multipart/form-data` with `file` field
- Response: `{"ok": true, "rows": [{"barcode": "...", "price": 9.48, "quantity": 144, "price_flagged": false}, ...]}`
- Download: Triggered from frontend via POST `/purchase/export` with JSON rows

## UI Layout

```
┌──────────────────────────────────────────────────────┐
│ nav: [标签处理] [重复检查] [采购订单 ←]               │
├──────────────────────────────────────────────────────┤
│  拖入或点击选择 Excel 文件                             │
│  ─────────────────────────────────────────────────   │
│  1234567890123,9.48,,144                              │
│  9876543210987,12.00,,36    ← 红色行：价格小数超2位   │
│  ...                                                  │
│  ─────────────────────────────────────────────────   │
│                    [一键复制]  [下载采购订单]          │
└──────────────────────────────────────────────────────┘
```

## Out of Scope

- Saving history of processed files
- Validating barcode format
- Any integration with existing inventory/label processing

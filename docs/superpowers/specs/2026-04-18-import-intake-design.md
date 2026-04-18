# Import Intake — Image Recognition Design

**Date:** 2026-04-18
**Branch:** feature/import-intake
**Status:** Approved

## Overview

A new "进货识别" tab in the existing app that lets users upload photos of supplier invoices (possibly in Greek, varying layouts), sends them to Gemini Vision for structured extraction, presents an editable review table, and exports an Excel file.

## User Flow

1. User opens the "进货识别" tab in the existing nav
2. Uploads one or more photos (drag-and-drop or click)
3. Clicks "开始识别" — backend calls Gemini Vision
4. Editable table appears on the right with recognized results
5. User reviews: corrects red (null) cells, checks yellow (suspect barcode) rows
6. Clicks "导出 Excel" — downloads `import_YYYYMMDD_HHMMSS.xlsx`

## Architecture

### New Files

| File | Purpose |
|------|---------|
| `routes_import.py` | Flask Blueprint: upload, recognize, export routes |
| `import_service.py` | Gemini Vision API call + result parsing + unit price calc |
| `templates/import.html` | Page template |
| `static/js/import.js` | Front-end table editing, validation, export trigger |
| `static/css/import.css` | Styles (reuses CSS variables from index.css) |

### Changes to Existing Files

- `config.py` — add `gemini_api_key: str = ""` (read from env `GEMINI_API_KEY`)
- `routes.py` — register `import_bp`
- `templates/index.html` — add "进货识别" nav item, add page div
- `requirements.txt` — add `google-generativeai`

### No Changes To

All existing routes, services, state, schemas — untouched.

## UI Layout

- **Nav:** new "进货识别" tab alongside "标签处理" and "重复检查"
- **Left panel:** image upload drop zone + thumbnail list of uploaded images
- **Right panel:** editable results table (appears after recognition)

```
┌─────────────────────────────────────────────────┐
│ nav: [标签处理] [重复检查] [进货识别 ←]           │
├───────────────────┬─────────────────────────────┤
│ 📷 拖入图片        │ Barcode  数量  单价€  总价€  │
│ ─────────────── │ ──────────────────────────── │
│ [thumb1.jpg] ✕  │ 1234567  12    €25.00  €300  │
│ [thumb2.jpg] ✕  │ 9876543   8    €42.50  €340  │
│                   │ [红色行 — null待填]           │
│ [开始识别]        │                              │
│                   │              [导出 Excel]    │
└───────────────────┴─────────────────────────────┘
```

## Gemini Integration

### Prompt Strategy

- Send all images in a single API call (base64 encoded)
- System instruction: extract barcode + quantity + total price regardless of language (Greek, English, etc.) and layout
- Return strict JSON: `[{"barcode": "...", "quantity": N, "total_price": N.NN}, ...]`
- If a field is uncertain, return `null` — do not guess
- Merge results from multiple images; if the same barcode appears in more than one image, keep both rows — the user resolves duplicates manually in the table

### Unit Price Calculation

```python
unit_price = total_price / quantity  # done in import_service.py
```

If `total_price` or `quantity` is null, `unit_price` is also null.

## Data Model (in-memory, per session)

```python
@dataclass
class ImportItem:
    barcode: str | None
    quantity: int | None
    total_price: float | None
    unit_price: float | None  # computed
    flagged: bool             # True if any field was null from Gemini
```

## Error Handling

| Situation | Behaviour |
|-----------|-----------|
| Gemini returns null for a field | Cell marked red in table; export blocked until filled |
| Barcode wrong length / format | Cell marked yellow; export allowed with warning |
| Gemini API error / timeout | Show error message, allow retry |
| No images uploaded | "开始识别" button disabled |
| All cells valid | Export enabled |

## Export Route

Export is triggered via `POST /import/export` — backend generates the xlsx in memory and returns it as a file download (same pattern as existing `/download` route). No client-side generation.

## Excel Output

- Filename: `import_YYYYMMDD_HHMMSS.xlsx`
- Columns: `Barcode`, `数量`, `单价(€)`, `总价(€)`
- One row per item, sorted by barcode

## Out of Scope

- Supplier profile configuration (Gemini adapts to layout automatically)
- Recognition history / audit log
- Barcode matching against existing inventory
- Batch naming or job management

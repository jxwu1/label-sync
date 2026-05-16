# Import Audit (after Phase 2)

Generated: 2026-05-16, branch refactor/p2-app-package

Root .py files remaining: 2 (was 55 before Phase 2)

```
  server.py
  wsgi.py
```

---

## app/ package structure

```
  app/__init__.py
  app/config.py
  app/importers/__init__.py
  app/importers/inventory.py
  app/importers/product_master.py
  app/models.py
  app/parsers/__init__.py
  app/parsers/erp_category.py
  app/parsers/location.py
  app/parsers/xls_html.py
  app/repositories/__init__.py
  app/repositories/input.py
  app/repositories/output.py
  app/repositories/stockpile_db.py
  app/repositories/transfer.py
  app/routes/__init__.py
  app/routes/analytics.py
  app/routes/attendance.py
  app/routes/collab.py
  app/routes/data_quality.py
  app/routes/foreign_customers.py
  app/routes/history.py
  app/routes/inventory.py
  app/routes/monthly_summary.py
  app/routes/pages_tasks.py
  app/routes/purchase.py
  app/routes/query.py
  app/routes/recent_changes.py
  app/routes/scan_history.py
  app/routes/stockpile.py
  app/routes/transfer.py
  app/schemas.py
  app/services/__init__.py
  app/services/analytics.py
  app/services/attendance.py
  app/services/attendance_report.py
  app/services/backtest.py
  app/services/barcode.py
  app/services/data_quality.py
  app/services/foreign_customer.py
  app/services/foreign_customer_report.py
  app/services/history.py
  app/services/message.py
  app/services/monthly_summary.py
  app/services/purchase.py
  app/services/query.py
  app/services/recent_changes.py
  app/services/scan_history.py
  app/services/storage.py
  app/services/task.py
  app/state.py
  app/utils/__init__.py
  app/utils/categorizer.py
  app/utils/customer_classifier.py
  app/utils/file_io.py
  app/utils/forecast_data.py
  app/utils/path_safety.py
  app/utils/response_builder.py
  app/utils/route_helpers.py
```

## Verification: any leftover old-style imports?

**✓ None.** All imports updated to app.* paths.


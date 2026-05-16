# Import Audit (before Phase 2)

Generated: 2026-05-16, branch refactor/p2-app-package, HEAD=$(git rev-parse --short HEAD)

Root modules: 55

Format: `MODULE_NAME (importer_count)` followed by `  - file:line` for each in-edge.

---

## `analytics_service` (20 importers)
  - routes_analytics.py:14
  - tests/test_analytics_service.py:84
  - tests/test_analytics_service.py:94
  - tests/test_analytics_service.py:104
  - tests/test_analytics_service.py:112
  - tests/test_analytics_service.py:120
  - tests/test_analytics_service.py:132
  - tests/test_analytics_service.py:149
  - tests/test_analytics_service.py:160
  - tests/test_analytics_service.py:169
  - tests/test_analytics_service.py:178
  - tests/test_analytics_service.py:186
  - tests/test_analytics_service.py:194
  - tests/test_analytics_service.py:201
  - tests/test_analytics_service.py:213
  - tests/test_analytics_service.py:222
  - tests/test_analytics_service.py:239
  - tests/test_analytics_service.py:251
  - tests/test_analytics_service.py:276
  - tools/recompute_categories.py:21

## `attendance_report_service` (4 importers)
  - foreign_customer_report_service.py:16
  - foreign_customer_report_service.py:18
  - routes_attendance.py:10
  - tests/test_attendance_report_service.py:6

## `attendance_service` (6 importers)
  - attendance_report_service.py:22
  - routes_attendance.py:11
  - e2e/conftest.py:40
  - tests/test_attendance_report_service.py:7
  - tests/test_attendance_routes.py:14
  - tests/test_attendance_service.py:6

## `backtest_service` (45 importers)
  - routes_analytics.py:147
  - routes_analytics.py:212
  - tests/test_backtest_service.py:21
  - tests/test_backtest_service.py:30
  - tests/test_backtest_service.py:35
  - tests/test_backtest_service.py:40
  - tests/test_backtest_service.py:45
  - tests/test_backtest_service.py:50
  - tests/test_backtest_service.py:55
  - tests/test_backtest_service.py:60
  - tests/test_backtest_service.py:65
  - tests/test_backtest_service.py:70
  - tests/test_backtest_service.py:77
  - tests/test_backtest_service.py:86
  - tests/test_backtest_service.py:93
  - tests/test_backtest_service.py:103
  - tests/test_backtest_service.py:112
  - tests/test_backtest_service.py:120
  - tests/test_backtest_service.py:129
  - tests/test_backtest_service.py:136
  - tests/test_backtest_service.py:143
  - tests/test_backtest_service.py:150
  - tests/test_backtest_service.py:161
  - tests/test_backtest_service.py:170
  - tests/test_backtest_service.py:177
  - tests/test_backtest_service.py:185
  - tests/test_backtest_service.py:194
  - tests/test_backtest_service.py:201
  - tests/test_backtest_service.py:215
  - tests/test_backtest_service.py:222
  - tests/test_backtest_service.py:230
  - tests/test_backtest_service.py:238
  - tests/test_backtest_service.py:295
  - tests/test_backtest_service.py:307
  - tests/test_backtest_service.py:321
  - tests/test_backtest_service.py:334
  - tests/test_backtest_service.py:362
  - tests/test_backtest_service.py:390
  - tests/test_backtest_service.py:417
  - tests/test_backtest_service.py:439
  - tests/test_backtest_service.py:449
  - tests/test_backtest_service.py:464
  - tests/test_backtest_service.py:497
  - tests/test_backtest_service.py:535
  - tests/test_backtest_service.py:541

## `barcode_service` (3 importers)
  - routes_pages_tasks.py:6
  - tests/test_barcode_service.py:9
  - tests/test_pages_tasks_routes.py:13

## `categorizer` (39 importers)
  - analytics_service.py:29
  - backtest_service.py:272
  - forecast_data.py:173
  - tests/test_categorizer.py:61
  - tests/test_categorizer.py:66
  - tests/test_categorizer.py:74
  - tests/test_categorizer.py:83
  - tests/test_categorizer.py:94
  - tests/test_categorizer.py:117
  - tests/test_categorizer.py:130
  - tests/test_categorizer.py:138
  - tests/test_categorizer.py:150
  - tests/test_categorizer.py:159
  - tests/test_categorizer.py:164
  - tests/test_categorizer.py:179
  - tests/test_categorizer.py:184
  - tests/test_categorizer.py:189
  - tests/test_categorizer.py:194
  - tests/test_categorizer.py:201
  - tests/test_categorizer.py:207
  - tests/test_categorizer.py:213
  - tests/test_categorizer.py:220
  - tests/test_categorizer.py:226
  - tests/test_categorizer.py:232
  - tests/test_categorizer.py:283
  - tests/test_categorizer.py:294
  - tests/test_categorizer.py:303
  - tests/test_categorizer.py:312
  - tests/test_categorizer.py:323
  - tests/test_categorizer.py:331
  - tests/test_categorizer.py:340
  - tests/test_categorizer.py:345
  - tests/test_categorizer.py:352
  - tests/test_categorizer.py:360
  - tests/test_categorizer.py:369
  - tests/test_categorizer.py:377
  - tests/test_categorizer.py:386
  - tests/test_categorizer.py:393
  - tests/test_categorizer.py:400

## `config` (15 importers)
  - file_io.py:8
  - input_repository.py:3
  - models.py:39
  - routes.py:1
  - scan_history_service.py:9
  - server.py:8
  - state.py:4
  - stockpile_db.py:18
  - task_service.py:9
  - e2e/conftest.py:35
  - phase_scripts/update_location.py:10
  - phase_scripts/update_location_phase1.py:8
  - phase_scripts/update_location_phase2.py:5
  - tests/test_history_service.py:20
  - tools/wipe_events.py:36

## `customer_classifier` (2 importers)
  - inventory_importer.py:23
  - tests/test_customer_classifier.py:6

## `data_quality_service` (2 importers)
  - routes_data_quality.py:6
  - tests/test_data_quality_service.py:10

## `erp_category_parser` (2 importers)
  - inventory_importer.py:24
  - tests/test_erp_category_parser.py:9

## `file_io` (6 importers)
  - barcode_service.py:4
  - data_quality_service.py:214
  - routes_stockpile.py:8
  - storage_service.py:6
  - phase_scripts/update_location.py:11
  - phase_scripts/update_location_phase2.py:6

## `forecast_data` (43 importers)
  - backtest_service.py:273
  - tests/test_forecast_data.py:73
  - tests/test_forecast_data.py:80
  - tests/test_forecast_data.py:89
  - tests/test_forecast_data.py:98
  - tests/test_forecast_data.py:108
  - tests/test_forecast_data.py:115
  - tests/test_forecast_data.py:123
  - tests/test_forecast_data.py:135
  - tests/test_forecast_data.py:144
  - tests/test_forecast_data.py:151
  - tests/test_forecast_data.py:158
  - tests/test_forecast_data.py:167
  - tests/test_forecast_data.py:179
  - tests/test_forecast_data.py:184
  - tests/test_forecast_data.py:189
  - tests/test_forecast_data.py:195
  - tests/test_forecast_data.py:206
  - tests/test_forecast_data.py:213
  - tests/test_forecast_data.py:220
  - tests/test_forecast_data.py:229
  - tests/test_forecast_data.py:235
  - tests/test_forecast_data.py:242
  - tests/test_forecast_data.py:251
  - tests/test_forecast_data.py:259
  - tests/test_forecast_data.py:309
  - tests/test_forecast_data.py:320
  - tests/test_forecast_data.py:327
  - tests/test_forecast_data.py:337
  - tests/test_forecast_data.py:349
  - tests/test_forecast_data.py:360
  - tests/test_forecast_data.py:375
  - tests/test_forecast_data.py:393
  - tests/test_forecast_data.py:404
  - tests/test_forecast_data.py:413
  - tests/test_forecast_data.py:423
  - tests/test_forecast_data.py:437
  - tests/test_forecast_data.py:442
  - tests/test_forecast_data.py:449
  - tests/test_forecast_data.py:456
  - tests/test_forecast_data.py:462
  - tests/test_forecast_data.py:471
  - tests/test_forecast_data.py:478

## `foreign_customer_report_service` (1 importer)
  - routes_foreign_customers.py:17

## `foreign_customer_service` (3 importers)
  - foreign_customer_report_service.py:17
  - routes_foreign_customers.py:18
  - tests/test_foreign_customer_service.py:9

## `history_service` (30 importers)
  - routes_history.py:3
  - tests/test_history_service.py:72
  - tests/test_history_service.py:92
  - tests/test_history_service.py:108
  - tests/test_history_service.py:114
  - tests/test_history_service.py:121
  - tests/test_history_service.py:141
  - tests/test_history_service.py:152
  - tests/test_history_service.py:162
  - tests/test_history_service.py:168
  - tests/test_history_service.py:180
  - tests/test_history_service.py:208
  - tests/test_history_service.py:220
  - tests/test_history_service.py:242
  - tests/test_history_service.py:252
  - tests/test_history_service.py:266
  - tests/test_history_service.py:322
  - tests/test_history_service.py:329
  - tests/test_history_service.py:345
  - tests/test_history_service.py:360
  - tests/test_history_service.py:383
  - tests/test_history_service.py:398
  - tests/test_history_service.py:405
  - tests/test_history_service.py:415
  - tests/test_history_service.py:425
  - tests/test_history_service.py:436
  - tests/test_history_service.py:447
  - tests/test_history_service.py:464
  - tests/test_history_service.py:489
  - tests/test_history_service.py:510

## `input_repository` (1 importer)
  - query_service.py:7

## `inventory_importer` (5 importers)
  - product_master_importer.py:24
  - routes_inventory.py:26
  - etl/parquet_importer.py:22
  - tests/test_inventory_importer.py:15
  - tools/inventory_admin.py:32

## `location_parser` (6 importers)
  - barcode_service.py:55
  - history_service.py:15
  - stockpile_db.py:19
  - phase_scripts/update_location_phase2.py:7
  - tests/test_location_parser.py:9
  - tests/test_scripts.py:10

## `message_service` (2 importers)
  - routes_collab.py:4
  - tests/test_collab_routes.py:8

## `models` (41 importers)
  - analytics_service.py:30
  - backtest_service.py:359
  - backtest_service.py:456
  - categorizer.py:28
  - data_quality_service.py:20
  - forecast_data.py:22
  - forecast_data.py:260
  - foreign_customer_service.py:15
  - history_service.py:16
  - inventory_importer.py:25
  - product_master_importer.py:30
  - purchase_service.py:147
  - recent_changes_service.py:13
  - routes_analytics.py:16
  - routes_analytics.py:177
  - routes_analytics.py:236
  - routes_inventory.py:31
  - stockpile_db.py:20
  - alembic/env.py:7
  - tests/test_analytics_service.py:20
  - tests/test_analytics_service.py:262
  - tests/test_analytics_service.py:277
  - tests/test_backtest_service.py:14
  - tests/test_categorizer.py:18
  - tests/test_forecast_data.py:24
  - tests/test_forecast_data.py:270
  - tests/test_foreign_customer_routes.py:11
  - tests/test_foreign_customer_service.py:18
  - tests/test_inventory_importer.py:23
  - tests/test_parquet_importer.py:23
  - tests/test_product_master_importer.py:12
  - tests/test_product_master_importer.py:215
  - tests/test_product_master_importer.py:250
  - tests/test_product_master_importer.py:264
  - tests/test_recent_changes_routes.py:12
  - tests/test_recent_changes_service.py:12
  - tests/test_routes_analytics.py:12
  - tests/test_routes_analytics.py:170
  - tests/test_stockpile_locations.py:15
  - tools/inventory_admin.py:33
  - tools/wipe_events.py:37

## `monthly_summary_service` (5 importers)
  - routes_monthly_summary.py:7
  - server.py:5
  - e2e/conftest.py:41
  - tests/test_monthly_summary_routes.py:8
  - tests/test_monthly_summary_service.py:8

## `output_repository` (4 importers)
  - barcode_service.py:5
  - query_service.py:8
  - routes_query.py:4
  - storage_service.py:7

## `path_safety` (5 importers)
  - output_repository.py:3
  - routes_inventory.py:39
  - routes_stockpile.py:9
  - storage_service.py:8
  - transfer_repository.py:3

## `product_master_importer` (2 importers)
  - routes_inventory.py:40
  - tests/test_product_master_importer.py:13

## `purchase_service` (2 importers)
  - routes_purchase.py:8
  - tests/test_purchase_service.py:9

## `query_service` (1 importer)
  - routes_query.py:3

## `recent_changes_service` (2 importers)
  - routes_recent_changes.py:3
  - tests/test_recent_changes_service.py:10

## `response_builder` (3 importers)
  - routes_collab.py:5
  - routes_pages_tasks.py:9
  - routes_transfer.py:5

## `route_helpers` (10 importers)
  - routes_analytics.py:17
  - routes_attendance.py:12
  - routes_collab.py:6
  - routes_foreign_customers.py:19
  - routes_inventory.py:44
  - routes_monthly_summary.py:8
  - routes_pages_tasks.py:10
  - routes_purchase.py:10
  - routes_stockpile.py:10
  - routes_transfer.py:6

## `routes` (2 importers)
  - server.py:9
  - tests/test_routes.py:6

## `routes_analytics` (2 importers)
  - routes.py:2
  - tests/test_routes_analytics.py:13

## `routes_attendance` (2 importers)
  - routes.py:3
  - tests/test_attendance_routes.py:15

## `routes_collab` (2 importers)
  - routes.py:32
  - tests/test_collab_routes.py:9

## `routes_data_quality` (1 importer)
  - routes.py:4

## `routes_foreign_customers` (2 importers)
  - routes.py:5
  - tests/test_foreign_customer_routes.py:12

## `routes_history` (1 importer)
  - routes.py:6

## `routes_inventory` (2 importers)
  - routes.py:7
  - tests/test_inventory_routes.py:13

## `routes_monthly_summary` (2 importers)
  - routes.py:8
  - tests/test_monthly_summary_routes.py:9

## `routes_pages_tasks` (2 importers)
  - routes.py:9
  - tests/test_pages_tasks_routes.py:14

## `routes_purchase` (2 importers)
  - routes.py:10
  - tests/test_purchase_routes.py:9

## `routes_query` (1 importer)
  - routes.py:11

## `routes_recent_changes` (2 importers)
  - routes.py:12
  - tests/test_recent_changes_routes.py:13

## `routes_scan_history` (2 importers)
  - routes.py:13
  - tests/test_scan_history_routes.py:11

## `routes_stockpile` (2 importers)
  - routes.py:14
  - tests/test_stockpile_routes.py:13

## `routes_transfer` (1 importer)
  - routes.py:33

## `scan_history_service` (3 importers)
  - routes_scan_history.py:5
  - tests/test_scan_history_routes.py:10
  - tests/test_scan_history_service.py:8

## `schemas` (8 importers)
  - barcode_service.py:6
  - message_service.py:3
  - response_builder.py:3
  - state.py:5
  - storage_service.py:9
  - tests/test_collab_routes.py:48
  - tests/test_collab_routes.py:58
  - tests/test_pages_tasks_routes.py:15

## `server` (5 importers)
  - wsgi.py:7
  - e2e/conftest.py:65
  - tests/test_history_service.py:288
  - tests/test_history_service.py:300
  - tests/test_history_service.py:309

## `state` (15 importers)
  - barcode_service.py:7
  - message_service.py:4
  - output_repository.py:4
  - query_service.py:13
  - routes_inventory.py:45
  - routes_pages_tasks.py:11
  - routes_stockpile.py:11
  - routes_transfer.py:7
  - server.py:10
  - storage_service.py:10
  - task_service.py:10
  - transfer_repository.py:4
  - phase_scripts/update_location_phase1.py:9
  - phase_scripts/update_location_phase2.py:8
  - tests/test_task_service.py:5

## `stockpile_db` (40 importers)
  - analytics_service.py:28
  - backtest_service.py:358
  - backtest_service.py:455
  - barcode_service.py:3
  - categorizer.py:27
  - data_quality_service.py:19
  - forecast_data.py:21
  - foreign_customer_service.py:14
  - history_service.py:14
  - product_master_importer.py:23
  - purchase_service.py:12
  - recent_changes_service.py:12
  - routes_analytics.py:15
  - routes_inventory.py:25
  - routes_purchase.py:9
  - routes_stockpile.py:7
  - server.py:6
  - storage_service.py:95
  - phase_scripts/update_location.py:9
  - phase_scripts/update_location_phase2.py:9
  - tests/test_analytics_service.py:19
  - tests/test_backtest_service.py:13
  - tests/test_categorizer.py:17
  - tests/test_data_quality_service.py:11
  - tests/test_forecast_data.py:23
  - tests/test_foreign_customer_routes.py:10
  - tests/test_foreign_customer_service.py:8
  - tests/test_history_service.py:29
  - tests/test_history_service.py:465
  - tests/test_history_service.py:490
  - tests/test_inventory_routes.py:12
  - tests/test_models_smoke.py:18
  - tests/test_recent_changes_routes.py:11
  - tests/test_recent_changes_service.py:11
  - tests/test_routes_analytics.py:11
  - tests/test_stockpile_db.py:9
  - tests/test_stockpile_locations.py:14
  - tests/test_stockpile_routes.py:12
  - tools/import_parquet.py:29
  - tools/inventory_admin.py:31

## `storage_service` (4 importers)
  - routes_pages_tasks.py:7
  - routes_transfer.py:4
  - server.py:7
  - task_service.py:22

## `task_service` (2 importers)
  - routes_pages_tasks.py:8
  - tests/test_task_service.py:4

## `transfer_repository` (2 importers)
  - routes_transfer.py:8
  - storage_service.py:11

## `wsgi` (0 importers)
  - (no in-edges in tracked paths — likely entry point or dead code)

## `xls_html_parser` (4 importers)
  - routes_inventory.py:46
  - tests/test_inventory_importer.py:24
  - tests/test_xls_html_parser.py:7
  - tools/inventory_admin.py:34


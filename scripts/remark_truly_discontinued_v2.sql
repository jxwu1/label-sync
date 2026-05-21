-- v2 remark (2026-05-21): 加 rule B (barcode[:-1][-5:]) JOIN + phantom 收纳
--
-- 修复 v1 (2026-05-21 早版) 漏:
--   1. model JOIN 只用 rule A (stockpile.model == snapshot.model), 漏了
--      stockpile.model 是 13 位 barcode 而 snapshot.model 是 5 位短码的 318 个 SKU
--   2. 没把 "无事件 + 不在 snapshot" 的 709 phantom (2019-2020 ERP 迁移残留,
--      用户确认大部分确实停用) 算进去
--
-- 预期: 18,231 -> 19,123 (+892)
--   13,541 zero_no_events
--    4,873 zero_inactive_730d
--      709 phantom_no_event_no_snap

BEGIN;

UPDATE stockpile SET is_truly_discontinued = false WHERE is_truly_discontinued = true;

SELECT 'AFTER_RESET' AS phase, COUNT(*) AS n
FROM stockpile WHERE is_truly_discontinued = true;

WITH latest_snap_date AS (SELECT MAX(snapshot_date) AS d FROM stockpile_inventory_snapshot),
last_events AS (
    SELECT product_barcode,
           MAX(event_at) FILTER (WHERE event_type='sale') AS last_sale,
           MAX(event_at) FILTER (WHERE event_type='purchase') AS last_purchase
    FROM inventory_events GROUP BY product_barcode
),
sku_qty AS (
    SELECT s.product_barcode, MIN(snap.qty_total) AS qty_total
    FROM stockpile s
    JOIN stockpile_inventory_snapshot snap
      ON snap.snapshot_date=(SELECT d FROM latest_snap_date)
      AND (snap.product_model = s.product_model
           OR (LENGTH(s.product_barcode) = 13
               AND snap.product_model = SUBSTRING(s.product_barcode, LENGTH(s.product_barcode)-5, 5)))
    GROUP BY s.product_barcode
),
truly_disc AS (
    SELECT s.product_barcode
    FROM stockpile s
    LEFT JOIN sku_qty q ON q.product_barcode = s.product_barcode
    LEFT JOIN last_events e ON e.product_barcode = s.product_barcode
    WHERE (
        (q.qty_total = 0
         AND (e.last_sale IS NULL OR e.last_sale::date < CURRENT_DATE - INTERVAL '730 days')
         AND (e.last_purchase IS NULL OR e.last_purchase::date < CURRENT_DATE - INTERVAL '730 days'))
        OR
        (q.qty_total IS NULL AND e.last_sale IS NULL AND e.last_purchase IS NULL)
    )
)
UPDATE stockpile s SET is_truly_discontinued = true
WHERE s.product_barcode IN (SELECT product_barcode FROM truly_disc);

SELECT 'AFTER_REMARK' AS phase, COUNT(*) AS n
FROM stockpile WHERE is_truly_discontinued = true;

COMMIT;

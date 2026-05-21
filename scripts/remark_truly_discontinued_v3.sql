-- v3 remark (2026-05-21): qty_total=0 严格等号改成 <=0
--
-- 修复 v2 (2026-05-21 下午) 漏:
--   负库存 SKU 算法漏标. 典型 case: 5203692253142
--     - 有 snapshot 2 行 (rule A model=5203692253142 qty=-1 + rule B model=53142 qty=0)
--     - sku_qty CTE MIN(qty) = -1
--     - v2 判定 qty_total = 0 → -1 != 0 → 不标停用
--   负库存 (ERP 超卖待到货 / 入库漏做 / 盘点错) 实际比 0 库存更"缺货",
--   补货决策侧应该也标停用 (没人卖 + 库存负 = 死货)
--
-- 改动: WHERE q.qty_total = 0 → q.qty_total <= 0
--
-- 预期增量: 几十-几百行 (跟 negative_stock 总数 2249 关联, 但绝大部分还在卖)

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
        (q.qty_total <= 0
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

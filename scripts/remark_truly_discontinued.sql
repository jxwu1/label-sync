-- 重打 is_truly_discontinued 标 (2026-05-21 数据驱动新算法)
--
-- 旧算法 (2026-05-20 mark_truly_discontinued.sql) 用 "PG 完全无事件"
-- → 漏掉 5828079144655 这种"3年前有过1笔销售然后再没动过"的死货.
--
-- 新算法 (跟 ERP 等级=0 解耦, 纯数据):
--   is_truly_discontinued = TRUE iff
--     最新 inventory_snapshot.qty_total = 0
--     AND (last_sale IS NULL OR last_sale < CURRENT_DATE - 730d)
--     AND (last_purchase IS NULL OR last_purchase < CURRENT_DATE - 730d)
--
-- 实测 (2026-05-21):
--   旧总数: 13,248 (含 no_events 子集)
--   新总数预期: 18,231
--     - no_events: 13,452 (无事件 子集, 跟旧重合)
--     - inactive_730d: 4,779 (新增覆盖)
--     - active: 6,000 (库存=0 但 730d 内有过活动 → 不算停用)

BEGIN;

UPDATE stockpile SET is_truly_discontinued = false WHERE is_truly_discontinued = true;

SELECT 'AFTER_RESET' AS phase, COUNT(*) AS n FROM stockpile WHERE is_truly_discontinued = true;

WITH latest_snap_date AS (
    SELECT MAX(snapshot_date) AS d FROM stockpile_inventory_snapshot
),
last_events AS (
    SELECT product_barcode,
           MAX(event_at) FILTER (WHERE event_type='sale') AS last_sale,
           MAX(event_at) FILTER (WHERE event_type='purchase') AS last_purchase
    FROM inventory_events GROUP BY product_barcode
),
truly_discontinued AS (
    SELECT s.product_barcode
    FROM stockpile s
    JOIN stockpile_inventory_snapshot snap
      ON snap.snapshot_date = (SELECT d FROM latest_snap_date)
      AND s.product_model = snap.product_model
    LEFT JOIN last_events e ON e.product_barcode = s.product_barcode
    WHERE snap.qty_total = 0
      AND (e.last_sale IS NULL OR e.last_sale::date < CURRENT_DATE - INTERVAL '730 days')
      AND (e.last_purchase IS NULL OR e.last_purchase::date < CURRENT_DATE - INTERVAL '730 days')
)
UPDATE stockpile s
SET is_truly_discontinued = true
WHERE s.product_barcode IN (SELECT product_barcode FROM truly_discontinued);

SELECT 'AFTER_REMARK' AS phase, COUNT(*) AS n
FROM stockpile WHERE is_truly_discontinued = true;

COMMIT;

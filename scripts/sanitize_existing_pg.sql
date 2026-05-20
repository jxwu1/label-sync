-- 一次性脱敏: 把 inventory_events 已有的 purchase 行 unit_price 清空 (进价不上云)
--
-- 背景: sanitize.py 是 2026-05-20 才上线的, 之前导入的 1.36M 行里有 22,750
-- 个 purchase 事件带进价. 本脚本一次性补脱敏, 之后新数据走 sanitize.py 链路.
--
-- 前置确认 (2026-05-20):
--   1. inventory_events 表 schema 里没有 customer_name / supplier_name 字段
--      (历史 import 自动丢弃), 所以只需处理 unit_price
--   2. uq_inventory_events UNIQUE 约束 nulls_not_distinct=f (默认), NULL 不冲突
--   3. 2 个 conflict group (4 行) 是同 doc 同 SKU 同 qty 但不同进价的分批入库,
--      置 NULL 后仍 distinct (NULL != NULL in PG default)
--   4. Hash 对齐已验证: PG sha256(text::bytea) == Python hashlib.sha256(utf8)
--      (本次不涉及, 留作 future name 字段如有需要)
--
-- 运行方式:
--   docker cp scripts/sanitize_existing_pg.sql y78raoiermwnu9vjd9criq3a:/tmp/
--   docker exec -i y78raoiermwnu9vjd9criq3a psql -U postgres -d label_sync \
--     -f /tmp/sanitize_existing_pg.sql

BEGIN;

SELECT 'BEFORE' AS phase,
       COUNT(*) FILTER (WHERE event_type='purchase' AND unit_price IS NOT NULL) AS purchase_with_price,
       COUNT(*) FILTER (WHERE event_type='sale' AND unit_price IS NOT NULL) AS sale_with_price
FROM inventory_events;

UPDATE inventory_events
SET unit_price = NULL
WHERE event_type = 'purchase' AND unit_price IS NOT NULL;

SELECT 'AFTER' AS phase,
       COUNT(*) FILTER (WHERE event_type='purchase' AND unit_price IS NOT NULL) AS purchase_with_price,
       COUNT(*) FILTER (WHERE event_type='sale' AND unit_price IS NOT NULL) AS sale_with_price
FROM inventory_events;

COMMIT;

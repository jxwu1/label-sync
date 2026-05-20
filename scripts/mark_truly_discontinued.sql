-- 一次性: 给 13,440 个极高置信「真停用」SKU 打标 (is_truly_discontinued=true)
--
-- 前置:
--   1. 迁移 d8a3f5c2b1e4 已 apply (stockpile.is_truly_discontinued 字段存在)
--   2. /tmp/discontinued_barcodes.csv 已 docker cp 进 shared-pg17 容器
--      (单列, 13,440 行, 无 header)
--
-- 运行:
--   docker exec -i y78raoiermwnu9vjd9criq3a psql -U postgres -d label_sync \
--     -f /tmp/mark_truly_discontinued.sql

BEGIN;

CREATE TEMP TABLE _discontinued (product_barcode text);
\COPY _discontinued FROM '/tmp/discontinued_barcodes.csv' CSV;

SELECT 'BEFORE_FLAG_COUNT' AS phase,
       COUNT(*) AS truly_discontinued_count
FROM stockpile WHERE is_truly_discontinued = true;

UPDATE stockpile
SET is_truly_discontinued = true
WHERE product_barcode IN (SELECT product_barcode FROM _discontinued);

SELECT 'AFTER_FLAG_COUNT' AS phase,
       COUNT(*) AS truly_discontinued_count
FROM stockpile WHERE is_truly_discontinued = true;

-- 诊断: 列表里多少 barcode 不在 stockpile 表 (新档/历史档, 不影响数据)
SELECT 'NOT_IN_STOCKPILE' AS phase,
       COUNT(*) AS barcodes_in_list_not_in_stockpile
FROM _discontinued d
LEFT JOIN stockpile s ON s.product_barcode = d.product_barcode
WHERE s.product_barcode IS NULL;

COMMIT;

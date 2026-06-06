"""货号销售/采购指标 + 客户端拆分（阶段 5 PR 5.1）。

每个 SKU 算 dashboard 展示用的指标，**不落表**，每次查询即时算。

三组函数：
- compute_sales_metrics(barcode, as_of) → 销售面 5 数（含 12 周线性回归斜率）
- compute_purchase_metrics(barcode, as_of) → 采购面 4 数（含库存推算 / 毛利率 / 采购频率）
- compute_customer_split(barcode, as_of) → 中国端 / 老外端各 5 数

设计取舍：
- numpy 算斜率，**不引** sklearn / scipy / statsmodels（YAGNI，也是 plan 明确边界）
- as_of 可注入，方便测试和"按月度回溯"用例（默认 today）
- 缺数据返回 0 / None，不抛异常（dashboard 期望永远能渲染）
- 单 SKU 一次 SQL；5 万 SKU 批量算另写 batch 入口（PR 5.1f）

本模块已 split-only 拆为子模块（_shared / freshness / metrics / restock_calc /
summary / categories），本文件仅做 re-export，外部 import 路径 (app.services.analytics)
保持不变。
"""

from app.services.analytics._shared import *  # noqa: F401,F403
from app.services.analytics.freshness import *  # noqa: F401,F403
from app.services.analytics.metrics import *  # noqa: F401,F403
from app.services.analytics.restock_calc import *  # noqa: F401,F403
from app.services.analytics.summary import *  # noqa: F401,F403
from app.services.analytics.categories import *  # noqa: F401,F403

# import * 不带下划线符号, 测试依赖的私有显式补:
from app.services.analytics._shared import (  # noqa: F401
    _fetch_all_rows_with_doc_no,
    _today,
)
from app.services.analytics.restock_calc import _compute_urgency_score  # noqa: F401
from app.services.analytics.summary import (  # noqa: F401
    _LIST_CACHE,
    _list_sku_summary_impl,
    _read_sku_summary_row,
)

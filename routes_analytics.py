"""销售分析 HTTP routes（PR 5.2 起）。

GET /analytics/sku/<barcode>
    返回该 SKU 的销售/采购/客户端拆分指标 + 当前自动 + 人工分类标签。
    供货号详情页"📈 销售分析"panel 使用。
"""

from flask import Blueprint, jsonify
from sqlalchemy import select

import analytics_service
import stockpile_db
from models import Stockpile

bp = Blueprint("analytics", __name__, url_prefix="/analytics")


@bp.get("/sku/<barcode>")
def sku_metrics(barcode: str):
    barcode = barcode.strip()
    if not barcode:
        return jsonify({"ok": False, "msg": "缺少条码"}), 400

    try:
        sales = analytics_service.compute_sales_metrics(barcode)
        purchase = analytics_service.compute_purchase_metrics(barcode)
        customer_split = analytics_service.compute_customer_split(barcode)
        with stockpile_db._session() as session:
            row = session.execute(
                select(
                    Stockpile.auto_category,
                    Stockpile.auto_category_computed_at,
                    Stockpile.manual_category,
                    Stockpile.manual_grade,
                ).where(Stockpile.product_barcode == barcode)
            ).first()
    except Exception as exc:
        return jsonify({"ok": False, "msg": f"分析失败：{exc}"}), 500

    if row is None:
        return jsonify({"ok": False, "msg": "未找到该条码"}), 404

    return jsonify(
        {
            "ok": True,
            "barcode": barcode,
            "sales": sales,
            "purchase": purchase,
            "customer_split": customer_split,
            "auto_category": row[0],
            "auto_category_computed_at": row[1],
            "manual_category": row[2],
            "manual_grade": row[3],
        }
    )

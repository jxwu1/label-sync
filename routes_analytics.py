"""销售分析 HTTP routes（PR 5.2 起）。

GET /analytics/sku/<barcode>
    返回该 SKU 的销售/采购/客户端拆分指标 + 当前自动 + 人工分类标签
    + 销量百分位（等级对照用）。
POST /analytics/sku/<barcode>/manual-category
    设/清 manual_category 标签。空字符串清空。
"""

from flask import Blueprint, jsonify
from pydantic import BaseModel
from sqlalchemy import select, update

import analytics_service
import stockpile_db
from models import Stockpile
from route_helpers import OptionalStr, parse_body

bp = Blueprint("analytics", __name__, url_prefix="/analytics")

# 8 个手工分类合法值（plan 锁定 + 空字符串清空）
_VALID_MANUAL_CATEGORIES = frozenset(
    ["", "季节性", "网红昙花", "应需采购", "消耗品", "长期产品", "阶段性多峰", "滞销"]
)


@bp.get("/sku/<barcode>/timeline")
def sku_timeline(barcode: str):
    """单 SKU 周聚合时间线（销量 + 进价）。"""
    barcode = barcode.strip()
    if not barcode:
        return jsonify({"ok": False, "msg": "缺少条码"}), 400
    try:
        timeline = analytics_service.compute_weekly_timeline(barcode)
    except Exception as exc:
        return jsonify({"ok": False, "msg": f"时间线失败：{exc}"}), 500
    return jsonify({"ok": True, "barcode": barcode, "timeline": timeline})


@bp.get("/list")
def list_skus():
    """全部 active SKU 的指标汇总（dashboard 列表页用）。

    无分页、无后端筛选/排序：~27k 行 × 小 dict ≈ 4MB JSON，浏览器侧
    一次拉完后做 filter / sort 更顺手（用户改 chip 不用再请求）。
    """
    try:
        items = analytics_service.list_sku_summary()
    except Exception as exc:
        return jsonify({"ok": False, "msg": f"列表失败：{exc}"}), 500
    return jsonify({"ok": True, "items": items, "total": len(items)})


@bp.get("/sku/<barcode>")
def sku_metrics(barcode: str):
    barcode = barcode.strip()
    if not barcode:
        return jsonify({"ok": False, "msg": "缺少条码"}), 400

    try:
        sales = analytics_service.compute_sales_metrics(barcode)
        purchase = analytics_service.compute_purchase_metrics(barcode)
        customer_split = analytics_service.compute_customer_split(barcode)
        qty_percentile = analytics_service.compute_qty_percentile(barcode)
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
            "qty_percentile": qty_percentile,
            "auto_category": row[0],
            "auto_category_computed_at": row[1],
            "manual_category": row[2],
            "manual_grade": row[3],
        }
    )


class _ManualCategoryBody(BaseModel):
    category: OptionalStr  # 允许 "" 清空


@bp.post("/sku/<barcode>/manual-category")
def set_manual_category(barcode: str):
    barcode = barcode.strip()
    if not barcode:
        return jsonify({"ok": False, "msg": "缺少条码"}), 400

    body, err = parse_body(_ManualCategoryBody)
    if err:
        return err
    cat = body.category
    if cat not in _VALID_MANUAL_CATEGORIES:
        valid = "/".join(c for c in _VALID_MANUAL_CATEGORIES if c)
        return jsonify({"ok": False, "msg": f"非法分类，可用：{valid}（或空清除）"}), 400

    new_value = cat if cat else None
    with stockpile_db._session() as session:
        result = session.execute(
            update(Stockpile)
            .where(Stockpile.product_barcode == barcode)
            .values(manual_category=new_value)
        )
        if result.rowcount == 0:
            return jsonify({"ok": False, "msg": "未找到该条码"}), 404
        session.commit()
    return jsonify({"ok": True, "manual_category": new_value})

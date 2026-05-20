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

from app.services import analytics as analytics_service
from app.repositories import stockpile_db
from app.models import Stockpile
from app.utils.route_helpers import OptionalStr, parse_body

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


# ---- 阶段 2.7 回测 routes (plan §2.7) ---------------------------------------


class _BacktestRunBody(BaseModel):
    model_name: str
    end_date: str  # 'YYYY-MM-DD'
    weeks: int = 156
    view: str = "base_demand"
    window_train: int = 13
    window_test: int = 4
    min_weeks: int = 20
    notes: OptionalStr = None
    barcodes: list[str] | None = None


@bp.post("/backtest/run")
def backtest_run():
    """启动一次回测 (同步; 全量大 batch 应改后台任务)."""
    from datetime import datetime

    from app.services import backtest as backtest_service
    body, err = parse_body(_BacktestRunBody)
    if err:
        return err
    try:
        end_date = datetime.strptime(body.end_date, "%Y-%m-%d").date()
    except ValueError:
        return jsonify({"ok": False, "msg": "end_date 格式应为 YYYY-MM-DD"}), 400

    try:
        run_id = backtest_service.run_backtest_all_skus(
            model_name=body.model_name,
            end_date=end_date,
            weeks=body.weeks,
            view=body.view,
            window_train=body.window_train,
            window_test=body.window_test,
            min_weeks=body.min_weeks,
            notes=body.notes,
            barcodes=body.barcodes,
        )
    except ValueError as e:
        return jsonify({"ok": False, "msg": str(e)}), 400
    return jsonify({"ok": True, "run_id": run_id})


@bp.get("/backtest/runs")
def backtest_list_runs():
    """列出最近 N 次 run 元信息."""
    from app.models import BacktestRun

    with stockpile_db._session() as session:
        rows = (
            session.execute(select(BacktestRun).order_by(BacktestRun.id.desc()).limit(50))
            .scalars()
            .all()
        )
        return jsonify(
            {
                "ok": True,
                "runs": [
                    {
                        "id": r.id,
                        "created_at": r.created_at,
                        "model_name": r.model_name,
                        "view": r.view,
                        "window_train": r.window_train,
                        "window_test": r.window_test,
                        "min_weeks": r.min_weeks,
                        "n_skus_total": r.n_skus_total,
                        "n_skus_scored": r.n_skus_scored,
                        "notes": r.notes,
                    }
                    for r in rows
                ],
            }
        )


@bp.get("/backtest/compare")
def backtest_compare():
    """对比两次 run 的 per-SKU 分数差异 (plan §2.8). query: run_a, run_b."""
    from flask import request

    from app.services import backtest as backtest_service
    raw_a = request.args.get("run_a")
    raw_b = request.args.get("run_b")
    if not raw_a or not raw_b:
        return jsonify({"ok": False, "msg": "缺少 run_a / run_b"}), 400
    try:
        run_a = int(raw_a)
        run_b = int(raw_b)
    except ValueError:
        return jsonify({"ok": False, "msg": "run_a / run_b 必须是整数"}), 400

    try:
        result = backtest_service.compare_run_pair(run_a, run_b)
    except ValueError as e:
        return jsonify({"ok": False, "msg": str(e)}), 404
    return jsonify({"ok": True, **result})


@bp.get("/backtest/summary")
def backtest_summary():
    """单个 run 的 aggregate 指标, 按 SKU origin (FOREIGN/CN/unknown/all) 筛选.

    query:
        run_id (必填)
        origin (可选, 默认 all): FOREIGN | CN | unknown | all
    返回 {ok, run_id, origin, n, med_mape, med_mase, avg_bias, avg_cov98}.
    用 sku_origin.ORIGIN_CTE_SQL 计算每个 barcode 的 origin (供应商前缀
    优先 + model 长度回退), 在 SQL 端聚合.
    """
    from flask import request
    from sqlalchemy import text

    from app.services.sku_origin import ORIGIN_CTE_SQL

    raw = request.args.get("run_id")
    origin_upper = (request.args.get("origin") or "all").strip().upper()
    _ORIGIN_MAP = {"ALL": "all", "FOREIGN": "FOREIGN", "CN": "CN", "UNKNOWN": "unknown"}
    if origin_upper not in _ORIGIN_MAP:
        return jsonify(
            {"ok": False, "msg": "origin 必须是 FOREIGN / CN / unknown / all"}
        ), 400
    origin_filter = _ORIGIN_MAP[origin_upper]
    if not raw:
        return jsonify({"ok": False, "msg": "缺少 run_id"}), 400
    try:
        run_id = int(raw)
    except ValueError:
        return jsonify({"ok": False, "msg": "run_id 必须是整数"}), 400

    where_origin = "" if origin_filter == "all" else "AND so.origin = :origin"
    sql = ORIGIN_CTE_SQL + f"""
SELECT
    COUNT(*) AS n,
    percentile_cont(0.5) WITHIN GROUP (ORDER BY br.mape) AS med_mape,
    percentile_cont(0.5) WITHIN GROUP (ORDER BY br.mase) AS med_mase,
    AVG(br.bias)         AS avg_bias,
    AVG(br.coverage_p98) AS avg_cov98
FROM backtest_results br
JOIN sku_origin so ON so.product_barcode = br.product_barcode
WHERE br.run_id = :run_id {where_origin}
"""
    params: dict = {"run_id": run_id}
    if origin_filter != "all":
        params["origin"] = origin_filter

    with stockpile_db._session() as session:
        row = session.execute(text(sql), params).first()
        if row is None or row.n == 0:
            return jsonify(
                {
                    "ok": True,
                    "run_id": run_id,
                    "origin": origin_filter,
                    "n": 0,
                    "med_mape": None,
                    "med_mase": None,
                    "avg_bias": None,
                    "avg_cov98": None,
                }
            )
        return jsonify(
            {
                "ok": True,
                "run_id": run_id,
                "origin": origin_filter,
                "n": int(row.n),
                "med_mape": float(row.med_mape) if row.med_mape is not None else None,
                "med_mase": float(row.med_mase) if row.med_mase is not None else None,
                "avg_bias": float(row.avg_bias) if row.avg_bias is not None else None,
                "avg_cov98": float(row.avg_cov98) if row.avg_cov98 is not None else None,
            }
        )


@bp.post("/forecast/refresh")
def forecast_refresh():
    """§3.7 触发 forecast_output 表全量刷新 (供 cron 容器调).

    无 query/body. 同步执行 (生产规模 ~27k SKU, 实测几分钟内完成).
    返回 {ok, n_total, n_written, n_skipped}.
    """
    from app.services.forecast import refresh_forecast_output

    try:
        stats = refresh_forecast_output()
    except Exception as exc:
        return jsonify({"ok": False, "msg": f"刷新失败：{exc}"}), 500
    return jsonify({"ok": True, **stats})


@bp.get("/backtest/results")
def backtest_results():
    """单个 run 的 per-SKU 分数 (query param run_id)."""
    from flask import request

    from app.models import BacktestResult

    raw = request.args.get("run_id")
    if not raw:
        return jsonify({"ok": False, "msg": "缺少 run_id"}), 400
    try:
        run_id = int(raw)
    except ValueError:
        return jsonify({"ok": False, "msg": "run_id 必须是整数"}), 400

    with stockpile_db._session() as session:
        rows = (
            session.execute(select(BacktestResult).where(BacktestResult.run_id == run_id))
            .scalars()
            .all()
        )
        return jsonify(
            {
                "ok": True,
                "run_id": run_id,
                "results": [
                    {
                        "product_barcode": r.product_barcode,
                        "sku_type": r.sku_type,
                        "mape": r.mape,
                        "mase": r.mase,
                        "bias": r.bias,
                        "coverage_p98": r.coverage_p98,
                        "mean_actual": r.mean_actual,
                        "mean_predicted": r.mean_predicted,
                    }
                    for r in rows
                ],
            }
        )

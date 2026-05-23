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
    """单 SKU 时间线: 156 周进价线 (event 精度) + 36 月销量柱 (聚合).

    2026-05-23 起返回:
      timeline:        156 周, 每周 {week_start, sale_qty, purchase_unit_price, raw_unit_price_local, currency_local}
      monthly_sales:   36 月, 每月 {month_start, sale_qty (批发), retail_qty}
    前端: 销量柱用 monthly_sales (36 根宽柱), 进价线/点用 timeline (event 精度).
    """
    barcode = barcode.strip()
    if not barcode:
        return jsonify({"ok": False, "msg": "缺少条码"}), 400
    try:
        timeline = analytics_service.compute_weekly_timeline(barcode)
        monthly = analytics_service.compute_monthly_sales(barcode)
    except Exception as exc:
        return jsonify({"ok": False, "msg": f"时间线失败：{exc}"}), 500
    return jsonify({"ok": True, "barcode": barcode, "timeline": timeline, "monthly_sales": monthly})


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
        extras = analytics_service.compute_sku_extras(barcode)
        holding = analytics_service.compute_avg_holding_days(barcode)
        heatmap = analytics_service.compute_monthly_heatmap(barcode)
        forecast = analytics_service.compute_forecast_snapshot(barcode)
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
        return jsonify({"ok": False, "msg": f"分析失败:{exc}"}), 500

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
            "extras": extras,
            "holding": holding,
            "heatmap": heatmap,
            "forecast": forecast,
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


@bp.get("/sales/top")
def sales_top():
    """历史实测好卖货清单 (区别于 /forecast/top 是预测).

    按过去 N 周 inventory_events 净销量 (扣退货) 聚合, 支持 origin filter.

    query:
        origin (可选, 默认 FOREIGN): FOREIGN | CN | unknown | all
        weeks  (可选, 默认 52, 范围 4-208): 回溯几周
        limit  (可选, 默认 200, 上限 5000)
        min_active_weeks (可选, 默认 0): 过滤至少有 N 个非零销售周的 SKU
        exclude_discontinued (可选, 默认 true): 是否排除 is_truly_discontinued=true 的 SKU
        format (可选, 默认 csv): csv | json
    """
    import csv
    import io

    from flask import request, Response
    from sqlalchemy import text

    from app.services.sku_origin import ORIGIN_CTE_SQL

    origin_upper = (request.args.get("origin") or "FOREIGN").strip().upper()
    _ORIGIN_MAP = {"ALL": "all", "FOREIGN": "FOREIGN", "CN": "CN", "UNKNOWN": "unknown"}
    if origin_upper not in _ORIGIN_MAP:
        return jsonify(
            {"ok": False, "msg": "origin 必须是 FOREIGN / CN / unknown / all"}
        ), 400
    origin_filter = _ORIGIN_MAP[origin_upper]

    try:
        weeks = int(request.args.get("weeks", "52"))
        limit = int(request.args.get("limit", "200"))
        min_active_weeks = int(request.args.get("min_active_weeks", "0"))
    except ValueError:
        return jsonify({"ok": False, "msg": "weeks/limit/min_active_weeks 必须是整数"}), 400
    if weeks < 4 or weeks > 208:
        return jsonify({"ok": False, "msg": "weeks 范围 4-208"}), 400
    if limit < 1 or limit > 5000:
        return jsonify({"ok": False, "msg": "limit 范围 1-5000"}), 400

    fmt = (request.args.get("format") or "csv").lower()
    if fmt not in ("csv", "json"):
        return jsonify({"ok": False, "msg": "format 必须是 csv 或 json"}), 400

    exclude_raw = (request.args.get("exclude_discontinued") or "true").strip().lower()
    if exclude_raw not in ("true", "false", "1", "0"):
        return jsonify({"ok": False, "msg": "exclude_discontinued 必须是 true 或 false"}), 400
    exclude_discontinued = exclude_raw in ("true", "1")

    where_origin = "" if origin_filter == "all" else "AND so.origin = :origin"
    where_disc = "AND s.is_truly_discontinued = false" if exclude_discontinued else ""
    sql = ORIGIN_CTE_SQL + f""",
sales_agg AS (
    SELECT
        product_barcode,
        SUM(qty)::int AS total_qty,
        COUNT(DISTINCT DATE_TRUNC('week', event_at::date)) AS n_active_weeks
    FROM inventory_events
    WHERE event_type = 'sale'
      AND event_at::date >= (CURRENT_DATE - (:weeks * 7))
    GROUP BY product_barcode
    HAVING SUM(qty) > 0
)
SELECT
    sa.product_barcode,
    s.product_model,
    s.product_name_zh,
    s.product_name_local,
    s.erp_category_raw,
    so.origin,
    s.auto_category,
    sa.total_qty,
    sa.n_active_weeks,
    (sa.total_qty * 1.0 / NULLIF(sa.n_active_weeks, 0)) AS mean_qty_per_active_week,
    s.sale_price
FROM sales_agg sa
JOIN stockpile s ON s.product_barcode = sa.product_barcode
JOIN sku_origin so ON so.product_barcode = sa.product_barcode
WHERE s.is_active = 1
  AND sa.n_active_weeks >= :min_active_weeks
  {where_origin}
  {where_disc}
ORDER BY sa.total_qty DESC
LIMIT :limit
"""
    params: dict = {"weeks": weeks, "limit": limit, "min_active_weeks": min_active_weeks}
    if origin_filter != "all":
        params["origin"] = origin_filter

    with stockpile_db._session() as session:
        rows = session.execute(text(sql), params).all()

    items = [
        {
            "product_barcode": r.product_barcode,
            "product_model": r.product_model,
            "product_name_zh": r.product_name_zh,
            "product_name_local": r.product_name_local,
            "erp_category_raw": r.erp_category_raw,
            "origin": r.origin,
            "auto_category": r.auto_category,
            "total_qty": int(r.total_qty),
            "n_active_weeks": int(r.n_active_weeks),
            "mean_qty_per_active_week": (
                float(r.mean_qty_per_active_week)
                if r.mean_qty_per_active_week is not None else None
            ),
            "sale_price": float(r.sale_price) if r.sale_price is not None else None,
        }
        for r in rows
    ]

    if fmt == "json":
        return jsonify({
            "ok": True, "origin": origin_filter, "weeks": weeks,
            "n": len(items), "items": items,
        })

    buf = io.StringIO()
    fields = [
        "product_barcode", "product_model",
        "product_name_zh", "product_name_local",
        "erp_category_raw", "origin", "auto_category",
        "total_qty", "n_active_weeks", "mean_qty_per_active_week",
        "sale_price",
    ]
    writer = csv.DictWriter(buf, fieldnames=fields)
    writer.writeheader()
    writer.writerows(items)
    csv_bytes = buf.getvalue().encode("utf-8-sig")
    fname = f"sales_top_{origin_filter}_{weeks}w.csv"
    return Response(
        csv_bytes,
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@bp.get("/forecast/top")
def forecast_top():
    """§3.7+ 按预测周销量排序的「好卖货」清单, 支持按 origin filter.

    query:
        origin (可选, 默认 FOREIGN): FOREIGN | CN | unknown | all
        limit (可选, 默认 200, 上限 5000)
        exclude_discontinued (可选, 默认 true): 是否排除 is_truly_discontinued=true 的 SKU
        format (可选, 默认 csv): csv | json

    JOIN forecast_output + stockpile + sku_origin CTE, 按 p50 desc 排序.
    不返回进价 (stock_price), 只含售价 (sale_price).
    """
    import csv
    import io

    from flask import request, Response
    from sqlalchemy import text

    from app.services.sku_origin import ORIGIN_CTE_SQL

    origin_upper = (request.args.get("origin") or "FOREIGN").strip().upper()
    _ORIGIN_MAP = {"ALL": "all", "FOREIGN": "FOREIGN", "CN": "CN", "UNKNOWN": "unknown"}
    if origin_upper not in _ORIGIN_MAP:
        return jsonify(
            {"ok": False, "msg": "origin 必须是 FOREIGN / CN / unknown / all"}
        ), 400
    origin_filter = _ORIGIN_MAP[origin_upper]

    try:
        limit = int(request.args.get("limit", "200"))
    except ValueError:
        return jsonify({"ok": False, "msg": "limit 必须是整数"}), 400
    if limit < 1 or limit > 5000:
        return jsonify({"ok": False, "msg": "limit 范围 1-5000"}), 400

    fmt = (request.args.get("format") or "csv").lower()
    if fmt not in ("csv", "json"):
        return jsonify({"ok": False, "msg": "format 必须是 csv 或 json"}), 400

    exclude_raw = (request.args.get("exclude_discontinued") or "true").strip().lower()
    if exclude_raw not in ("true", "false", "1", "0"):
        return jsonify({"ok": False, "msg": "exclude_discontinued 必须是 true 或 false"}), 400
    exclude_discontinued = exclude_raw in ("true", "1")

    where_origin = "" if origin_filter == "all" else "AND so.origin = :origin"
    where_disc = "AND s.is_truly_discontinued = false" if exclude_discontinued else ""
    sql = ORIGIN_CTE_SQL + f"""
SELECT
    f.product_barcode,
    s.product_model,
    s.product_name_zh,
    s.product_name_local,
    s.erp_category_raw,
    so.origin,
    f.sku_type,
    f.model_used,
    f.n_weeks_history,
    f.p50,
    f.mu,
    s.sale_price
FROM forecast_output f
JOIN stockpile s ON s.product_barcode = f.product_barcode
JOIN sku_origin so ON so.product_barcode = f.product_barcode
WHERE s.is_active = 1 {where_origin} {where_disc}
ORDER BY f.p50 DESC
LIMIT :limit
"""
    params: dict = {"limit": limit}
    if origin_filter != "all":
        params["origin"] = origin_filter

    with stockpile_db._session() as session:
        rows = session.execute(text(sql), params).all()

    items = [
        {
            "product_barcode": r.product_barcode,
            "product_model": r.product_model,
            "product_name_zh": r.product_name_zh,
            "product_name_local": r.product_name_local,
            "erp_category_raw": r.erp_category_raw,
            "origin": r.origin,
            "sku_type": r.sku_type,
            "model_used": r.model_used,
            "n_weeks_history": r.n_weeks_history,
            "p50": float(r.p50) if r.p50 is not None else None,
            "mu": float(r.mu) if r.mu is not None else None,
            "sale_price": float(r.sale_price) if r.sale_price is not None else None,
        }
        for r in rows
    ]

    if fmt == "json":
        return jsonify({"ok": True, "origin": origin_filter, "n": len(items), "items": items})

    buf = io.StringIO()
    fields = [
        "product_barcode", "product_model",
        "product_name_zh", "product_name_local",
        "erp_category_raw", "origin", "sku_type",
        "model_used", "n_weeks_history",
        "p50", "mu", "sale_price",
    ]
    writer = csv.DictWriter(buf, fieldnames=fields)
    writer.writeheader()
    writer.writerows(items)
    csv_bytes = buf.getvalue().encode("utf-8-sig")  # Excel 友好 BOM
    fname = f"forecast_top_{origin_filter}.csv"
    return Response(
        csv_bytes,
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@bp.post("/data/upload")
def data_upload():
    """§2.6 接收脱敏后的 parquet 文件入库.

    Auth: X-Upload-Token 头, 跟服务器 env UPLOAD_TOKEN 常时间比较.

    2026-05-21 起策略变更: events.purchase 带 unit_price 不再被拒收
    (用户决策接受内网态势下进价上 PG). 上线后 stockpile.last_purchase_unit_price
    会被 parquet_importer 自动回填供毛利计算.

    保存到 CONFIG.base_dir/scrape_uploads/<ts>_<name>.parquet, 然后调
    etl.parquet_importer.import_cleaned_parquet 入 inventory_events.

    返回 200 {ok, sale/purchase 各 imported/dup/missed} 或 400/401/500.
    """
    import os
    import secrets
    from datetime import datetime, timezone
    from pathlib import Path

    from flask import request
    from werkzeug.utils import secure_filename

    from app.config import CONFIG

    expected = os.environ.get("UPLOAD_TOKEN", "")
    if not expected:
        return jsonify({"ok": False, "msg": "服务器 UPLOAD_TOKEN 未配置"}), 500
    provided = request.headers.get("X-Upload-Token", "")
    if not secrets.compare_digest(provided, expected):
        return jsonify({"ok": False, "msg": "鉴权失败"}), 401

    if "file" not in request.files:
        return jsonify({"ok": False, "msg": "缺少 file (multipart form 字段名)"}), 400
    f = request.files["file"]
    fname = f.filename or ""
    if not fname.endswith(".parquet"):
        return jsonify({"ok": False, "msg": "file 必须是 .parquet"}), 400
    is_events = fname.startswith("events_")
    is_inventory = fname.startswith("inventory_snapshot_")
    is_product_master = fname.startswith("product_master_")
    if not (is_events or is_inventory or is_product_master):
        return jsonify({
            "ok": False,
            "msg": "文件名必须以 events_ / inventory_snapshot_ / product_master_ 开头",
        }), 400

    upload_dir = Path(CONFIG.base_dir) / "scrape_uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    saved = upload_dir / f"{ts}_{secure_filename(fname)}"
    f.save(saved)

    if is_events:
        try:
            from etl.parquet_importer import import_cleaned_parquet
            with stockpile_db._session() as session:
                sale_r, purchase_r = import_cleaned_parquet(saved, session)
                session.commit()
        except Exception as exc:
            return jsonify({"ok": False, "msg": f"导入失败: {exc}"}), 500
        return jsonify({
            "ok": True,
            "kind": "events",
            "filename": saved.name,
            "sale": {
                "imported": sale_r.rows_imported,
                "dup_skipped": sale_r.rows_skipped_duplicate,
                "missing_skipped": sale_r.rows_skipped_missing_key,
                "new_customers": sale_r.new_customers,
                "new_skus": sale_r.new_skus,
            },
            "purchase": {
                "imported": purchase_r.rows_imported,
                "dup_skipped": purchase_r.rows_skipped_duplicate,
                "missing_skipped": purchase_r.rows_skipped_missing_key,
                "new_suppliers": purchase_r.new_suppliers,
                "new_skus": purchase_r.new_skus,
            },
        })

    if is_inventory:
        try:
            from etl.inventory_importer import import_inventory_snapshot
            with stockpile_db._session() as session:
                stats = import_inventory_snapshot(saved, session)
                session.commit()
        except ValueError as exc:
            saved.unlink(missing_ok=True)
            return jsonify({"ok": False, "msg": f"inventory schema 错误: {exc}"}), 400
        except Exception as exc:
            return jsonify({"ok": False, "msg": f"导入失败: {exc}"}), 500
        return jsonify({
            "ok": True,
            "kind": "inventory_snapshot",
            "filename": saved.name,
            **stats,
        })

    # product_master 分支: parquet → DataFrame → 复用现有 importer
    try:
        import pandas as pd
        from app.importers.product_master import (
            import_product_master,
            DEFAULT_PRODUCT_MAPPING,
        )
        df = pd.read_parquet(saved)
        with stockpile_db._session() as session:
            result = import_product_master(df, DEFAULT_PRODUCT_MAPPING, session)
            session.commit()
    except Exception as exc:
        return jsonify({"ok": False, "msg": f"product_master 导入失败: {exc}"}), 500
    return jsonify({
        "ok": True,
        "kind": "product_master",
        "filename": saved.name,
        "rows_imported": result.rows_imported,
        "rows_updated": result.rows_updated,
        "rows_skipped_missing_barcode": result.rows_skipped_missing_barcode,
        "rows_skipped_duplicate_barcode": result.rows_skipped_duplicate_barcode,
        "new_suppliers": result.new_suppliers,
    })


@bp.post("/data/dedup-purchase-events")
def data_dedup_purchase_events():
    """清理重复的 purchase inventory_events (2026-05-23).

    规则: 相同 (barcode, event_at, qty, event_type='purchase'), 一行
    unit_price 为 NULL, 另一行 > 0 → 删 NULL 行 (ERP 内部重复导入).

    Auth: X-Upload-Token. Query: ?execute=true 实际删, 缺省 dry-run.
    """
    import os
    import secrets
    from flask import request
    from sqlalchemy import text

    expected = os.environ.get("UPLOAD_TOKEN", "")
    if not expected:
        return jsonify({"ok": False, "msg": "服务器 UPLOAD_TOKEN 未配置"}), 500
    provided = request.headers.get("X-Upload-Token", "")
    if not secrets.compare_digest(provided, expected):
        return jsonify({"ok": False, "msg": "鉴权失败"}), 401

    execute = request.args.get("execute", "").lower() == "true"
    find_sql = text("""
        SELECT e_null.id
        FROM inventory_events e_null
        JOIN inventory_events e_priced
          ON e_priced.event_type = 'purchase'
         AND e_priced.product_barcode = e_null.product_barcode
         AND e_priced.event_at = e_null.event_at
         AND e_priced.qty = e_null.qty
         AND e_priced.unit_price IS NOT NULL
         AND e_priced.id != e_null.id
        WHERE e_null.event_type = 'purchase'
          AND e_null.unit_price IS NULL
    """)
    with stockpile_db._session() as session:
        ids = [r[0] for r in session.execute(find_sql).all()]
        count = len(ids)
        if not execute:
            return jsonify({"ok": True, "mode": "dry-run", "deletable_rows": count})
        # 分批 DELETE
        BATCH = 500
        for i in range(0, len(ids), BATCH):
            chunk = ids[i:i + BATCH]
            session.execute(
                text("DELETE FROM inventory_events WHERE id = ANY(:ids)"),
                {"ids": chunk},
            )
        session.commit()
        return jsonify({"ok": True, "mode": "execute", "deleted": count})


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

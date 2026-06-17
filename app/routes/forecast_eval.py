"""预测效果看板 canonical 端点（前端独立化 §11，2026-06-17 迁 Vue）。

只读，走 session auth。聚合逻辑在 services/forecast_eval；本端点是 §6 的
pydantic 契约出口——schema 与现实漂移即 500（与 /api/briefing/data 同纪律）。
"""

from __future__ import annotations

from flask import Blueprint, jsonify

from app.repositories import stockpile_db
from app.services.forecast_eval import build_forecast_eval_dashboard

api_bp = Blueprint("api_forecast_eval", __name__, url_prefix="/api/forecast-eval")


@api_bp.get("/data")
def data():
    from app.schemas_api import ForecastEvalData

    with stockpile_db._session() as session:
        payload = {"ok": True, **build_forecast_eval_dashboard(session)}
    return jsonify(ForecastEvalData.model_validate(payload).model_dump())

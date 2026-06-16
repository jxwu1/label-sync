"""最新批次简报 (老板 backlog #3) 路由。只读, 走 session auth。"""

from __future__ import annotations

from datetime import datetime

from flask import Blueprint, jsonify, redirect

from app.services import briefing as briefing_service
from app.services.analytics._shared import _today

bp = Blueprint("briefing", __name__, url_prefix="/briefing")


@bp.get("")
def page():
    # 简报页已迁 Vue 独立栈 /ui/briefing (前端独立化 §11 收尾, 2026-06-15)。
    # 原路径 302 跳转, 不再渲染旧 Alpine SPA 的简报标签。
    # 注: 数据端点 /briefing/data 保留 (鉴权契约测试样本); canonical = /api/briefing/data。
    return redirect("/ui/briefing", code=302)


@bp.get("/data")
def data():
    # 系统级异常(DB/schema)不在此吞 (review #6): _safe 特意重抛 SQLAlchemyError,
    # 这里不准再 except 接住 — str(exc) 会把 SQL 语句发给客户端, 且丢 Flask 的
    # traceback 日志。让其冒泡 → Flask 通用 500。
    payload = briefing_service.build_briefing_cached(
        as_of=_today(),
        generated_at=datetime.now().isoformat(timespec="seconds"),
    )
    return jsonify(payload)


api_bp = Blueprint("api_briefing", __name__, url_prefix="/api/briefing")


@api_bp.get("/data")
def api_data():
    """canonical 简报端点（spec §6）。pydantic 校验 = schema 与现实漂移即 500。

    红线 B1 注记：computed_at 过期与 stockout_weeks_excluded 的处理在
    build_briefing 内部（data_health 卡新鲜度 + 置信分层输入），本端点
    是同一链路的再暴露，不引入新的 forecast_output 裸消费。
    """
    from app.schemas_api import BriefingData

    payload = briefing_service.build_briefing_cached(
        as_of=_today(),
        generated_at=datetime.now().isoformat(timespec="seconds"),
    )
    return jsonify(BriefingData.model_validate(payload).model_dump())

"""最新批次简报 (老板 backlog #3) 路由。只读, 走 session auth。"""

from __future__ import annotations

from datetime import datetime

from flask import Blueprint, jsonify, render_template
from flask_login import current_user

from app.config import CONFIG
from app.services import briefing as briefing_service
from app.services.analytics._shared import _today

bp = Blueprint("briefing", __name__, url_prefix="/briefing")


@bp.get("")
def page():
    return render_template(
        "index.html",
        enable_transfer=CONFIG.enable_transfer,
        is_admin=(getattr(current_user, "role", None) == "admin"),
    )


@bp.get("/data")
def data():
    # 系统级异常(DB/schema)不在此吞 (review #6): _safe 特意重抛 SQLAlchemyError,
    # 这里不准再 except 接住 — str(exc) 会把 SQL 语句发给客户端, 且丢 Flask 的
    # traceback 日志。让其冒泡 → Flask 通用 500。
    payload = briefing_service.build_briefing(
        as_of=_today(),
        generated_at=datetime.now().isoformat(timespec="seconds"),
    )
    return jsonify(payload)

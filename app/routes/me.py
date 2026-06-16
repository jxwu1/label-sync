"""壳用的当前用户信息端点。只读, session auth。"""

from flask import Blueprint, jsonify
from flask_login import current_user

from app.schemas_api import MeData

bp = Blueprint("api_me", __name__, url_prefix="/api")


@bp.get("/me")
def me():
    # session-only：全局 auth 对正确 X-Upload-Token 会放行(cron 分支),此时 current_user
    # 是匿名,没有 display_name → 显式挡掉,返回 JSON 401 而非 500。
    if not current_user.is_authenticated:
        return jsonify({"error": "unauthenticated"}), 401
    return jsonify(
        MeData(
            display_name=current_user.display_name or current_user.username,
            is_admin=getattr(current_user, "role", None) == "admin",  # 缺字段=非 admin（安全默认）
        ).model_dump()
    )

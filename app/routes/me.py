"""壳用的当前用户信息端点。只读, session auth。"""

from flask import Blueprint, jsonify
from flask_login import current_user

from app.schemas_api import MeData

bp = Blueprint("api_me", __name__, url_prefix="/api")


@bp.get("/me")
def me():
    return jsonify(
        MeData(
            display_name=current_user.display_name or current_user.username,
            is_admin=getattr(current_user, "role", None) == "admin",  # 缺字段=非 admin（安全默认）
        ).model_dump()
    )

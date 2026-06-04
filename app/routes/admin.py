"""Admin 后台 API: 用户管理 + 系统参数 + 主题偏好."""

from flask import Blueprint, jsonify, request
from flask_login import current_user, login_required

from app.auth import hash_password
from app.models import SystemSetting, User, get_session

bp = Blueprint("admin", __name__, url_prefix="/admin")


# ── 用户管理 ──────────────────────────────────────────


@bp.route("/api/users", methods=["GET"])
@login_required
def list_users():
    with get_session() as s:
        users = s.query(User).order_by(User.id).all()
        return jsonify(
            [
                {
                    "id": u.id,
                    "username": u.username,
                    "display_name": u.display_name,
                    "theme": u.theme,
                    "created_at": u.created_at,
                }
                for u in users
            ]
        )


@bp.route("/api/users", methods=["POST"])
@login_required
def create_user():
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    display_name = (data.get("display_name") or "").strip() or None

    if not username or not password:
        return jsonify(ok=False, error="用户名和密码不能为空"), 400

    with get_session() as s:
        if s.query(User).filter_by(username=username).first():
            return jsonify(ok=False, error="用户名已存在"), 409
        u = User(
            username=username, password_hash=hash_password(password), display_name=display_name
        )
        s.add(u)
        s.flush()
        return jsonify(ok=True, id=u.id)


@bp.route("/api/users/<int:uid>", methods=["PUT"])
@login_required
def update_user(uid):
    data = request.get_json(silent=True) or {}
    with get_session() as s:
        u = s.get(User, uid)
        if not u:
            return jsonify(ok=False, error="用户不存在"), 404
        if "display_name" in data:
            u.display_name = (data["display_name"] or "").strip() or None
        if "password" in data and data["password"]:
            u.password_hash = hash_password(data["password"])
        return jsonify(ok=True)


@bp.route("/api/users/<int:uid>", methods=["DELETE"])
@login_required
def delete_user(uid):
    if uid == current_user.id:
        return jsonify(ok=False, error="不能删除自己"), 400
    with get_session() as s:
        u = s.get(User, uid)
        if not u:
            return jsonify(ok=False, error="用户不存在"), 404
        s.delete(u)
        return jsonify(ok=True)


# ── 系统参数 ──────────────────────────────────────────


@bp.route("/api/settings", methods=["GET"])
@login_required
def get_settings():
    with get_session() as s:
        rows = s.query(SystemSetting).order_by(SystemSetting.key).all()
        return jsonify({r.key: r.value for r in rows})


@bp.route("/api/settings", methods=["PUT"])
@login_required
def update_settings():
    data = request.get_json(silent=True) or {}
    with get_session() as s:
        for k, v in data.items():
            row = s.get(SystemSetting, k)
            if row:
                row.value = str(v)
                row.updated_by = current_user.username
            else:
                s.add(SystemSetting(key=k, value=str(v), updated_by=current_user.username))
    return jsonify(ok=True)


# ── 当前用户主题 ──────────────────────────────────────


@bp.route("/api/theme", methods=["PUT"])
@login_required
def update_theme():
    data = request.get_json(silent=True) or {}
    theme = data.get("theme", "")
    if theme not in ("dark", "light"):
        return jsonify(ok=False, error="无效主题"), 400
    with get_session() as s:
        u = s.get(User, current_user.id)
        u.theme = theme
    return jsonify(ok=True, theme=theme)

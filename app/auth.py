"""Flask-Login 初始化 + 登录/注销路由 + seed 首用户."""

from flask import Blueprint, redirect, render_template, request, url_for
from flask_login import LoginManager, login_required, login_user, logout_user
import bcrypt

from app.models import User, SystemSetting, get_session

login_manager = LoginManager()
login_manager.login_view = "auth.login"

bp = Blueprint("auth", __name__)


def init_auth(app):
    app.secret_key = app.secret_key or "label-sync-dev-secret-change-in-prod"
    login_manager.init_app(app)
    app.register_blueprint(bp)
    _seed_admin()

    @app.before_request
    def _require_login():
        from flask_login import current_user
        if request.endpoint and request.endpoint.startswith("auth."):
            return
        if request.endpoint == "static":
            return
        if not current_user.is_authenticated:
            return redirect(url_for("auth.login", next=request.url))

    @app.after_request
    def _no_cache_html(response):
        if response.content_type and "text/html" in response.content_type:
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        return response


@login_manager.user_loader
def _load_user(user_id: str) -> User | None:
    with get_session() as s:
        return s.get(User, int(user_id))


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def check_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


def _seed_admin():
    with get_session() as s:
        if s.query(User).count() > 0:
            return
        admin = User(
            username="admin",
            password_hash=hash_password("admin"),
            display_name="管理员",
            theme="dark",
        )
        s.add(admin)
        defaults = {
            "cn_exchange_rate_rmb_per_eur": "7.8",
            "cn_shipping_rate_rmb_per_m3": "1000.0",
            "retail_to_wholesale_ratio": "2.0",
        }
        for k, v in defaults.items():
            if not s.get(SystemSetting, k):
                s.add(SystemSetting(key=k, value=v, updated_by="seed"))


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return render_template("login.html")

    from flask import jsonify

    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")

    with get_session() as s:
        user = s.query(User).filter_by(username=username).first()
        if not user or not check_password(password, user.password_hash):
            return jsonify(ok=False, error="用户名或密码错误"), 401
        login_user(user, remember=True)
        theme = user.theme
        s.expunge(user)

    next_url = request.args.get("next") or url_for("pages_tasks.index")
    return jsonify(ok=True, theme=theme, next=next_url)


@bp.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("auth.login"))

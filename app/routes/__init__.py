"""HTTP 路由蓝图注册中心。

收集 app/routes/*.py 下定义的所有 Flask Blueprint，按业务可见性顺序注册。
跨站 transfer / collab 蓝图按 CONFIG.enable_transfer 开关延迟引入。
"""

from app.config import CONFIG
from app.routes.admin import bp as admin_bp
from app.routes.analytics import bp as analytics_bp
from app.routes.attendance import bp as attendance_bp
from app.routes.briefing import bp as briefing_bp
from app.routes.dashboard import bp as dashboard_bp
from app.routes.data_quality import bp as data_quality_bp
from app.routes.foreign_customers import bp as foreign_customers_bp
from app.routes.history import bp as history_bp
from app.routes.inventory import bp as inventory_bp
from app.routes.monthly_summary import bp as monthly_summary_bp
from app.routes.pages_tasks import bp as pages_tasks_bp
from app.routes.pda import bp as pda_bp
from app.routes.purchase import bp as purchase_bp
from app.routes.query import bp as query_bp
from app.routes.recent_changes import bp as recent_changes_bp
from app.routes.restock import bp as restock_bp
from app.routes.scan_history import bp as scan_history_bp
from app.routes.stockpile import bp as stockpile_bp


def register_routes(app) -> None:
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(briefing_bp)
    app.register_blueprint(pages_tasks_bp)
    app.register_blueprint(query_bp)
    app.register_blueprint(history_bp)
    app.register_blueprint(recent_changes_bp)
    app.register_blueprint(data_quality_bp)
    app.register_blueprint(purchase_bp)
    app.register_blueprint(monthly_summary_bp)
    app.register_blueprint(attendance_bp)
    app.register_blueprint(scan_history_bp)
    app.register_blueprint(stockpile_bp)
    app.register_blueprint(inventory_bp)
    app.register_blueprint(foreign_customers_bp)
    app.register_blueprint(analytics_bp)
    app.register_blueprint(restock_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(pda_bp)
    if CONFIG.enable_transfer:
        from app.routes.collab import bp as collab_bp
        from app.routes.transfer import bp as transfer_bp

        app.register_blueprint(transfer_bp)
        app.register_blueprint(collab_bp)

from config import CONFIG
from routes_attendance import bp as attendance_bp
from routes_data_quality import bp as data_quality_bp
from routes_history import bp as history_bp
from routes_monthly_summary import bp as monthly_summary_bp
from routes_pages_tasks import bp as pages_tasks_bp
from routes_purchase import bp as purchase_bp
from routes_query import bp as query_bp
from routes_recent_changes import bp as recent_changes_bp
from routes_scan_history import bp as scan_history_bp
from routes_stockpile import bp as stockpile_bp


def register_routes(app) -> None:
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
    if CONFIG.enable_transfer:
        from routes_collab import bp as collab_bp
        from routes_transfer import bp as transfer_bp

        app.register_blueprint(transfer_bp)
        app.register_blueprint(collab_bp)

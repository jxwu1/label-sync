from routes_import import bp as import_bp
from routes_pages_tasks import bp as pages_tasks_bp
from routes_query import bp as query_bp

from config import CONFIG


def register_routes(app) -> None:
    app.register_blueprint(pages_tasks_bp)
    app.register_blueprint(query_bp)
    app.register_blueprint(import_bp)
    if CONFIG.dual_mode:
        from routes_transfer import bp as transfer_bp
        from routes_collab import bp as collab_bp
        app.register_blueprint(transfer_bp)
        app.register_blueprint(collab_bp)

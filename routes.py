from routes_collab import bp as collab_bp
from routes_pages_tasks import bp as pages_tasks_bp
from routes_query import bp as query_bp
from routes_transfer import bp as transfer_bp


def register_routes(app) -> None:
    app.register_blueprint(pages_tasks_bp)
    app.register_blueprint(query_bp)
    app.register_blueprint(transfer_bp)
    app.register_blueprint(collab_bp)

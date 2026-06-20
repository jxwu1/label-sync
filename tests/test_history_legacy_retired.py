"""Phase 4c 守护：旧 SPA 货号历史页已退役（与原 test_history_legacy_preserved 反向）。

货号历史已全量迁 Vue /ui/history（含批次记录），旧 Alpine 页已删。
本测试防止误把旧页文件 / nav 条目重新加回；并正向锁定 /scan_history 蓝图必须保留。
"""

from pathlib import Path

from server import create_app

ROOT = Path(__file__).resolve().parent.parent


def test_old_spa_history_nav_entry_removed():
    store_js = (ROOT / "static" / "js" / "store.js").read_text(encoding="utf-8")
    assert '{ id: "history"' not in store_js, "旧 SPA 侧栏 history 条目应已删（4c）"


def test_old_spa_history_files_removed():
    for rel in (
        "templates/partials/_page_history.html",
        "static/js/history.js",
        "static/js/index-recent-changes.js",
        "static/js/index-scan-history.js",
    ):
        assert not (ROOT / rel).exists(), f"{rel} 应已删除（4c）"


def test_index_html_no_legacy_history_refs():
    index_html = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
    for token in (
        "_page_history.html",
        "js/history.js",
        "index-recent-changes.js",
        "index-scan-history.js",
    ):
        assert token not in index_html, f"index.html 不应再引用 {token}（4c）"


def test_scan_history_blueprint_preserved():
    """反向保险：/scan_history 蓝图必须保留（新页 + 标签页共用二进制下载，绝不可删）。"""
    assert (ROOT / "app" / "routes" / "scan_history.py").exists(), (
        "/scan_history 蓝图必须保留——新 Vue 页与标签处理页都依赖二进制下载"
    )


def _rules():
    app = create_app(seed_auth=False, prewarm=False)
    return [r.rule for r in app.url_map.iter_rules()]


def test_recent_changes_http_routes_unregistered():
    rules = _rules()
    assert not any(r.startswith("/recent_changes") for r in rules), (
        "旧 /recent_changes/* HTTP 路由应已注销（4c）"
    )


def test_new_and_scan_routes_still_registered():
    rules = _rules()
    assert any(r.startswith("/api/history/recent-changes") for r in rules), (
        "新 /api/history/recent-changes/* 必须仍在"
    )
    assert any(r.startswith("/scan_history") for r in rules), (
        "/scan_history/* 必须仍在（新页 + 标签页下载）"
    )

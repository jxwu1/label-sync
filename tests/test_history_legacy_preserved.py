"""HC-1 守护：货号历史 Phase 1 是 additive 迁移，旧 SPA history 必须保留。

防止后续误把旧页当 forecast_eval 那样退役——Phase 1 完整 parity 未达成前，
旧版完整分析页是用户唯一的分析入口。
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_old_spa_history_nav_entry_preserved():
    store_js = (ROOT / "static" / "js" / "store.js").read_text(encoding="utf-8")
    assert '{ id: "history"' in store_js, "旧 SPA 侧栏 history 入口被删——违反 HC-1"


def test_old_spa_history_partial_preserved():
    assert (ROOT / "templates" / "partials" / "_page_history.html").exists(), (
        "旧 history 模板被删——违反 HC-1"
    )


def test_old_spa_history_js_preserved():
    assert (ROOT / "static" / "js" / "history.js").exists(), "旧 history.js 被删——违反 HC-1"

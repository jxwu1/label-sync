"""Vue /ui/* 页面浏览器烟雾（前端独立化 §11 迁移产物）。

验证「构建产物加载 + SPA 路由 + 同源 Flask /api/* + reload + 无 console error」。
**不验**生产 Caddy/nginx 剥前缀反代——那归部署 smoke。

前置：frontend/dist 必须已构建（被 gitignore）。标准命令 = `npm run build` → `pytest e2e/`。
dist 缺失时这些用例 skip（不是 fail），CI 的 e2e-smoke job 有构建步骤故必跑。
"""

from pathlib import Path

import pytest

_DIST_INDEX = Path(__file__).resolve().parent.parent / "frontend" / "dist" / "index.html"

requires_dist = pytest.mark.skipif(
    not _DIST_INDEX.exists(),
    reason="frontend/dist 未构建——先跑 `npm run build`（CI e2e-smoke 有构建步骤）",
)

# Vue 应用挂载点（vite 默认 #app），挂载后其子节点非空即视为成功渲染
_APP_MOUNTED = (
    "document.querySelector('#app') && document.querySelector('#app').children.length > 0"
)

_UI_PAGES = ["/ui/briefing", "/ui/forecast-eval", "/ui/history"]


@pytest.mark.smoke
@requires_dist
@pytest.mark.parametrize("path", _UI_PAGES)
def test_ui_page_loads_and_reloads_no_console_error(live_server, page_with_console, path) -> None:
    page = page_with_console

    # 首次加载：Vue 挂载成功（静态 chunk 经 /ui/assets/* 同源加载）
    page.goto(live_server + path)
    page.wait_for_function(_APP_MOUNTED, timeout=10000)

    # 刷新：SPA fallback 命中 index.html，再次挂载成功
    page.reload()
    page.wait_for_function(_APP_MOUNTED, timeout=10000)

    assert page.console_errors == [], f"{path} console errors: {page.console_errors}"

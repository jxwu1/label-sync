"""验证 nav store onFirstActivate 钩子：sa/dq 进页时自动 load，省去用户点刷新一步。

抓的是只有真浏览器才能验的「Alpine store 时序 + module script 注册路径」回归：
- onFirstActivate 注册时机晚于 alpine:init（module script 在 classic defer 之后）
- 注册路径正确性：load() 真被触发了（看 DOM 副作用，不只是看 store 内部 flag）
- 重复 switch 不重复触发（caching 语义）
"""

_ALPINE_SETTLE_MS = 300


def _wait_alpine_ready(page) -> None:
    page.wait_for_function("window.Alpine !== undefined", timeout=5000)
    page.wait_for_timeout(_ALPINE_SETTLE_MS)


def test_sales_analytics_lazy_load_fires_on_first_switch(live_server, page_with_console) -> None:
    """切到销售分析 → load() 自动跑 → #saStatTotal 显示「共 N 个 SKU」。"""
    page = page_with_console
    page.goto(live_server + "/")
    _wait_alpine_ready(page)

    # 初始：#saStatTotal 是空（page 还没切过去 + load 未跑）
    assert page.evaluate("document.getElementById('saStatTotal').textContent") == ""

    page.evaluate("Alpine.store('nav').switch('sales_analytics')")
    page.locator("#pageSalesAnalytics.active").wait_for(state="attached", timeout=2000)

    # load() 跑完后 saStatTotal 必然有 "共 N 个 SKU" 文本（沙箱无数据 N=0 也会写）
    page.wait_for_function(
        "document.getElementById('saStatTotal').textContent.match(/^共 \\d+ 个 SKU$/)",
        timeout=5000,
    )

    assert page.console_errors == [], f"console errors: {page.console_errors}"


def test_data_quality_lazy_load_fires_on_first_switch(live_server, page_with_console) -> None:
    """切到数据质量 → refresh() 自动跑 → #dqStatMulti 数字从 "—" 变成 N。"""
    page = page_with_console
    page.goto(live_server + "/")
    _wait_alpine_ready(page)

    page.evaluate("Alpine.store('nav').switch('data_quality')")
    page.locator("#pageDataQuality.active").wait_for(state="attached", timeout=2000)

    # refresh() 成功路径 → dq stat 数字被填充（不是初始的 "—"）
    page.wait_for_function(
        "document.querySelector('#dqStatMulti .dq-stat-num').textContent.match(/^\\d/)",
        timeout=5000,
    )

    assert page.console_errors == [], f"console errors: {page.console_errors}"


def test_lazy_load_fires_only_once_across_switches(live_server, page_with_console) -> None:
    """切到 sa → 切走 → 再切回 sa：load 只跑一次（验缓存语义，避免每次切回都重 fetch）。"""
    page = page_with_console
    page.goto(live_server + "/")
    _wait_alpine_ready(page)

    # 第一次切到 sa
    page.evaluate("Alpine.store('nav').switch('sales_analytics')")
    page.wait_for_function(
        "document.getElementById('saStatTotal').textContent.match(/^共 \\d+ 个 SKU$/)",
        timeout=5000,
    )

    # _initedPages 应该含 sales_analytics
    inited = page.evaluate("Alpine.store('nav')._initedPages")
    assert "sales_analytics" in inited, f"_initedPages: {inited}"

    # 切走再切回
    page.evaluate("Alpine.store('nav').switch('main')")
    page.evaluate("Alpine.store('nav').switch('sales_analytics')")
    page.wait_for_timeout(_ALPINE_SETTLE_MS)

    # _initedPages 仍只有一次 sales_analytics（不重复入队）
    inited_after = page.evaluate("Alpine.store('nav')._initedPages")
    sa_count = sum(1 for p in inited_after if p == "sales_analytics")
    assert sa_count == 1, f"sales_analytics 应该只 init 一次，实际 {sa_count} 次：{inited_after}"

    assert page.console_errors == [], f"console errors: {page.console_errors}"

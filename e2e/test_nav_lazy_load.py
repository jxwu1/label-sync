"""验证 nav store onFirstActivate 钩子：进页时自动 load，省去用户点刷新一步。

抓的是只有真浏览器才能验的「Alpine store 时序 + module script 注册路径」回归：
- onFirstActivate 注册时机晚于 alpine:init（module script 在 classic defer 之后）
- 注册路径正确性：load() 真被触发了（看 DOM 副作用，不只是看 store 内部 flag）
- 重复 switch 不重复触发（caching 语义）

原以 sales_analytics 为载体；该页已退役（迁 Vue），改用仍采用 onFirstActivate 的
data_quality 覆盖「首次加载」+「重复切换只触发一次」。
"""

_ALPINE_SETTLE_MS = 300

# refresh() 成功后会把 7 个 tab-count 填成数字（空沙箱也写 "0"）。null 安全，避免
# 元素未挂时 .textContent 抛 TypeError。dq 页改版 dq-v2 后旧 #dqStatMulti 已不存在。
_DQ_LOADED = (
    "(() => { const e = document.querySelector('#dqTabStrip .tab-count[data-c=\"whitespace\"]');"
    " return !!(e && /^\\d/.test(e.textContent)); })()"
)


def _wait_alpine_ready(page) -> None:
    page.wait_for_function("window.Alpine !== undefined", timeout=5000)
    page.wait_for_timeout(_ALPINE_SETTLE_MS)


def test_data_quality_lazy_load_fires_on_first_switch(live_server, page_with_console) -> None:
    """切到数据质量 → refresh() 自动跑 → #dqStatMulti 数字从 "—" 变成 N。"""
    page = page_with_console
    page.goto(live_server + "/")
    _wait_alpine_ready(page)

    page.evaluate("Alpine.store('nav').switch('data_quality')")
    page.locator("#pageDataQuality.active").wait_for(state="attached", timeout=2000)

    # refresh() 成功路径 → dq stat 数字被填充（不是初始的 "—"）
    page.wait_for_function(_DQ_LOADED, timeout=5000)

    assert page.console_errors == [], f"console errors: {page.console_errors}"


def test_lazy_load_fires_only_once_across_switches(live_server, page_with_console) -> None:
    """切到 dq → 切走 → 再切回 dq：load 只跑一次（验缓存语义，避免每次切回都重 fetch）。"""
    page = page_with_console
    page.goto(live_server + "/")
    _wait_alpine_ready(page)

    # 第一次切到 data_quality
    page.evaluate("Alpine.store('nav').switch('data_quality')")
    page.wait_for_function(_DQ_LOADED, timeout=5000)

    # _initedPages 应该含 data_quality
    inited = page.evaluate("Alpine.store('nav')._initedPages")
    assert "data_quality" in inited, f"_initedPages: {inited}"

    # 切走再切回
    page.evaluate("Alpine.store('nav').switch('main')")
    page.evaluate("Alpine.store('nav').switch('data_quality')")
    page.wait_for_timeout(_ALPINE_SETTLE_MS)

    # _initedPages 仍只有一次 data_quality（不重复入队）
    inited_after = page.evaluate("Alpine.store('nav')._initedPages")
    dq_count = sum(1 for p in inited_after if p == "data_quality")
    assert dq_count == 1, f"data_quality 应该只 init 一次，实际 {dq_count} 次：{inited_after}"

    assert page.console_errors == [], f"console errors: {page.console_errors}"

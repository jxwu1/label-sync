"""回归：PDA 扫描页前端关键不变量。

真机暴露的 bug：扫描枪是键盘 wedge（逐字符 + Enter 喂给焦点元素），但旧版把扫码灌进
一个隐藏的、屏幕外输入框——手机浏览器拒绝给不可见输入自动聚焦，于是扫了没地方落、
表格永远空。修复：整页 document 级捕获 + 预渲染空表格 + 静态资源版本号防缓存。
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PDA_JS = (ROOT / "static" / "js" / "pda.js").read_text(encoding="utf-8")
PDA_HTML = (ROOT / "templates" / "pda.html").read_text(encoding="utf-8")


def test_scan_input_is_visible_and_focusable():
    # 扫描枪把字符注入「聚焦的可编辑输入框」→ 必须有一个可见、可聚焦、带光标的输入框接住
    assert 'id="scanInput"' in PDA_HTML
    # 输入框不能被推到屏幕外（旧 bug：left:-9999px 隐藏 → 手机不给聚焦 → 扫不进）
    css = (ROOT / "static" / "css" / "pda.css").read_text(encoding="utf-8")
    assert "-9999px" not in css
    # 点表格 → 聚焦扫描框（像点 Excel 格子唤出光标）
    assert "focusScan" in PDA_JS
    assert "addEventListener('click', focusScan)" in PDA_JS


def test_assets_cache_busted():
    # pda.js / pda.css 必须带版本号，否则改了扫码逻辑 PDA 还跑旧缓存
    assert "js/pda.js') }}?v={{ asset_v }}" in PDA_HTML
    assert "css/pda.css') }}?v={{ asset_v }}" in PDA_HTML


def test_empty_grid_prerendered():
    # 预渲染空行：页面一打开就像 Excel 表格，降低学习成本
    assert "MIN_ROWS" in PDA_JS
    assert "emptyRowHtml" in PDA_JS


def test_asset_version_is_8_hex():
    from app.routes.pda import _asset_version

    v = _asset_version()
    assert len(v) == 8
    int(v, 16)  # 必须是合法 hex（内容哈希）

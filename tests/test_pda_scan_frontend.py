"""回归：PDA 扫描页前端关键不变量。

真机暴露的 bug：扫描枪是键盘 wedge（逐字符 + Enter 喂给焦点元素），但旧版把扫码灌进
一个隐藏的、屏幕外输入框——手机浏览器拒绝给不可见输入自动聚焦，于是扫了没地方落、
表格永远空。修复：整页 document 级捕获 + 预渲染空表格 + 静态资源版本号防缓存。
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PDA_JS = (ROOT / "static" / "js" / "pda.js").read_text(encoding="utf-8")
PDA_HTML = (ROOT / "templates" / "pda.html").read_text(encoding="utf-8")


def test_scan_capture_is_document_level():
    # 扫码必须整页捕获，不依赖隐藏输入框焦点
    assert "document.addEventListener('keydown'" in PDA_JS
    assert "scanBuf" in PDA_JS
    # 旧的屏幕外隐藏输入框已移除（正是它导致扫不进）
    assert 'id="scanInput"' not in PDA_HTML


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

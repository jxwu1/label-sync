"""回归：/pda 扫描端必须能退出（登出），否则操作员/管理员被困在 kiosk 页。

缺陷背景：pda.html 是独立 kiosk 页，原本无任何导航/退出入口；scanner 角色又被
before_request 限制只能访问 /pda，导致"完全退不出去"。/logout（auth.* 白名单）
始终可达，缺的只是页面上的入口按钮 —— 这两条断言守住入口存在且指向 /logout。
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_pda_template_has_exit_button():
    html = (ROOT / "templates" / "pda.html").read_text(encoding="utf-8")
    assert 'id="exitBtn"' in html, "扫描页缺少退出按钮，操作员会被困在 kiosk 页"


def test_pda_js_exit_targets_logout():
    js = (ROOT / "static" / "js" / "pda.js").read_text(encoding="utf-8")
    assert "exitBtn" in js, "exitBtn 未绑定事件"
    assert "/logout" in js, "退出未跳转 /logout，scanner 跳别处会被弹回 /pda"

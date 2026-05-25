"""
refresh_cookie.py — Playwright headless 登录 boson, 拿 PHPSESSID 写入 cookie.txt.

配置 (从 scraper/.env 读):
  BOSON_BASE_URL  — 默认 http://bosonapp.local:8137
  BOSON_USERNAME  — 登录用户名
  BOSON_PASSWORD  — 登录密码

退出码:
  0 = 成功写入 cookie.txt
  1 = 登录失败 / 拿不到 cookie
"""

import os
import sys
from pathlib import Path

_SCRAPER_DIR = Path(__file__).resolve().parent
OUT_FILE = _SCRAPER_DIR / "cookie.txt"


def _load_env() -> None:
    """从 scraper/.env 读环境变量 (简易, 不引 python-dotenv)."""
    env_path = _SCRAPER_DIR / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())


def main() -> int:
    _load_env()

    base_url = os.environ.get("BOSON_BASE_URL", "http://bosonapp.local:8137")
    username = os.environ.get("BOSON_USERNAME", "")
    password = os.environ.get("BOSON_PASSWORD", "")
    add_code = os.environ.get("BOSON_ADD_CODE", "")

    if not username or not password:
        print(
            "scraper/.env 缺 BOSON_USERNAME 或 BOSON_PASSWORD.\n"
            "在 .env 加:\n"
            "  BOSON_USERNAME=你的用户名\n"
            "  BOSON_PASSWORD=你的密码\n"
            "  BOSON_ADD_CODE=附加码 (如需要)",
            file=sys.stderr,
        )
        return 1

    login_url = f"{base_url}/boson/index.php"
    print(f"→ {login_url}", file=sys.stderr)

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("缺依赖 playwright: pip install playwright && playwright install chromium", file=sys.stderr)
        return 1

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context()
        page = ctx.new_page()

        try:
            page.goto(login_url, timeout=15_000)
            page.wait_for_selector("#username", state="visible", timeout=10_000)

            if add_code:
                page.fill("#add_code", add_code)
            page.fill("#username", username)
            page.fill("#passwd", password)
            page.click("#login_form input[type=button]")

            page.wait_for_timeout(3000)

            cookies = ctx.cookies()
            php_session = next(
                (c for c in cookies if c["name"] == "PHPSESSID" and "boson" in c.get("domain", "")),
                None,
            )

            if not php_session:
                all_names = [c["name"] for c in cookies]
                print(f"登录后没拿到 PHPSESSID. cookies: {all_names}", file=sys.stderr)
                print("可能原因: 账密错误 / boson 页面结构变了", file=sys.stderr)
                return 1

            value = php_session["value"]
            OUT_FILE.write_text(value, encoding="utf-8")
            print(f"✓ 写入 {OUT_FILE} ({len(value)} 字符)", file=sys.stderr)
            return 0

        except Exception as exc:
            print(f"登录失败: {exc}", file=sys.stderr)
            return 1
        finally:
            browser.close()


if __name__ == "__main__":
    sys.exit(main())

"""
Pixel-perfect verification tool for html-mirror skill.

Modes:
  Capture:  python scripts/screenshot.py <url_or_file> <output.png> [--width=1440] [--height=900] [--theme=dark]
  Diff:     python scripts/screenshot.py --diff <ref.png> <live.png> <diff_output.png>
  Audit:    python scripts/screenshot.py --audit <url> --selectors ".sidebar,.header,.pnl"

Examples:
  python scripts/screenshot.py http://127.0.0.1:8899/06-foreign-customers.html screenshots/ref-06.png --theme=dark
  python scripts/screenshot.py http://127.0.0.1:5000/ screenshots/live-06.png --theme=dark
  python scripts/screenshot.py --diff screenshots/ref-06.png screenshots/live-06.png screenshots/diff-06.png
  python scripts/screenshot.py --audit http://127.0.0.1:5000/ --selectors ".fc-control,.fc-stats,.fc-panel,.fc-table th"
"""

import sys, asyncio, os


async def capture(target, output, width=1440, height=900, theme="dark"):
    """Screenshot a URL or local HTML file."""
    from playwright.async_api import async_playwright

    os.makedirs(os.path.dirname(output) or ".", exist_ok=True)
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={"width": width, "height": height})

        if target.startswith("http"):
            await page.goto(target, wait_until="networkidle")
        else:
            abs_path = os.path.abspath(target)
            await page.goto(f"file://{abs_path}", wait_until="networkidle")

        # Set theme
        await page.evaluate(f"""() => {{
            const body = document.body || document.documentElement;
            if (body) body.setAttribute('data-theme', '{theme}');
        }}""")
        await page.wait_for_timeout(600)  # wait for theme transition + JS render

        await page.screenshot(path=output, full_page=True)
        await browser.close()
        print(f"OK  captured -> {output}")


def diff_images(ref_path, live_path, diff_path):
    """Generate a red-highlighted diff image. Returns mismatch percentage."""
    from PIL import Image, ImageChops
    import numpy as np

    os.makedirs(os.path.dirname(diff_path) or ".", exist_ok=True)
    ref = Image.open(ref_path).convert("RGB")
    live = Image.open(live_path).convert("RGB")

    if ref.size != live.size:
        print(f"WARN  sizes differ: ref={ref.size} live={live.size}, resizing live to match")
        live = live.resize(ref.size, Image.LANCZOS)

    diff = ImageChops.difference(ref, live)
    diff_array = np.array(diff)

    threshold = 10
    mask = np.any(diff_array > threshold, axis=2)

    highlight = np.array(live.copy())
    highlight[mask] = [255, 0, 0]

    Image.fromarray(highlight).save(diff_path)

    total_pixels = mask.size
    mismatch_pixels = int(mask.sum())
    pct = (mismatch_pixels / total_pixels) * 100

    if pct < 0.5:
        print(f"PASS  {pct:.2f}% mismatch ({mismatch_pixels:,} pixels) -- within tolerance")
    else:
        print(f"FAIL  {pct:.2f}% mismatch ({mismatch_pixels:,} pixels) -- needs fixing")

    print(f"      diff saved -> {diff_path}")
    return pct


async def audit(url, selectors, theme="dark"):
    """Extract computed styles from live page and print them for comparison."""
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={"width": 1440, "height": 900})
        await page.goto(url, wait_until="networkidle")

        await page.evaluate(f"""() => {{
            document.body.setAttribute('data-theme', '{theme}');
        }}""")
        await page.wait_for_timeout(500)

        selector_list = [s.strip() for s in selectors.split(",")]

        results = await page.evaluate(
            """(selectors) => {
            const out = {};
            for (const sel of selectors) {
                const el = document.querySelector(sel);
                if (!el) { out[sel] = 'NOT_FOUND'; continue; }
                const s = getComputedStyle(el);
                out[sel] = {
                    width: s.width,
                    height: s.height,
                    padding: s.padding,
                    margin: s.margin,
                    gap: s.gap,
                    fontSize: s.fontSize,
                    fontWeight: s.fontWeight,
                    fontFamily: s.fontFamily.split(',')[0].trim(),
                    lineHeight: s.lineHeight,
                    color: s.color,
                    backgroundColor: s.backgroundColor,
                    borderRadius: s.borderRadius,
                    border: s.border,
                    boxShadow: s.boxShadow === 'none' ? 'none' : s.boxShadow.substring(0, 60)
                };
            }
            return out;
        }""",
            selector_list,
        )

        await browser.close()

        print("AUDIT  computed styles from live page:")
        print("=" * 70)
        for sel, vals in results.items():
            print(f"\n  {sel}:")
            if vals == "NOT_FOUND":
                print(f"    ! NOT FOUND in DOM")
                continue
            for prop, val in vals.items():
                print(f"    {prop}: {val}")
        print("\n" + "=" * 70)
        print("Compare each value against the demo HTML's CSS.")
        print("Any difference = a bug to fix.")


if __name__ == "__main__":
    args = sys.argv[1:]

    if "--diff" in args:
        idx = args.index("--diff")
        ref = args[idx + 1]
        live = args[idx + 2]
        out = args[idx + 3]
        diff_images(ref, live, out)

    elif "--audit" in args:
        idx = args.index("--audit")
        url = args[idx + 1]
        sel_idx = args.index("--selectors")
        selectors = args[sel_idx + 1]
        theme = "dark"
        for a in args:
            if a.startswith("--theme="):
                theme = a.split("=")[1]
        asyncio.run(audit(url, selectors, theme))

    else:
        target = args[0]
        output = args[1]
        width, height, theme = 1440, 900, "dark"
        for a in args[2:]:
            if a.startswith("--width="):
                width = int(a.split("=")[1])
            if a.startswith("--height="):
                height = int(a.split("=")[1])
            if a.startswith("--theme="):
                theme = a.split("=")[1]
        asyncio.run(capture(target, output, width, height, theme))

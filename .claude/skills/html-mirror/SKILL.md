---
name: html-mirror
description: Pixel-perfect implementation from HTML design demos into live Flask/Jinja pages. Use this skill whenever the user asks to implement, build, convert, or replicate any HTML demo or mockup into their actual project — including when they say things like "make it look like the demo", "implement the dashboard page", "convert this HTML to Jinja", or reference files in a design-demos directory. Also trigger when the user complains about visual differences between their site and the demo, or asks to "fix the styling" or "match the design". This skill runs a Playwright-powered screenshot comparison loop that catches every mismatched pixel between reference and implementation.
---

# html-mirror: Demo → Live, Pixel-Perfect

You have HTML demo files that represent the finished visual design.
Your job: make the live Flask/Jinja site look IDENTICAL to the demo.

Why this skill exists: Claude Code's default behavior when implementing frontends is to "interpret" designs — choosing its own spacing, approximating colors, using `auto` and `inherit` for sizing. This produces output that looks "close enough" to Claude but is visibly wrong to the user. This skill eliminates interpretation entirely. You are a copy machine, not a designer.

## How It Works (Overview)

```
Phase 1: READ the demo HTML — memorize every CSS value
Phase 2: COPY the CSS into your implementation — verbatim, not interpreted  
Phase 3: SCREENSHOT both demo and live site — compare pixel-by-pixel
Phase 4: FIX every difference — loop until < 0.5% pixel mismatch
```

---

## Phase 1: Reconnaissance

Before writing ANY implementation code, you must read and internalize the design source files.

### Read the demo HTML completely

```bash
cat docs/design-demos/<page>.html
```

You're looking for three things:

1. **CSS variables** — every `--bg-*`, `--ink-*`, `--sp-*`, `--fs-*`, `--r-*` value. These are the design system. Copy them exactly.
2. **Component classes** — `.btn`, `.pill`, `.pnl`, `.tbl`, `.sys-row`, etc. Each has explicit px values for padding, font-size, gap, border-radius. These are not suggestions — they are specifications.
3. **HTML structure** — the DOM nesting, what tags are used, what's inside what. Your Jinja template should produce the same DOM.

### Read the constraint files

If `design-context.md` or `size-constraints.md` exist in the project, read them. They contain mandatory rules like "sidebar is always 200px" and "never use auto for card height". These override your instincts.

### Why this matters

The #1 failure mode is skipping this step and "winging it" based on a glance at the demo. Every time Claude Code has produced bad frontend output for this user, it was because it didn't read the actual CSS values and instead guessed. Reading takes 2 minutes. Fixing a bad implementation takes 20.

---

## Phase 2: Implementation

### The CSS Copy Strategy

The demo HTML contains a `<style>` block with the complete design system. Your implementation strategy:

1. **Extract the `<style>` block** into `static/css/design-system.css` — nearly verbatim
2. **Shared shell** (sidebar, header, theme switch) goes into `base.html`
3. **Page content** goes into `{% block content %}` per page

The CSS file should be recognizably the same code as the demo's style block, not a "translation" or "adaptation".

### Values You Must Copy Exactly

These are the values the user's design system specifies in absolute px. Using anything else WILL produce visible differences:

| What | Demo says | You write | NEVER write |
|------|-----------|-----------|-------------|
| Sidebar width | `200px` | `width: 200px` | `width: 15%`, `flex: 1` |
| Header height | `48px` | `height: 48px` | `height: auto`, `min-height: 3rem` |
| Body font | `13px` | `font-size: 13px` | `font-size: 0.8125rem` |
| Card padding | `14px 16px` | `padding: 14px 16px` | `padding: 1rem` |
| Gap between items | `var(--sp-3)` = `12px` | `gap: var(--sp-3)` | `gap: 0.75rem`, `gap: 1em` |
| Colors | `#E5484D` | `var(--accent)` which is `#E5484D` | `red-500`, `#e54` |

The reason: this user's experience has been that every time Claude Code uses relative units, auto-sizing, or Tailwind color names, the result visually diverges from the demo. Absolute px values in CSS variables is the design system's contract.

### Forbidden Patterns

These CSS patterns are banned because they create unpredictable sizing:

```
height: auto          →  use explicit px or min-height
width: fit-content    →  use explicit px or grid 1fr
padding: inherit      →  use explicit px
font-size: 0.875rem   →  use px from --fs-* variables
gap: 1rem             →  use --sp-* variables (which are px)
```

The reason they're banned isn't that they're bad CSS — it's that they give Claude Code room to guess, and Claude Code's guesses don't match the demo.

### Isolation Rule: Never Modify Shared CSS for a Single Page

When the project has multiple pages sharing parent containers (`.content`, `.page`, `.shell`), **NEVER modify shared CSS to fix a single page's layout**. Instead:

1. Use page-specific CSS overrides: `#pageXxx.active { ... }`
2. If a shared class needs different behavior on one page, add a page-scoped selector
3. Before editing any shared CSS rule, grep for all pages that use it and verify the change won't break them

Why: modifying `.content { padding }` to fix the labeling page will break every other page's padding. This has happened — don't repeat it.

---

## Phase 3: Visual Verification Loop

This is the critical phase. You've written code — now prove it matches.

### Setup: Screenshot Script

Create `tools/compare_screenshots.py` if it doesn't exist:

```python
"""Take screenshots of design HTML and actual site for comparison."""
from playwright.sync_api import sync_playwright

def screenshot_both(design_url, live_url, nav_action=None, width=1500, height=900):
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": width, "height": height})

        # Screenshot design HTML
        page.goto(design_url)
        page.wait_for_timeout(500)
        page.screenshot(path="tools/screenshot_design.png", full_page=False)

        # Screenshot live site (login if needed)
        page.goto(live_url + "/login")
        page.fill('input[name="username"]', "admin")
        page.fill('input[name="password"]', "admin")
        page.click('button[type="submit"]')
        page.wait_for_timeout(1000)

        if nav_action:
            nav_action(page)
            page.wait_for_timeout(500)

        page.screenshot(path="tools/screenshot_actual.png", full_page=False)
        browser.close()
```

### The Loop

**Step 1 — Screenshot both versions at the same viewport**

**Step 2 — Read both screenshots and visually compare:**
- Overall layout proportions (sidebar width, column widths, panel heights)
- Component sizing (padding, font size, gap)
- Color matching between themes
- Element positioning (does the right column reach the bottom?)

**Step 3 — List every mismatch**, no matter how small:

```
MISMATCHES FOUND:
- .sidebar width: expected 200px, got 180px
- .pnl-hd padding: expected 10px 16px, got 12px 16px  
- body font-size: expected 13px, got 16px
- .btn border-radius: expected 4px, got 6px
```

**Step 4 — Fix all mismatches by copying the exact value from the demo CSS**, then go back to Step 1.

### Exit condition

- Visual comparison: no visible differences at 1:1 zoom
- Both dark AND light themes pass
- **Regression check: switch to every other page in the app and confirm none are broken by the changes**

"Close enough" is not an exit condition. The user has explicitly said they want identical output. 2px off is a bug.

---

## Phase 4: Page-by-Page Rollout

After the shell + first page passes, each subsequent page is faster because shared CSS is already correct.

Recommended order:
1. Shell (sidebar, header, theme switch) + design-system.css — extracted from any demo
2. Dashboard (the page with the most shared components)
3. Remaining pages in sidebar order

For each page, run the full Phase 3 loop before moving to the next.

---

## Common Failures and Why They Happen

**Everything looks smaller than the demo**: `body { font-size }` is wrong. The demo uses `13px`. If your base is different, every em/rem cascades wrong. Check this first.

**Massive whitespace / content doesn't fill the page**: The shell layout is wrong. Sidebar needs `width: 200px; flex-shrink: 0`, main area needs `flex: 1; min-width: 0`. Check `display: flex` on `.shell`.

**Cards are different heights from each other**: You used `height: auto` or no min-height. The design system says `min-height: 80px` for stat cards. Grid children stretch to the tallest sibling, but only if content fills them — `min-height` prevents collapse.

**Colors look "almost right" but slightly off**: You used a Tailwind color name or an approximation. Check that CSS variables match the demo's hex values exactly. `#E5484D` ≠ `#DC3545` — these are the dark vs light theme values of `--accent`.

**Fonts look different**: Missing Google Fonts `<link>` tag. Copy it from the demo's `<head>`. The demo uses Inter, JetBrains Mono, and Space Grotesk.

**Page container height mismatch between pages**: Each page has its own `#pageXxx.active` override with explicit `height: calc(100vh - Npx)`. The `N` depends on how many shell elements (header, substrip) are visible. Don't use the same `N` for pages with different shell configurations. Calculate: `N = header(48) + substrip(28 if shown) + borders`.

**Modifying shared CSS breaks other pages**: Before editing `.content`, `.page`, `.shell`, or any non-page-scoped class, grep for every page that uses it. If more than one page is affected, use a page-specific override instead.

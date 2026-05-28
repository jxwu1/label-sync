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

### The CSS Extraction Rule (Most Important Rule in This Skill)

The demo HTML contains a `<style>` block with the complete design system. Your implementation strategy:

1. **Literally copy the `<style>` block** from the demo HTML into `static/css/design-system.css`
2. Run the extraction once from the most complete demo (usually labeling or dashboard)
3. **Do not rewrite, refactor, translate to Tailwind, or "clean up" the CSS**
4. Shared shell (sidebar, header, theme switch) goes into `base.html`
5. Page content goes into `{% block content %}` per page
6. Every Jinja template links `<link rel="stylesheet" href="/static/css/design-system.css">`

Why this is the #1 rule: The failure that has repeatedly happened is that Claude Code reads `.btn { padding: 5px 12px; font-size: 11px }` in the demo, then writes `class="px-2 py-1 text-xs"` in the template, which computes to `padding: 4px 8px; font-size: 12px` — close but wrong. Every component, every property, every pixel is off by a little, and it adds up to "everything looks smaller".

The fix is to not translate at all. The demo CSS IS the production CSS. Extract it as-is. If you need to split it into multiple files for organization (base.css, components.css, pages/), that's fine, but every class definition must contain the same property values as the demo, character for character.

**Self-check before committing CSS**: open the demo HTML and your CSS file side by side. Every `.btn`, `.pill`, `.pnl`, `.tbl th`, `.nav-item` etc. should have identical property values. If any value differs, it's a bug.

**NEVER translate demo CSS to Tailwind utility classes.** The demo CSS is the source of truth. Tailwind utilities are approximations. Approximations accumulate error.

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

---

## Phase 3: Visual Verification Loop

This is the critical phase. You've written code — now prove it matches.

### Setup: Screenshot Script

The project should have `scripts/screenshot.py`. If it doesn't exist, create it — see `references/screenshot-script.md` for the full code.

### The Loop

**Step 1 — Screenshot both versions at the same viewport:**

```bash
# Reference (demo HTML file)
python scripts/screenshot.py docs/design-demos/01-dashboard.html screenshots/ref.png --width=1440 --theme=dark

# Live (your implementation)  
python scripts/screenshot.py http://localhost:5000/ screenshots/live.png --width=1440 --theme=dark
```

**Step 2 — Generate a pixel diff:**

```bash
python scripts/screenshot.py --diff screenshots/ref.png screenshots/live.png screenshots/diff.png
```

This overlays red on every pixel that differs. The output tells you the mismatch percentage.

**Step 3 — Also run a numerical audit** (zero image cost):

Use Playwright to extract `getComputedStyle` from key elements on the live page and compare against the values in the demo CSS. This catches differences that are hard to see in screenshots (1-2px padding, slightly wrong font-weight).

```bash
python scripts/screenshot.py --audit http://localhost:5000/ --selectors ".sidebar,.header,.pnl,.btn,.tbl th,.tbl td"
```

**Step 4 — List every mismatch**, no matter how small:

```
MISMATCHES FOUND:
- .sidebar width: expected 200px, got 180px
- .pnl-hd padding: expected 10px 16px, got 12px 16px  
- body font-size: expected 13px, got 16px
- .btn border-radius: expected 4px, got 6px
```

**Step 5 — Fix all mismatches**, then go back to Step 1.

### Exit condition

- Pixel diff < 0.5% (remaining noise is anti-aliasing)
- Numerical audit: zero value mismatches
- Both dark AND light themes pass

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

---

## Reference Files

For implementation details that would bloat this skill, read these on demand:

- `references/screenshot-script.md` — Full screenshot.py with diff and audit modes
- `references/css-variable-catalog.md` — Complete list of all design system variables and their values

Create these reference files in the skill directory when setting up the project.

---
name: playwright-edge-windows
description: 'Launch and drive a headless Microsoft Edge browser with Playwright on Windows. Use this whenever the user wants to run Playwright scripts against the locally installed Edge browser, do headless browser automation, scraping, or UI-driven data collection on Windows, or when a Playwright task needs a real Chromium-family browser (Edge) instead of Playwright''s bundled Chromium. Marked Windows-only: this skill assumes the default Edge install path under C:\Program Files (x86)\Microsoft\Edge. Triggers on phrases like "use Edge", "headless Edge", "playwright 抓取", "无头浏览器", or any scraping/automation task where the environment is Windows.'
---

# Playwright + Headless Edge on Windows

Launch the locally installed Microsoft Edge with Playwright in headless mode, make it look like a normal Chrome browser, and drive it reliably.

## Platform
**Windows only.** The Edge default install path differs on macOS/Linux, and this skill relies on the Windows path:
`C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe`
On 64-bit-only installs it may be under `C:\Program Files\Microsoft\Edge\Application\msedge.exe` — check both if launch fails.

## Prerequisites
- Windows with Microsoft Edge installed (ships with Windows 10/11 by default).
- Python 3.9+ with `pip install playwright`.
- No `playwright install` needed: Edge is already a full browser, so you can skip downloading Playwright's Chromium.

## Launching Edge headlessly
Always launch the installed Edge binary explicitly via `executable_path`. This avoids downloading Playwright's Chromium and uses the user's real browser:
```python
from playwright.sync_api import sync_playwright

EDGE = r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'

with sync_playwright() as p:
    b = p.chromium.launch(
        executable_path=EDGE,
        headless=True,
        args=['--disable-blink-features=AutomationControlled'],
    )
    ctx = b.new_context(
        user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36',
        locale='en-US',
        viewport={'width': 1440, 'height': 900},
    )
    page = ctx.new_page()
    page.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined});")
    ...
    b.close()
```

## Why each piece matters
- **`executable_path=EDGE`** — points Playwright at the real Edge. Playwright treats Edge as Chromium, so all Chromium APIs work.
- **`--disable-blink-features=AutomationControlled`** — removes the automation-related Blink feature that headless browsers often expose; makes the session look more like a normal browser.
- **`add_init_script`** — hides the `navigator.webdriver` flag before any page script runs. Many sites check this and block headless automation.
- **Real desktop user-agent** — mimic a normal Chrome 125 on Windows 10/11 x64 instead of the default headless UA (`HeadlessChrome`), which sites can use to detect automation.
- **`locale='en-US'`** — keeps UI text in English, which makes parsing page text (e.g. "Nonstop", "Economy") stable across scrapes.
- **`viewport=1440x900`** — desktop-size viewport; some sites serve mobile layouts or render differently on narrow screens.

## Common patterns
### Reliable navigation
Use `wait_until='domcontentloaded'` with a generous timeout, then sleep to let client-side JS render:
```python
page.goto(url, wait_until='domcontentloaded', timeout=45000)
page.wait_for_timeout(9000)
```
Client-rendered pages (Google Flights, etc.) need the extra wait; `networkidle` can hang on pages with persistent connections, so prefer a fixed wait.

### Clicking visible elements only
Sites often keep hidden duplicates of elements (e.g. menu items in both mobile and desktop layouts). Loop over all matches and pick the first visible one:
```python
for e in page.query_selector_all('text=/^Economy$/'):
    try:
        if e.is_visible():
            e.click(force=True, timeout=8000)
            break
    except Exception:
        pass
```
Use `text=/^...$/` regex selectors for exact text matches and `force=True` to click elements that Playwright considers "not actionable" (e.g. covered or with unusual layout).

### Handling dynamic dropdowns / autocomplete
For inputs with autocomplete (airport search, etc.):
1. Click the input, `page.fill(text)` the value.
2. Wait ~2.5s for suggestions to load.
3. Press `Enter` to accept the top suggestion.
4. Read the input value back afterward to verify, and screenshot to confirm state.

See the `google-flights-scraper` skill for a full worked example of this pattern at scale.

## Gotchas
- **Path variations**: if launch fails with `executable_path`, check both `C:\Program Files (x86)\...` and `C:\Program Files\...\msedge.exe` (and Edge Beta/Dev channels if installed).
- **No `playwright install` needed** — but if you do want Playwright's own Chromium later, `playwright install chromium` works too.
- **Don't reuse the same browser instance across unrelated tasks** — each `with sync_playwright()` block should open and close its own browser.
- **Anti-bot arms race**: the UA + webdriver-hiding + `AutomationControlled` flag is the baseline. If a site still blocks you, add randomized delays between actions and consider headed mode (`headless=False`) for debugging via screenshots.
- **headless=False visible window** — during development, run headed once with `page.screenshot(path='debug.png')` to see what the page actually looks like before relying on text parsing.
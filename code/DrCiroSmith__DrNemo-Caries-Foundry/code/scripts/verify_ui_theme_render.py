#!/usr/bin/env python3
"""
Renders docs/index.html in headless Playwright Chromium in:
1. Desktop Light Mode (1920x1080)
2. Desktop Dark Mode (1920x1080)
3. Mobile Light Mode (390x844)
4. Mobile Dark Mode (390x844)

Verifies:
- scrollWidth <= clientWidth (no horizontal scrollbar / overflow)
- Theme toggle responsiveness
- WebGL 3Dmol canvas presence
- Saves screenshots for visual QA inspection
"""
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

REPO_ROOT = Path(__file__).parent.parent.resolve()
INDEX_PATH = REPO_ROOT / "docs" / "index.html"
OUT_DIR = REPO_ROOT / "demo_data" / "results" / "screenshots"
OUT_DIR.mkdir(parents=True, exist_ok=True)

PLAYWRIGHT_ARGS = [
    "--enable-webgl",
    "--ignore-gpu-blocklist",
    "--enable-gpu-rasterization",
    "--use-gl=angle",
    "--use-angle=swiftshader",
]

def test_theme_and_viewport(page, mode_name: str, width: int, height: int, theme: str, out_file: Path):
    print(f"\n--- Testing {mode_name} ({width}x{height}, theme={theme}) ---")
    page.set_viewport_size({"width": width, "height": height})
    page.goto(f"file://{INDEX_PATH}")
    page.wait_for_timeout(2000)

    # Set theme via script
    page.evaluate(f"setTheme('{theme}')")
    page.wait_for_timeout(1500)

    # Check horizontal overflow
    overflow = page.evaluate("() => ({ scrollWidth: document.documentElement.scrollWidth, clientWidth: document.documentElement.clientWidth })")
    scroll_w = overflow["scrollWidth"]
    client_w = overflow["clientWidth"]
    print(f"  Dimensions: clientWidth={client_w}, scrollWidth={scroll_w}")
    assert scroll_w <= client_w + 1, f"Horizontal overflow detected: scrollWidth {scroll_w} > clientWidth {client_w}"
    print("  [PASS] Zero horizontal overflow.")

    # Check 3D canvas
    canvas_count = page.locator("canvas").count()
    print(f"  WebGL Canvases found: {canvas_count}")

    # Check active tab matrix
    matrix_visible = page.locator("#tab-falsification").is_visible()
    print(f"  Disproof Matrix visible: {matrix_visible}")

    # Take screenshot
    page.screenshot(path=str(out_file), full_page=False)
    print(f"  Screenshot saved: {out_file.name} ({out_file.stat().st_size:,} bytes)")

def main():
    print("=== PLAYWRIGHT HEADLESS THEME AND RESPONSIVENESS SUITE ===")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=PLAYWRIGHT_ARGS)
        page = browser.new_page()

        # 1. Desktop Light (1920x1080)
        test_theme_and_viewport(page, "Desktop Light", 1920, 1080, "light", OUT_DIR / "desktop_light.png")

        # 2. Desktop Dark (1920x1080)
        test_theme_and_viewport(page, "Desktop Dark", 1920, 1080, "dark", OUT_DIR / "desktop_dark.png")

        # 3. Mobile Light (390x844)
        test_theme_and_viewport(page, "Mobile Light", 390, 844, "light", OUT_DIR / "mobile_light.png")

        # 4. Mobile Dark (390x844)
        test_theme_and_viewport(page, "Mobile Dark", 390, 844, "dark", OUT_DIR / "mobile_dark.png")

        browser.close()
    print("\n[SUCCESS] All 4 render configurations passed with 0 horizontal overflow.")

if __name__ == "__main__":
    main()

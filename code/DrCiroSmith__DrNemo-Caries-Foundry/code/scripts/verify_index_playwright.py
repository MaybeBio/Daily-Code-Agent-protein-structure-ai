#!/usr/bin/env python3
import sys
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

html_path = Path(__file__).resolve().parent.parent / "docs" / "index.html"

console_errors = []
console_logs = []

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1280, "height": 900}, device_scale_factor=2)
    
    def handle_console(msg):
        if msg.type == "error":
            console_errors.append(f"{msg.text} @ {msg.location}")
        else:
            console_logs.append(msg.text)
    page.on("console", handle_console)
    page.on("pageerror", lambda err: console_errors.append(f"PAGEERROR: {err}"))
    
    print(f"Loading {html_path}...")
    page.goto(f"file://{html_path}")
    page.wait_for_timeout(3500) # allow 3Dmol to initialize and render
    
    # Check molecular viewport canvas exists
    canvas = page.query_selector("#molecular-viewport canvas")
    print(f"WebGL canvas found: {canvas is not None}")
    
    # Check lead title
    badge = page.inner_text("#active-lead-badge")
    print(f"Active lead badge: {badge}")
    
    overlay = page.inner_text("#viewport-overlay-text")
    print(f"Overlay text: {overlay}")
    
    # Capture test screenshot
    test_shot = Path("/tmp/test_caries_foundry.png")
    page.screenshot(path=str(test_shot))
    print(f"Captured test screenshot: {test_shot} ({test_shot.stat().st_size / 1024.0:.1f} KB)")
    
    browser.close()

print(f"\nConsole Errors Count: {len(console_errors)}")
for err in console_errors:
    print(f"  [ERROR] {err}")

if len(console_errors) == 0:
    print("VERIFICATION PASS: 0 JS Console Errors!")
else:
    sys.exit(1)

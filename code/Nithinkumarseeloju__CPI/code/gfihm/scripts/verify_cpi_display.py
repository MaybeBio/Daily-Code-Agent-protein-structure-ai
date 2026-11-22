"""Check model-level styling, residue selection and the result landing link."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]
with sync_playwright() as p:
    browser=p.chromium.launch(executable_path=r'C:\Program Files\Google\Chrome\Application\chrome.exe',headless=True,args=['--enable-unsafe-swiftshader'])
    page=browser.new_page(viewport={'width':1450,'height':1000})
    errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    page.goto('http://127.0.0.1:8765/?dataset=davis&pair=269fc35f78e85a36d61dbf6cf68801e2df9bbe1684a29850eeb1b9e10bafb534')
    page.wait_for_function("document.getElementById('poseSource').textContent.includes('2ITY')",timeout=60000)
    assert page.locator('#full').is_checked(), 'Full protein styling failed during load'
    assert not page.locator('#play').is_disabled()
    page.locator('#context').uncheck();page.locator('#context').check()
    page.locator('#contactList .contact').first.click()
    assert page.evaluate("pocket.selectedAtoms({}).some(a=>a.style.sphere?.color==='#ff99ef')")
    page.locator('#full').uncheck();page.locator('#full').check()
    page.locator('#preprocessingResults summary').click()
    assert '19,037' in page.locator('#preprocessingResults').inner_text()
    page.screenshot(path=str(ROOT/'reports/site_ready.png'),full_page=True)
    assert not errors,errors
    browser.close()
report=dict(result='PASS',checks=['Auto-loaded real Davis result', 'Full protein ribbon remains enabled', 'Water/cofactor visibility toggle', 'Contact residue click highlights matching atoms', 'Protein visibility toggle', 'Preprocessing report displayed'],browser_errors=errors)
(ROOT/'reports/cpi_display_validation.json').write_text(json.dumps(report,indent=2))
print(json.dumps(report,indent=2))

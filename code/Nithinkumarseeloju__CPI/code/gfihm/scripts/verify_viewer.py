"""Smoke test actual WebGL rendering and controls using installed Chrome."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]
with sync_playwright() as p:
    browser=p.chromium.launch(executable_path=r'C:\Program Files\Google\Chrome\Application\chrome.exe',headless=True,args=['--enable-unsafe-swiftshader'])
    page=browser.new_page(viewport={'width':1500,'height':1100},device_scale_factor=1)
    errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    page.goto('http://127.0.0.1:8765/',wait_until='networkidle')
    page.wait_for_function("document.getElementById('status').textContent.includes('nearby atom pairs')",timeout=60000)
    assert page.locator('#complexTitle').inner_text()=='10GS'
    counts=page.evaluate('({ligand:ligand.selectedAtoms({}).length,pocket:pocket.selectedAtoms({}).length,contacts:contactShapes.length,canvas:document.querySelectorAll("canvas").length})')
    assert counts['ligand']>0 and counts['pocket']>0 and counts['contacts']>0 and counts['canvas']>0
    original=page.evaluate('ligand.selectedAtoms({})[0].x')
    page.locator('#position').evaluate("e=>{e.value='0';e.dispatchEvent(new Event('input'));}")
    moved=page.evaluate('ligand.selectedAtoms({})[0].x')
    assert abs(moved-original)>0.01
    assert page.evaluate('contactShapes.length')==0
    page.locator('#play').click()
    page.wait_for_function("document.getElementById('position').value==='100' && anim===null",timeout=10000)
    assert abs(page.evaluate('ligand.selectedAtoms({})[0].x')-original)<1e-5
    page.locator('#surface').check();page.wait_for_timeout(2000)
    page.locator('#full').check();page.wait_for_function('protein !== null',timeout=30000)
    page.screenshot(path=str(ROOT/'reports/viewer_desktop.png'),full_page=True)
    page.locator('#contacts').uncheck(); assert page.evaluate('contactShapes.length')==0
    page.locator('#pdb').fill('zzzz');page.locator('#load').click()
    assert 'Choose a PDB ID' in page.locator('#status').inner_text()
    page.locator('#pdb').fill('11gs');page.locator('#load').click()
    page.wait_for_function("document.getElementById('complexTitle').textContent==='11GS'",timeout=30000)
    page.wait_for_function("!document.getElementById('load').disabled",timeout=30000)
    page.set_viewport_size({'width':390,'height':844});page.wait_for_timeout(1000)
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
    page.screenshot(path=str(ROOT/'reports/viewer_mobile.png'),full_page=True)
    assert not errors,errors
    report=dict(result='PASS',rendered_atoms=counts,checks=['WebGL canvas and loaded atom models','Pocket contacts visible','Slider moves ligand and hides bound contacts','Animation returns exactly to bound coordinates','Pocket surface','Full protein from source archive','Invalid PDB ID message','Switch complex','Mobile layout without horizontal overflow'],page_errors=errors)
    (ROOT/'reports/viewer_validation.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report,indent=2));browser.close()

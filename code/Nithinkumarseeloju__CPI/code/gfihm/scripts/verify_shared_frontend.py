"""Check the shared Perceiver landing page and its real workbench integration."""
import json
import zipfile
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'reports/shared_frontend'
BASE = 'http://127.0.0.1:8765/'


def main():
    OUT.mkdir(exist_ok=True)
    checks, errors = [], []
    with sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path=r'C:\Program Files\Google\Chrome\Application\chrome.exe',
            headless=True, args=['--enable-unsafe-swiftshader'])
        page = browser.new_page(viewport={'width': 1440, 'height': 1000})
        page.on('pageerror', lambda error: errors.append(str(error)))
        assert page.goto(BASE, wait_until='networkidle').status == 200
        page.locator('.loader').wait_for(state='hidden')
        page.wait_for_timeout(1600)
        assert page.locator('#world canvas').count() == 1
        assert page.locator('#molecule canvas').count() == 1
        assert page.title() == 'Perceiver CPI — Beyond the visible'
        assert page.evaluate('Array.from(document.querySelectorAll("[id]")).map(e=>e.id).filter((v,i,a)=>a.indexOf(v)!==i)') == []
        assert page.locator('#method option').count() == 2
        assert page.locator('#method').input_value() == 'dock'
        page.screenshot(path=str(OUT / 'desktop.png'))
        checks.append('Original hero/type/palette, Three.js and scientific viewer canvases load together; no duplicate IDs')

        page.get_by_role('button', name='Menu', exact=True).click()
        page.get_by_role('navigation').get_by_role('link', name='The research', exact=True).click()
        page.wait_for_url('**/#research')
        page.wait_for_timeout(1000)
        for label, count in [('Integrated scores', 1), ('Kinase binding', 2), ('All datasets', 3)]:
            page.get_by_role('button', name=label, exact=True).click()
            assert page.locator('.card:visible').count() == count
        page.get_by_role('button', name='Explore KIBA', exact=True).click()
        page.get_by_role('dialog').wait_for(state='visible')
        assert page.locator('#dialog-title').inner_text() == 'KIBA'
        page.get_by_role('button', name='Close dataset details', exact=True).click()
        page.get_by_role('dialog').wait_for(state='hidden')
        page.go_forward()
        page.get_by_role('dialog').wait_for(state='visible')
        page.locator('#dialog-explore').click()
        page.wait_for_url('**/#workspace')
        assert page.locator('#dataset').input_value() == 'kiba'
        page.wait_for_function("document.getElementById('pairSelect').options.length>1")
        assert page.locator('#smiles').input_value() == ''
        assert page.locator('#sequence').input_value() == ''
        page.wait_for_timeout(1100)
        page.screenshot(path=str(OUT / 'workspace.png'))
        checks.append('Menu, filters, dialogs/history and dataset-to-workbench handoff work without substituting a pair')

        page.locator('.workflow-links a[href="#bioemuPanel"]').click()
        page.wait_for_url('**/#bioemuPanel')
        assert page.locator('#bioemuPanel').get_attribute('open') is not None
        page.wait_for_timeout(1000)
        assert page.locator('#bioemuExport').is_visible()
        checks.append('BioEmu navigation opens the actual export/import panel')

        for width, height in [(320, 568), (390, 844), (768, 900), (1024, 900), (1440, 1000), (844, 390)]:
            page.set_viewport_size({'width': width, 'height': height})
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), (width, height)
            page.get_by_role('button', name='Menu', exact=True).click()
            page.wait_for_timeout(600)
            link = page.get_by_role('navigation').get_by_role('link', name='Your exploration', exact=False)
            link.scroll_into_view_if_needed()
            link.click()
            page.wait_for_url('**/#workspace')
            page.wait_for_timeout(1000)
        checks.append('Six desktop/mobile/landscape viewports fit; short-screen menu remains scrollable')

        page.set_viewport_size({'width': 390, 'height': 844})
        page.goto(BASE, wait_until='networkidle')
        page.locator('.loader').wait_for(state='hidden')
        page.wait_for_timeout(1600)
        page.screenshot(path=str(OUT / 'mobile.png'))
        # Test a saved real pair link and its coordinate provenance.
        pair = '269fc35f78e85a36d61dbf6cf68801e2df9bbe1684a29850eeb1b9e10bafb534'
        page.goto(BASE + '?dataset=davis&pair=' + pair + '&method=experimental#workspace', wait_until='networkidle')
        page.locator('.loader').wait_for(state='hidden')
        page.wait_for_function("document.getElementById('poseSource').textContent.includes('2ITY')", timeout=90000)
        page.wait_for_function("!document.getElementById('downloadReport').disabled", timeout=90000)
        with page.expect_download() as download_info:
            page.locator('#downloadReport').click()
        with zipfile.ZipFile(download_info.value.path()) as report_zip:
            assert {'report.html', 'results.json', 'structure/protein.pdb',
                    'structure/ligand.sdf', 'structure/pocket.pdb',
                    'structure/scene.pml'} <= set(report_zip.namelist())
            result = json.loads(report_zip.read('results.json'))
            assert result['score'].get('score') is not None
            assert result['structure'].get('pose_available')
        assert page.evaluate("ligand.selectedAtoms({}).length>0")
        assert page.locator('#dataset').input_value() == 'davis'
        page.locator('#structures').scroll_into_view_if_needed()
        page.wait_for_timeout(1200)
        page.screenshot(path=str(OUT / 'mobile-structure.png'))
        checks.append('Saved Davis pair shows score and 2ITY structure; combined report contains score and pose files')

        page.emulate_media(reduced_motion='reduce')
        page.goto(BASE, wait_until='networkidle')
        page.locator('.loader').wait_for(state='hidden')
        page.get_by_role('button', name='Menu', exact=True).click()
        page.keyboard.press('Escape')
        assert page.locator('#menu').is_hidden()
        assert page.evaluate('!document.querySelector("main").inert')
        checks.append('Reduced-motion loader/menu and keyboard Escape restore the workbench')
        assert not errors, errors
        browser.close()

    report = dict(status='PASS', checks=checks, page_errors=errors,
                  companion_reports=['reports/cpi_browser_validation.json', 'reports/bioemu2_validation.json'],
                  limitations=['Physical mobile devices, Safari and Firefox were not tested.',
                               'Hero motion was visually inspected; no frame-rate guarantee.',
                               'BioEmu GPU inference is not configured; its import tests use temporary synthetic fixtures.'])
    (OUT / 'verification.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()

"""Regression checks for structure browsing, live counts and model cache reload."""
import json,time,tempfile,hashlib
from pathlib import Path
from playwright.sync_api import sync_playwright
from cpi_data import ROOT,connect

checks=[]
with sync_playwright() as p:
    browser=p.chromium.launch(executable_path=r'C:\Program Files\Google\Chrome\Application\chrome.exe',headless=True,args=['--enable-unsafe-swiftshader'])
    page=browser.new_page(viewport={'width':1450,'height':1000})
    errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    page.goto('http://127.0.0.1:8765/',wait_until='networkidle')
    page.wait_for_function("document.querySelectorAll('#coverageTable tbody tr').length===3")
    assert page.locator('#pdbInventory option').count()==19035
    live=page.request.get('http://127.0.0.1:8765/api/results').json()
    for row,(dataset,d) in zip(page.locator('#coverageTable tbody tr').all(),live['datasets'].items()):
        cells=row.locator('td').all_text_contents()
        assert int(cells[1].replace(',',''))==d['source_rows'],cells
        assert int(cells[4].replace(',',''))==d['pose_ready_pairs'],cells
    checks.append('Current database counts displayed for all three datasets; all 19035 processed PDB IDs browsable')
    page.locator('#pdbExplorer summary').click()
    page.fill('#browsePdb','2ITY');page.click('#browseStructure')
    page.wait_for_function("document.getElementById('poseSource').textContent.includes('complex 2ITY')")
    page.wait_for_function("!document.getElementById('play').disabled")
    assert 'no dataset model score requested' in page.locator('#scoreResult').inner_text()
    assert page.locator('#smiles').input_value()==''
    assert page.locator('#export').get_attribute('href')=='/api/export/2ity'
    page.locator('#contactList .contact').first.click()
    assert page.evaluate("pocket.selectedAtoms({}).some(a=>a.style.sphere?.color==='#ff99ef')")
    page.click('#play');page.wait_for_timeout(400)
    assert page.evaluate('currentPose>0&&currentPose<100')
    page.click('#play')
    checks.append('Independent PDB browser loads the correct complex, contacts, checked motion and export without a CSV score')
    page.fill('#browsePdb','3vjs');page.click('#browseStructure')
    assert 'unavailable' in page.locator('#queryStatus').inner_text()
    assert page.evaluate('ligand===null')
    assert page.request.get('http://127.0.0.1:8765/api/pdbbind/3vjs/motion').status==404
    checks.append('Excluded structures show a simple error and clear the previous pose')
    page.fill('#browsePdb','10gs');page.click('#browseStructure')
    page.wait_for_function("document.getElementById('poseSource').textContent.includes('complex 10GS')")
    page.fill('#smiles','CCO')
    page.wait_for_timeout(900)
    assert page.evaluate('ligand===null')
    checks.append('Editing inputs cancels a PDB viewer result and ignores late motion responses')
    page.set_viewport_size({'width':390,'height':844})
    page.locator('#preprocessingResults summary').click()
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
    assert not errors,errors
    browser.close()

# In-memory cache corruption must force a real strict reload of the provided
# checkpoint. No checkpoint file or source measurement is modified.
import cpi_inference
with connect() as c:
    pair=dict(c.execute("SELECT p.* FROM pairs p JOIN measurements m ON m.pair_id=p.id WHERE m.dataset='davis' LIMIT 1").fetchone())
cpi_inference.CACHE['davis']=(None,None,None,'obsolete-checkpoint-digest')
score=cpi_inference.predict('davis',pair['smiles'],pair['sequence'])
checkpoint=ROOT/score['checkpoint']
assert score['checkpoint_sha256']==hashlib.sha256(checkpoint.read_bytes()).hexdigest()
checks.append('Obsolete in-memory checkpoint digest forces strict reload and real inference')

# Test unsupported docking in an isolated database, with no source receptor.
import cpi_data,cpi_app
old_db=cpi_data.DB;original_resolve=cpi_app.resolve_pair
with tempfile.TemporaryDirectory(prefix='completion-test-',dir=ROOT/'reports') as directory:
    directory=Path(directory);assert directory.resolve().is_relative_to((ROOT/'reports').resolve())
    try:
        cpi_data.DB=directory/'isolated.sqlite';cpi_data.init().close()
        cpi_app.resolve_pair=lambda _:None
        key,smiles,sequence,ligand_key=cpi_data.normalize('CCO','ACDEFGHIKLMNPQRSTVWY')
        with cpi_data.connect() as c:c.execute('INSERT INTO pairs VALUES (?,?,?,?)',(key,smiles,sequence,ligand_key));c.commit()
        job_id=cpi_app.submit(key,'dock')
        for _ in range(100):
            job=cpi_app.job_status(job_id)
            if job['status'] not in ('queued','running'):break
            time.sleep(.1)
        assert job['status']=='unsupported' and job['error'] is None,job
        assert 'protein structure' in job['result']['message']
        checks.append('Missing receptor returns actionable unsupported status rather than a generic failure')
    finally:
        cpi_app.pool.shutdown(wait=True);cpi_data.DB=old_db;cpi_app.resolve_pair=original_resolve
report=dict(result='PASS',checks=checks,browser_errors=errors)
(ROOT/'reports/completion_validation.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps(report,indent=2))

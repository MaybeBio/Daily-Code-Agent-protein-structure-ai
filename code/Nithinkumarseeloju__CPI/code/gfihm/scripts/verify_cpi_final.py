"""Final integration checks: real docking display, export, errors and recovery."""
import json,io,zipfile,time,tempfile,sqlite3
from pathlib import Path
from playwright.sync_api import sync_playwright
from cpi_data import ROOT,connect
results=[]
pair='269fc35f78e85a36d61dbf6cf68801e2df9bbe1684a29850eeb1b9e10bafb534'
with connect() as c:
 source_pair=dict(c.execute('SELECT * FROM pairs WHERE id=?',(pair,)).fetchone())
 source_match=dict(c.execute('SELECT * FROM matches WHERE pair_id=? LIMIT 1',(pair,)).fetchone())
with sync_playwright() as p:
 browser=p.chromium.launch(executable_path=r'C:\Program Files\Google\Chrome\Application\chrome.exe',headless=True,args=['--enable-unsafe-swiftshader'])
 page=browser.new_page(viewport={'width':1450,'height':1000});errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
 page.goto('http://127.0.0.1:8765/?dataset=davis&pair='+pair,wait_until='networkidle')
 page.wait_for_function("document.getElementById('poseSource').textContent.includes('2ITY')",timeout=60000)
 page.select_option('#method','redock');page.click('#predict')
 page.wait_for_function("document.getElementById('poseSource').textContent.includes('AutoDock Vina')",timeout=120000)
 assert page.locator('#sceneTitle').inner_text()=='Predicted docking pose'
 assert page.evaluate('metadata.pose_source')=='AutoDock Vina predicted pose'
 href=page.locator('#export').get_attribute('href');raw=page.request.get('http://127.0.0.1:8765'+href).body()
 jid=href.rsplit('/',1)[-1]
 with zipfile.ZipFile(io.BytesIO(raw)) as z:assert z.read('ligand.sdf')==(ROOT/'processed/predicted'/jid/'ligand.sdf').read_bytes()
 page.screenshot(path=str(ROOT/'reports/cpi_docked.png'),full_page=True)
 results.append('Real Vina result displayed as predicted, with the correct ligand and matching PyMOL export')
 page.fill('#smiles','C(');page.click('#predict');page.wait_for_function("document.getElementById('scoreResult').textContent.includes('valid SMILES')")
 assert page.evaluate('ligand===null');assert not page.locator('#jobError').is_visible()
 results.append('Invalid input clears predicted pose and produces a readable error')
 assert not errors,errors;browser.close()

# Failure/recovery checks use an isolated SQLite database and do not change
# the running site's jobs or checkpoints.
import cpi_data,cpi_app,cpi_inference
with tempfile.TemporaryDirectory(prefix='cpi-test-',dir=ROOT/'reports') as tmp:
 tmp=Path(tmp);assert tmp.resolve().is_relative_to((ROOT/'reports').resolve())
 old_db=cpi_data.DB;cpi_data.DB=tmp/'test.sqlite'
 c=cpi_app.init()
 c.execute('INSERT INTO pairs VALUES (?,?,?,?)',tuple(source_pair.values()))
 c.execute('INSERT INTO matches VALUES (?,?,?,?,?,?,?,?,?)',tuple(source_match.values()));c.commit();c.close()
 old_root=cpi_inference.ROOT;cpi_inference.ROOT=tmp;cpi_inference.CACHE.clear()
 try:cpi_inference.predict('davis',source_pair['smiles'],source_pair['sequence']);raise AssertionError('Missing checkpoint should fail')
 except FileNotFoundError:results.append('Missing checkpoint produces an explicit file error without changing supplied weights')
 finally:cpi_inference.ROOT=old_root
 jid=cpi_app.submit(pair);assert cpi_app.submit(pair)==jid
 for _ in range(120):
  state=cpi_app.job_status(jid)
  if state['status'] not in ('queued','running'):break
  time.sleep(.2)
 assert state['status']=='completed',state
 with cpi_app.connect() as c:c.execute("UPDATE jobs SET status='queued' WHERE id=?",(jid,));c.commit()
 cpi_app.recover()
 for _ in range(120):
  state=cpi_app.job_status(jid)
  if state['status']=='completed':break
  time.sleep(.2)
 assert state['status']=='completed'
 results.append('Duplicate submissions share a job; startup recovery completes an interrupted queued job')
 # Exercise a preparation failure without replacing a real user's job.
 import cpi_docking
 original_dock=cpi_docking.dock
 def fail_preparation(*args,**kwargs):raise ValueError('Test receptor preparation failure')
 cpi_docking.dock=fail_preparation
 failed_id=cpi_app.submit(pair,'redock')
 for _ in range(120):
  failure=cpi_app.job_status(failed_id)
  if failure['status'] not in ('queued','running'):break
  time.sleep(.2)
 assert failure['status']=='failed' and 'Test receptor preparation failure' in failure['error']
 assert cpi_app.job_status(jid)['status']=='completed'
 cpi_docking.dock=original_dock
 results.append('Injected docking preparation failure is saved with its error; existing experimental result remains usable')
 cpi_app.pool.shutdown(wait=True);cpi_data.DB=old_db
report=dict(result='PASS',checks=results,browser_errors=errors,pymol_rendering='Not tested; matching coordinate files and export script checked.')
(ROOT/'reports/cpi_final_validation.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))

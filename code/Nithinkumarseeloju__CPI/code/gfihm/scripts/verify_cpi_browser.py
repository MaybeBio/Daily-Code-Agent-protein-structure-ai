"""Exercise actual dataset pairs, live score routing and relative ligand motion."""
import io,json,time,zipfile,urllib.request,sqlite3
from pathlib import Path
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[1];BASE='http://127.0.0.1:8765'
c=sqlite3.connect(ROOT/'processed/cpi.sqlite');c.row_factory=sqlite3.Row
examples={}
for ds in ('davis','kiba','metz'):
 for r in c.execute('SELECT j.* FROM jobs j WHERE pair_id IN (SELECT pair_id FROM measurements WHERE dataset=?)',(ds,)):
  data=json.loads(r['result'] or '{}')
  if data.get('motion',{}).get('version')==2 and data.get('animation_available'):
   examples[ds]=dict(pair_id=r['pair_id'],pdb_id=data['pdb_id']);break
assert len(examples)==3
result=dict(examples=examples,checks=[],page_errors=[])
with sync_playwright() as p:
 browser=p.chromium.launch(executable_path=r'C:\Program Files\Google\Chrome\Application\chrome.exe',headless=True,args=['--enable-unsafe-swiftshader'])
 page=browser.new_page(viewport={'width':1600,'height':1250});page.on('pageerror',lambda e:result['page_errors'].append(str(e)))
 page.goto(BASE,wait_until='networkidle');page.select_option('#method','experimental');page.wait_for_function("document.getElementById('pairSelect').options.length>1")
 for ds,example in examples.items():
  page.select_option('#dataset',ds)
  page.wait_for_selector(f'#pairSelect option[value="{example["pair_id"]}"]',state='attached')
  page.select_option('#pairSelect',example['pair_id']);page.wait_for_function("document.getElementById('sequence').value.length>40")
  with page.expect_response(lambda r:'/api/predict' in r.url and r.request.method=='POST',timeout=60000) as response:
   page.click('#predict')
  score=response.value.json();assert response.value.status==200,score
  assert score['dataset']==ds and score['pair_id']==example['pair_id'] and f'runs\\{ds}\\' in score['checkpoint']
  page.wait_for_function("document.getElementById('poseSource').textContent.includes('Verified experimental')",timeout=60000)
  page.wait_for_function("!document.getElementById('play').disabled",timeout=30000)
  assert page.evaluate('metadata.pdb_id')==example['pdb_id']
  assert page.evaluate('ligand.selectedAtoms({}).length')>0
  result['examples'][ds]['fresh_score']=score['score'];result['examples'][ds]['truncated']=score['truncated']
  page.click('#play');page.wait_for_timeout(100)
  before=page.evaluate('({view:viewer.getView(),lig:ligand.selectedAtoms({}).map(a=>[a.x,a.y,a.z]),prot:pocket.selectedAtoms({}).map(a=>[a.x,a.y,a.z])})')
  page.wait_for_function('previous => currentPose > previous',arg=page.evaluate('currentPose'),timeout=10000)
  after=page.evaluate('({view:viewer.getView(),lig:ligand.selectedAtoms({}).map(a=>[a.x,a.y,a.z]),prot:pocket.selectedAtoms({}).map(a=>[a.x,a.y,a.z])})')
  assert before['view']==after['view'],'Camera moved during playback'
  assert before['prot']==after['prot'],'Protein moved during playback'
  assert before['lig']!=after['lig'],'Ligand did not move'
  page.click('#play');paused=page.evaluate('currentPose');page.wait_for_timeout(200);assert page.evaluate('currentPose')==paused
  for value in (0,35,100):page.locator('#position').evaluate(f"e=>{{e.value='{value}';e.dispatchEvent(new Event('input'));}}")
  error=page.evaluate('Math.max(...ligand.selectedAtoms({}).flatMap((a,i)=>[Math.abs(a.x-original[i][0]),Math.abs(a.y-original[i][1]),Math.abs(a.z-original[i][2])]))')
  assert error<1e-4;result['examples'][ds]['final_coordinate_max_error']=error
  assert page.evaluate('contactShapes.length')>0
  page.locator('#position').evaluate("e=>{e.value='0';e.dispatchEvent(new Event('input'));}");assert page.evaluate('contactShapes.length')==0
  page.click('#reset');page.screenshot(path=str(ROOT/f'reports/cpi_{ds}.png'),full_page=True)
  raw=urllib.request.urlopen(BASE+f'/api/export/{example["pdb_id"]}').read()
  with zipfile.ZipFile(io.BytesIO(raw)) as archive:
   folder=ROOT/f'processed/pdbbind/complexes/{example["pdb_id"]}'
   assert archive.read('ligand.sdf')==(folder/'ligand.sdf').read_bytes()
   assert archive.read('pocket.pdb')==(folder/'pocket.pdb').read_bytes()
 result['checks']+=['All three datasets use their own checkpoint and preserve pair identity','Fresh score displayed separately from measured values','Exact matched complex displayed for each dataset','Ligand moves relative to fixed protein and fixed camera','Pause and scrub work','Final coordinates match stored ligand within 1e-4 A','Contact lines hidden during approach','PyMOL export coordinate identity']
 # Delay responses in the browser, then change datasets while requests are active.
 page.evaluate("window.realFetch=window.fetch;window.fetch=async(...a)=>{const r=await realFetch(...a);if(String(a[0]).includes('/api/predict')||String(a[0]).includes('/api/jobs'))await new Promise(x=>setTimeout(x,1200));return r;}")
 page.click('#predict');page.select_option('#dataset','davis');page.wait_for_timeout(2500)
 assert page.locator('#scoreResult').inner_text()=='Ready for the new query.'
 assert page.evaluate('ligand===null');page.evaluate('window.fetch=window.realFetch')
 result['checks'].append('Late responses cannot replace a newly selected dataset')
 page.fill('#smiles','C(');page.fill('#sequence','ACDEFGHIK');page.click('#predict');page.wait_for_function("document.getElementById('scoreResult').textContent.includes('valid SMILES')")
 assert page.evaluate('ligand===null')
 page.fill('#smiles','CCO');page.fill('#sequence','AC?EF');page.click('#predict');page.wait_for_function("document.getElementById('scoreResult').textContent.includes('? at 3')")
 result['checks'].append('Invalid SMILES and protein letters produce simple errors and no stale pose')
 page.fill('#smiles','CCO');page.fill('#sequence','>test\nACDEFGHIKLMNPQRSTVWY\nACDEFGHIKLMNPQRSTVWY');page.click('#predict')
 page.wait_for_function("document.getElementById('queryStatus').textContent.includes('No verified experimental')",timeout=120000)
 assert page.evaluate('ligand===null');result['checks'].append('FASTA input works; unavailable structure does not show unrelated coordinates')
 page.set_viewport_size({'width':390,'height':844});page.wait_for_timeout(300)
 assert page.evaluate('document.documentElement.scrollWidth<=innerWidth');result['checks'].append('Mobile layout fits viewport')
 assert not result['page_errors'],result['page_errors'];browser.close()
result['result']='PASS';(ROOT/'reports/cpi_browser_validation.json').write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2))

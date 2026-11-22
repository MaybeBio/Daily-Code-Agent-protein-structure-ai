"""Local CPI application; durable pair jobs independent of affinity inference."""
import sys,json,zipfile,io,hashlib,threading,traceback,time,html as html_lib
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import numpy as np
from scipy.spatial import cKDTree
from fastapi import FastAPI,HTTPException
from fastapi.responses import FileResponse,Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel,Field
from typing import Literal
from cpi_data import ROOT,connect,init,normalize,resolve_pair,find_receptor,find_receptor_homolog
from cpi_inference import predict,checkpoint_path
from cpi_job_errors import classify_failure,failure_detail
from preprocess import parse_protein

app=FastAPI(title='CPI student workbench');pool=ThreadPoolExecutor(max_workers=2);guard=threading.Lock()
from cpi_bioemu2 import router as bioemu2_router
app.include_router(bioemu2_router)
pdb_motion_tasks={}
class Query(BaseModel):
 dataset:str
 smiles:str=Field(max_length=10000)
 sequence:str=Field(max_length=20000)
 method:Literal['experimental','dock','homolog','redock']='dock'
class ReportRequest(Query):
 job_id:str
def clean(q):
 if q.dataset not in ('davis','kiba','metz'):raise HTTPException(400,'Choose Davis, KIBA or Metz.')
 try:return normalize(q.smiles,q.sequence)
 except ValueError as e:raise HTTPException(400,str(e))
@app.get('/api/datasets')
def datasets():
 with connect() as c:return [dict(dataset=ds,rows=c.execute('SELECT count(*) FROM measurements WHERE dataset=?',(ds,)).fetchone()[0]) for ds in ('davis','kiba','metz')]
@app.get('/api/pairs')
def pairs(dataset:str,q:str='',matched:bool=False,offset:int=0):
 if dataset not in ('davis','kiba','metz'):raise HTTPException(400,'Unknown dataset')
 with connect() as c:
  sql='''SELECT DISTINCT p.id,p.smiles,substr(p.sequence,1,35) AS sequence_preview,EXISTS(SELECT 1 FROM matches x WHERE x.pair_id=p.id) AS pose_available FROM pairs p JOIN measurements m ON m.pair_id=p.id WHERE m.dataset=? AND (p.id LIKE ? OR p.smiles LIKE ?)'''
  if matched:sql+=' AND EXISTS(SELECT 1 FROM matches x WHERE x.pair_id=p.id)'
  return [dict(r) for r in c.execute(sql+' ORDER BY pose_available DESC,p.id LIMIT 50 OFFSET ?',(dataset,'%'+q+'%','%'+q+'%',max(0,offset)))]
@app.get('/api/pairs/{pair}')
def details(pair:str,dataset:str):
 with connect() as c:
  p=c.execute('SELECT * FROM pairs WHERE id=?',(pair,)).fetchone()
  if not p:raise HTTPException(404,'Pair not found.')
  return dict(p)|dict(measurements=[dict(r) for r in c.execute('SELECT row_id,original_score FROM measurements WHERE pair_id=? AND dataset=?',(pair,dataset))],matches=[dict(r) for r in c.execute('SELECT * FROM matches WHERE pair_id=?',(pair,))])
@app.post('/api/predict')
def prediction(q:Query):
 k,sm,seq,lk=clean(q)
 try:
  sha=hashlib.sha256(checkpoint_path(q.dataset).read_bytes()).hexdigest()
  with connect() as c:
   cache_key=sha+':singleton-v2'
   old=c.execute('SELECT result FROM scores WHERE dataset=? AND pair_id=? AND checkpoint=?',(q.dataset,k,cache_key)).fetchone()
   result=json.loads(old[0]) if old else predict(q.dataset,sm,seq)
   result.update(pair_id=k,input_smiles=sm,input_sequence=seq,source_measurements=[dict(r) for r in c.execute('SELECT row_id,original_score FROM measurements WHERE pair_id=? AND dataset=?',(k,q.dataset))])
   check_file=ROOT/'reports/checkpoint_verification.json'
   reference=json.loads(check_file.read_text()).get(q.dataset,{}) if check_file.exists() else {}
   if reference.get('checkpoint_sha256')==result['checkpoint_sha256']:
    result['reference_verification']=reference
   else:
    result.pop('reference_verification',None)
    result['reference_verification_status']='Selected training checkpoint has not been compared with the original saved predictions.'
   # Use the digest of the bytes actually loaded, even if the file was
   # replaced between the initial cache lookup and model inference.
   cache_key=result['checkpoint_sha256']+':singleton-v2'
   c.execute('INSERT OR REPLACE INTO scores VALUES (?,?,?,?)',(q.dataset,k,cache_key,json.dumps(result)));c.commit()
  return result
 except Exception as e:
  (ROOT/'reports/model_errors.log').open('a').write(f'{q.dataset} {k}\n{traceback.format_exc()}\n')
  raise HTTPException(503,f'The score model could not run: {e}. The 3D viewer can still work.')
from cpi_motion import approach
class UnsupportedStructure(ValueError):pass
def execute_job(jid,k):
 with connect() as c:c.execute("UPDATE jobs SET status='running' WHERE id=?",(jid,));c.commit()
 try:
  # Manual queries are matched as well as pre-indexed dataset pairs.
  # Protect creation of the reusable ligand index from concurrent requests.
  with connect() as c: mode=c.execute("SELECT method FROM job_methods WHERE job_id=?",(jid,)).fetchone()
  if not mode or mode[0]!="dock":
   with guard:resolve_pair(k)
  with connect() as c:
   m=c.execute('SELECT * FROM matches WHERE pair_id=? ORDER BY query_coverage DESC,pdb_id LIMIT 1',(k,)).fetchone()
   method=c.execute('SELECT method FROM job_methods WHERE job_id=?',(jid,)).fetchone();method=method[0] if method else 'experimental'
   pair=dict(c.execute('SELECT * FROM pairs WHERE id=?',(k,)).fetchone())
   receptor=c.execute('SELECT x.* FROM matches x JOIN pairs p ON x.pair_id=p.id WHERE p.sequence=? ORDER BY x.query_coverage DESC,x.pdb_id LIMIT 1',(pair['sequence'],)).fetchone()
  folder=None
  if method=='dock':
   from cpi_sequence_docking import predict_and_dock
   from cpi_motion import plan,heavy_coordinates
   folder=ROOT/'processed/predicted'/jid
   from os import environ
   docking=predict_and_dock(pair['smiles'],pair['sequence'],folder,force_rebuild=environ.get('CPI_FORCE_REBUILD')=='1')
   from rdkit import Chem
   ligand=Chem.SDMolSupplier(str(folder/'ligand.sdf'),removeHs=True)[0]
   if ligand is None or ligand.GetNumConformers()==0:raise ValueError('The selected docked ligand pose could not be read.')
   motion=plan(np.asarray(ligand.GetConformer().GetPositions()),heavy_coordinates((folder/'protein.pdb').read_text()))
   selected=docking['selected_pocket_rank'];probability=docking['selected_pocket_probability']
   route=f"{docking['protein_source']}, {docking['pocket_source']}, AutoDock Vina pose"
   result=dict(pair_id=k,pose_available=True,animation_available=motion['available'],route=route,match=None,pdb_id=docking.get('experimental_site',{}).get('pdb_id','sequence'),motion=motion,artifact_base=f'/api/pose/{jid}',docking=docking,sequence_docking=not bool(docking.get("experimental_site")));state='completed'
  elif method=='redock' or (not m and method in ('homolog',)):
   if not receptor:
    receptor=find_receptor(pair['sequence'])
    if not receptor and method=='homolog':receptor=find_receptor_homolog(pair['sequence'])
   if not receptor:
    if method=='homolog':raise UnsupportedStructure('No exact receptor or high-identity experimental homolog with a sequence-matched pocket was found in the local structure index. The score is still available; provide a validated matching receptor structure to enable docking.')
    raise UnsupportedStructure('No exact receptor or high-identity experimental homolog with a sequence-matched pocket was found in the local structure index. Choose sequence-based Docking to predict a structure and rank pockets locally.')
   from cpi_docking import dock
   from cpi_motion import plan,heavy_coordinates
   folder=ROOT/'processed/predicted'/jid;docking=dock(pair['smiles'],receptor['pdb_id'],folder)
   template_based=receptor.get('identity',1.)<1.
   provenance=dict(template_based=template_based,template_pdb=receptor['pdb_id'],template_chain=receptor['chain'],
                   sequence_identity=receptor['identity'],query_coverage=receptor['query_coverage'],
                   chain_coverage=receptor['chain_coverage'],pocket_identity=receptor.get('pocket_identity',1.),
                   pocket_residues=receptor.get('pocket_residues'))
   if template_based:
    docking['receptor_provenance']=provenance
    (folder/'docking.json').write_text(json.dumps(docking,indent=2))
    metadata_path=folder/'metadata.json';pose_metadata=json.loads(metadata_path.read_text())
    pose_metadata['receptor_provenance']=provenance
    pose_metadata['pose_source']='AutoDock Vina predicted pose using a sequence-screened homolog template'
    metadata_path.write_text(json.dumps(pose_metadata,indent=2))
   from rdkit import Chem
   ligand=Chem.SDMolSupplier(str(folder/'ligand.sdf'),removeHs=True)[0]
   motion=plan(np.asarray(ligand.GetConformer().GetPositions()),heavy_coordinates((folder/'protein.pdb').read_text()))
   route='Homology-template docking (predicted pose; not an exact-target structure)' if template_based else 'Predicted pose: AutoDock Vina in a matched known pocket'
   result=dict(pair_id=k,pose_available=True,animation_available=motion['available'],route=route,match=dict(receptor),receptor_provenance=provenance,pdb_id=receptor['pdb_id'],motion=motion,artifact_base=f'/api/pose/{jid}',docking=docking);state='completed'
  elif not m:
   result=dict(pair_id=k,pose_available=False,animation_available=False,route='unsupported',message='No verified experimental match was found. Choose sequence-based Docking to predict a structure and rank pockets locally.')
   state='unsupported'
  else:
   m=dict(m);motion=approach(m['pdb_id']);result=dict(pair_id=k,pose_available=True,animation_available=motion['available'],route='Verified experimental chain/domain',match=m,pdb_id=m['pdb_id'],motion=motion);state='completed';folder=ROOT/'processed/pdbbind/complexes'/m['pdb_id']
  if folder:
   try:
    from cpi_contacts import analyze
    contact_start=time.monotonic();analysis=analyze(folder);result['contact_seconds']=time.monotonic()-contact_start;result['interaction_method']=analysis['method'];result['contacts']=analysis['contacts']
   except Exception as contact_error:
    if method=='dock':raise RuntimeError(f'PLIP contact analysis failed: {contact_error}') from contact_error
    (folder/'interaction_error.txt').write_text(traceback.format_exc());result['interaction_warning']='Assigned contact types unavailable; geometric contacts are still shown.'
  with connect() as c:c.execute('UPDATE jobs SET status=?,result=?,error=NULL WHERE id=?',(state,json.dumps(result),jid));c.commit()
 except UnsupportedStructure as e:
  result=dict(pair_id=k,pose_available=False,animation_available=False,route='unsupported',message=str(e))
  with connect() as c:c.execute("UPDATE jobs SET status='unsupported',result=?,error=NULL WHERE id=?",(json.dumps(result),jid));c.commit()
 except Exception:
  error=traceback.format_exc()
  stage=classify_failure(error)
  reason=error.strip().splitlines()[-1]
  result=dict(pose_available=False,animation_available=False,stage=stage,detail=failure_detail(stage)+' '+reason)
  with connect() as c:
   c.execute("UPDATE jobs SET status='failed',error=?,result=? WHERE id=?",(error,json.dumps(result),jid))
   c.commit()
def job_id_for(k,method):
 version='sequence-fold-pocket-v2' if method=='dock' else 'exact-domain-motion-v2'
 return hashlib.sha256((k+version+('' if method=='experimental' else ':'+method)).encode()).hexdigest()
def submit(k,method='experimental'):
 jid=job_id_for(k,method)
 with guard,connect() as c:
  r=c.execute('SELECT * FROM jobs WHERE id=?',(jid,)).fetchone()
  if not r:
   c.execute('INSERT INTO jobs VALUES (?,?,?,?,?)',(jid,k,'queued',None,None));c.execute('INSERT OR REPLACE INTO job_methods VALUES (?,?)',(jid,method));c.commit();pool.submit(execute_job,jid,k)
 return jid
@app.post('/api/jobs')
def job(q:Query):
 k,s,seq,lk=clean(q)
 with connect() as c:c.execute('INSERT OR IGNORE INTO pairs VALUES (?,?,?,?)',(k,s,seq,lk));c.commit()
 return dict(id=submit(k,q.method),pair_id=k)
@app.get('/api/jobs/{jid}')
def job_status(jid:str):
 with connect() as c:r=c.execute('SELECT * FROM jobs WHERE id=?',(jid,)).fetchone()
 if not r:raise HTTPException(404,'Job not found.')
 d=dict(r);d['result']=json.loads(d['result']) if d['result'] else None
 if d['status']=='failed':
  d['stage']=(d['result'] or {}).get('stage') or classify_failure(d['error'])
  d['detail']=(d['result'] or {}).get('detail') or failure_detail(d['stage'])
 return d
@app.post('/api/report')
def combined_report(q:ReportRequest):
 k,sm,seq,lk=clean(q)
 expected=job_id_for(k,q.method)
 if q.job_id!=expected:raise HTTPException(400,'The selected 3D result does not match these inputs and route.')
 job=job_status(q.job_id)
 if job['status'] not in ('completed','unsupported','failed'):raise HTTPException(409,'Wait for the 3D result to finish before downloading the report.')
 score=prediction(q)
 result=job['result'] or {'pose_available':False,'route':'failed','message':'The 3D job failed. See the saved technical error for details.'}
 report=dict(dataset=q.dataset,smiles=sm,sequence=seq,score=score,structure=result,structure_status=job['status'])
 safe=lambda value:html_lib.escape(str(value or '—'))
 pose_note='A 3D pose is included in the structure/ folder.' if result.get('pose_available') else 'No 3D pose was available for this input and route.'
 docking=result.get('docking') or {}
 pocket_rows=''.join(
  f"<tr><td>{safe(pocket.get('overall_rank'))}</td><td>{safe(pocket.get('rank'))}</td><td>{safe(pocket.get('p2rank_probability'))}</td><td>{safe(pocket.get('vina_score_kcal_mol',pocket.get('status')))}</td></tr>"
  for pocket in docking.get('pocket_candidates',[])
 )
 pocket_table=f'<table><thead><tr><th>Docking rank</th><th>P2Rank rank</th><th>Pocket probability</th><th>Vina score (kcal/mol)</th></tr></thead><tbody>{pocket_rows}</tbody></table>' if pocket_rows else ''
 document=f'''<!doctype html><html lang="en"><meta charset="utf-8"><title>Perceiver CPI result report</title>
<style>body{{font:16px/1.6 Arial,sans-serif;max-width:900px;margin:40px auto;padding:0 20px;color:#20242a}}h1,h2{{font-weight:500}}.card{{padding:16px;border:1px solid #ccd2d8;margin:18px 0}}.muted{{color:#59636e;overflow-wrap:anywhere}}pre{{white-space:pre-wrap;overflow-wrap:anywhere}}table{{border-collapse:collapse}}td,th{{border:1px solid #ccd2d8;padding:6px 12px}}</style>
<h1>Perceiver CPI · Combined result report</h1><p class="muted">Generated {safe(time.strftime('%Y-%m-%d %H:%M:%S UTC',time.gmtime()))}</p>
<section class="card"><h2>Affinity prediction</h2><p><strong>{safe(score.get('score_label'))}:</strong> {safe(score.get('score'))}</p><p>Dataset: {safe(q.dataset.upper())}</p><p class="muted">Score is model output on the dataset's native scale; it is not evidence of experimental binding.</p></section>
<section class="card"><h2>3D structure result</h2><p>{safe(result.get('route'))}</p><p>{safe(result.get('message') or result.get('pdb_id',''))}</p><p>{safe(pose_note)}</p><p>{safe(docking.get('confidence'))}</p>{pocket_table}</section>
<section class="card"><h2>Inputs</h2><p><strong>Compound SMILES</strong></p><pre>{safe(sm)}</pre><p><strong>Protein sequence</strong></p><pre>{safe(seq)}</pre></section>
<p class="muted">The ZIP also contains results.json. When a pose is available, structure/ contains the protein, ligand, pocket and a PyMOL scene script.</p></html>'''
 output=io.BytesIO()
 with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as archive:
  archive.writestr('report.html',document)
  archive.writestr('results.json',json.dumps(report,indent=2))
  if result.get('pose_available'):
   folder=ROOT/'processed/predicted'/q.job_id if result.get('artifact_base') else ROOT/'processed/pdbbind/complexes'/result['pdb_id']
   scene=export_folder(folder,q.job_id[:12] if result.get('artifact_base') else result['pdb_id'])
   with zipfile.ZipFile(io.BytesIO(scene.body)) as assets:
    for name in assets.namelist():archive.writestr('structure/'+name,assets.read(name))
   if result.get('sequence_docking'):
    for source,name in (
     (folder/'docking.json','structure/docking.json'),
     (folder/'fold_metadata.json','structure/fold_metadata.json'),
     (folder/'p2rank'/'protein.pdb_predictions.csv','structure/pocket_rankings.csv'),
    ):
     if source.is_file():archive.write(source,name)
 return Response(output.getvalue(),media_type='application/zip',headers={'Content-Disposition':f'attachment; filename="perceiver_{q.dataset}_report.zip"'})
@app.post('/api/jobs/{jid}/retry')
def retry(jid:str):
 with guard,connect() as c:
  r=c.execute('SELECT * FROM jobs WHERE id=?',(jid,)).fetchone()
  if not r:raise HTTPException(404,'Job not found.')
  if r['status'] not in ('queued','running'):
   c.execute("UPDATE jobs SET status='queued',error=NULL,result=NULL WHERE id=?",(jid,));c.commit();pool.submit(execute_job,jid,r['pair_id'])
 return dict(id=jid)
@app.get('/api/complexes')
def complexes():
 import csv
 with (ROOT/'processed/pdbbind/manifest.csv').open(newline='') as f:return [dict(pdb_id=r['pdb_id'],affinity_raw=r['affinity_raw']) for r in csv.DictReader(f) if r['status']!='excluded']

@app.get('/api/pdbbind/{pdb}/motion')
def pdbbind_motion(pdb:str):
 """Browse a structure independently of any CSV pair; plan off-request."""
 pdb=pdb.lower()
 if len(pdb)!=4 or not pdb.isalnum():raise HTTPException(400,'Enter a four-character PDB ID, for example 2ity.')
 folder=ROOT/'processed/pdbbind/complexes'/pdb
 if not (folder/'metadata.json').is_file():raise HTTPException(404,'This PDB structure was not processed successfully. Check the ID or the exclusions report.')
 cache=folder/'approach_v2.json'
 if cache.exists():return dict(status='completed',pdb_id=pdb,motion=json.loads(cache.read_text()))
 with guard:
  task=pdb_motion_tasks.get(pdb)
  if task is None:task=pool.submit(approach,pdb);pdb_motion_tasks[pdb]=task
 if not task.done():return dict(status='running',pdb_id=pdb)
 try:return dict(status='completed',pdb_id=pdb,motion=task.result())
 except Exception:
  (folder/'motion_error.txt').write_text(traceback.format_exc(),encoding='utf-8')
  with guard:pdb_motion_tasks.pop(pdb,None)
  return dict(status='failed',pdb_id=pdb,message='The final structure is available, but its approach could not be calculated. See motion_error.txt in this structure folder.')

@app.get('/api/results')
def results_summary():
 with connect() as c:receptor_count=c.execute('SELECT count(*) FROM receptor_scanned').fetchone()[0]
 return dict(datasets=coverage(),pdbbind=json.loads((ROOT/'reports/pdbbind_summary.json').read_text()),receptor_structures_indexed=receptor_count,training_tables=json.loads((ROOT/'reports/table_summary.json').read_text()))
@app.get('/api/complex/{pdb}/{file}')
def artifact(pdb:str,file:str):
 if len(pdb)!=4 or not pdb.isalnum() or file not in ('metadata.json','protein.pdb','pocket.pdb','ligand.sdf','graph.npz'):raise HTTPException(404)
 folder=ROOT/'processed/pdbbind/complexes'/pdb
 if not folder.exists():raise HTTPException(404)
 if file=='protein.pdb':
  meta=json.loads((folder/'metadata.json').read_text())
  with zipfile.ZipFile(ROOT/'P-L.zip') as z:return Response(z.read(meta['protein_archive_path']),media_type='text/plain')
 if file=='metadata.json':return enriched_metadata(folder)
 return FileResponse(folder/file)

def enriched_metadata(folder):
 meta=json.loads((folder/'metadata.json').read_text())
 if (folder/'interaction_analysis.json').exists():meta['interaction_analysis']=json.loads((folder/'interaction_analysis.json').read_text())
 return meta

@app.get('/api/jobs/{jid}/files/{file}')
@app.get('/api/pose/{jid}/{file}')
def pose_artifact(jid:str,file:str):
 if len(jid)!=64 or any(c not in '0123456789abcdef' for c in jid) or file not in ('metadata.json','protein.pdb','pocket.pdb','ligand.sdf','graph.npz'):raise HTTPException(404)
 folder=ROOT/'processed/predicted'/jid
 if not (folder/file).exists():raise HTTPException(404)
 return enriched_metadata(folder) if file=='metadata.json' else FileResponse(folder/file)
@app.get('/api/export/{pdb}')
def export(pdb:str):
 if len(pdb)!=4 or not pdb.isalnum():raise HTTPException(404)
 folder=ROOT/'processed/pdbbind/complexes'/pdb
 if not folder.exists():raise HTTPException(404)
 return export_folder(folder,pdb)

def export_folder(folder,name):
 b=io.BytesIO()
 if (folder/'protein.pdb').exists():protein=(folder/'protein.pdb').read_bytes()
 else:
  meta=json.loads((folder/'metadata.json').read_text())
  with zipfile.ZipFile(ROOT/'P-L.zip') as z:protein=z.read(meta['protein_archive_path'])
 pml='''load protein.pdb, receptor
load ligand.sdf, selected_ligand
load pocket.pdb, pocket
hide everything
show cartoon, receptor
color gray70, receptor
show sticks, pocket
color cyan, pocket and elem C
show sticks, selected_ligand
color yellow, selected_ligand and elem C
distance close_contacts, selected_ligand, pocket, 4.0, 0
set orthoscopic, on
set depth_cue, off
set antialias, 2
bg_color white
zoom pocket or selected_ligand
# Geometric contacts, not assigned hydrogen bonds. Final displayed pose.
# Optional: ray 1600, 1200
'''
 with zipfile.ZipFile(b,'w',zipfile.ZIP_DEFLATED) as z:
  z.writestr('protein.pdb',protein);z.writestr('ligand.sdf',(folder/'ligand.sdf').read_bytes());z.writestr('pocket.pdb',(folder/'pocket.pdb').read_bytes());z.writestr('scene.pml',pml)
 return Response(b.getvalue(),media_type='application/zip',headers={'Content-Disposition':f'attachment; filename="{name}_pymol.zip"'})
@app.get('/api/export/pose/{jid}')
def export_pose(jid:str):
 if len(jid)!=64 or any(c not in '0123456789abcdef' for c in jid):raise HTTPException(404)
 folder=ROOT/'processed/predicted'/jid
 if not (folder/'metadata.json').exists():raise HTTPException(404)
 return export_folder(folder,jid[:12])

@app.get('/api/jobs/{jid}/error')
def job_error(jid:str):
 data=job_status(jid)
 return Response(data['error'] or 'No technical error recorded.',media_type='text/plain')

@app.get('/api/coverage')
def coverage():
 output={}
 with connect() as c:
  for ds in ('davis','kiba','metz'):
   model_path=checkpoint_path(ds)
   checkpoint_key=hashlib.sha256(model_path.read_bytes()).hexdigest()+':singleton-v2' if model_path.is_file() else None
   scored={r[0] for r in c.execute('SELECT DISTINCT pair_id FROM scores WHERE dataset=? AND checkpoint=?',(ds,checkpoint_key))} if checkpoint_key else set()
   ids={r[0] for r in c.execute('SELECT DISTINCT pair_id FROM measurements WHERE dataset=? AND pair_id IS NOT NULL',(ds,))}
   matched={r[0] for r in c.execute('SELECT DISTINCT pair_id FROM matches')} & ids
   jobs=[dict(r) for r in c.execute("SELECT * FROM jobs WHERE status!='superseded'") if r['pair_id'] in ids]
   poses=set();animated=set();states={}
   for r in jobs:
    states.setdefault(r['status'],set()).add(r['pair_id'])
    result=json.loads(r['result'] or '{}')
    if r['status']=='completed' and result.get('pose_available'):poses.add(r['pair_id'])
    if r['status']=='completed' and result.get('animation_available') and (result.get('motion',{}).get('version')==2 or result.get('artifact_base')):animated.add(r['pair_id'])
   output[ds]=dict(source_rows=c.execute('SELECT count(*) FROM measurements WHERE dataset=?',(ds,)).fetchone()[0],valid_pairs=len(ids),verified_experimental_pairs=len(matched),no_verified_experimental_match=len(ids-matched),pose_ready_pairs=len(poses),animation_ready_pairs=len(animated),fresh_score_pairs=len(scored),structure_job_pairs_by_status={k:len(v) for k,v in states.items()},score_not_precomputed=len(ids-scored),active_checkpoint_key=checkpoint_key,score_model_available=bool(checkpoint_key))
 return output
@app.on_event('startup')
def recover():
 c=init()
 # Preserve the old traceback, but classify the known missing-data condition
 # correctly for queries submitted before the actionable status was added.
 for row in c.execute("SELECT id,pair_id FROM jobs WHERE status='failed' AND error LIKE '%No verified receptor for this protein sequence is indexed.%'").fetchall():
  result=dict(pair_id=row['pair_id'],pose_available=False,animation_available=False,route='unsupported',message='No verified 3D protein structure was found for this sequence. Your score can still be calculated. Docking needs a matching receptor first. Retry after the protein index is ready or choose a verified pair.')
  c.execute("UPDATE jobs SET status='unsupported',result=? WHERE id=?",(json.dumps(result),row['id']))
 c.commit();pending=list(c.execute("SELECT id,pair_id FROM jobs WHERE status IN ('queued','running')"));c.close()
 for r in pending:pool.submit(execute_job,*r)
app.mount('/vendor',StaticFiles(directory=ROOT/'viewer/vendor'),name='vendor')
app.mount('/experience',StaticFiles(directory=ROOT/'viewer/experience',check_dir=False),name='experience')
@app.get('/')
def home():return FileResponse(ROOT/'viewer/cpi.html')
@app.get('/{filename}')
def static(filename:str):
 if filename not in ('cpi.js','app.js','style.css','bioemu2.js'):raise HTTPException(404)
 return FileResponse(ROOT/'viewer'/filename)
if __name__=='__main__':
 import uvicorn
 uvicorn.run(app,host='127.0.0.1',port=8765)

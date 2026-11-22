"""Account for every valid source pair and write current application coverage."""
import csv,json,hashlib,time,collections,importlib.metadata,shutil
from cpi_app import ROOT,connect,coverage,prediction,Query

def main():
 # Precompute actual scores for every experimental match. Other pairs remain
 # available for on-demand scoring, and are explicitly marked not computed.
 timings=[]
 with connect() as c:
  matched=list(c.execute('SELECT DISTINCT m.dataset,p.* FROM measurements m JOIN pairs p ON p.id=m.pair_id JOIN matches x ON x.pair_id=p.id'))
 for r in matched:
  t=time.time()
  try:prediction(Query(dataset=r['dataset'],smiles=r['smiles'],sequence=r['sequence']));timings.append(time.time()-t)
  except Exception as e:print(r['dataset'],r['id'],str(e),flush=True)
 counts=coverage()
 with connect() as c:
  jobs={}
  for r in c.execute("SELECT * FROM jobs WHERE status!='superseded'"):
   key=r['pair_id'];result=json.loads(r['result'] or '{}')
   if key not in jobs or result.get('pose_available'):jobs[key]=dict(r)|dict(parsed=result)
  for ds in ('davis','kiba','metz'):
   pairs=list(c.execute('SELECT DISTINCT p.id FROM pairs p JOIN measurements m ON m.pair_id=p.id WHERE m.dataset=?',(ds,)))
   scored={r[0] for r in c.execute('SELECT DISTINCT pair_id FROM scores WHERE dataset=? AND checkpoint=?',(ds,counts[ds]['active_checkpoint_key']))};known={r[0] for r in c.execute('SELECT DISTINCT pair_id FROM matches')}
   with (ROOT/f'processed/{ds}/pair_readiness.csv').open('w',newline='',encoding='utf-8') as f:
    fields=['pair_id','affinity_prediction','experimental_pose','structure_job','pose_available','animation_available'];w=csv.DictWriter(f,fieldnames=fields);w.writeheader()
    for r in pairs:
     k=r['id'];j=jobs.get(k,{});out=j.get('parsed',{})
     w.writerow(dict(pair_id=k,affinity_prediction='computed' if k in scored else 'available_on_demand_not_computed',experimental_pose='matched' if k in known else 'no_verified_match',structure_job=j.get('status','not_submitted'),pose_available=bool(out.get('pose_available')),animation_available=bool(out.get('animation_available'))))
   counts[ds]['fresh_score_source_pairs']=len({r['id'] for r in pairs}&scored)
 report=dict(datasets=counts,inference_timing=dict(samples=len(timings),mean_seconds=sum(timings)/max(1,len(timings)),scope='Matched examples; includes model startup on first call and cached examples. Not a full-batch cost estimate.'),routes=dict(experimental='Tested exact ligand plus contacting chain/domain matches',docking='Tested Vina 1.2.7 with Meeko; known-pocket route; strict receptor preparation can reject unsupported systems',complex_prediction='Not installed or tested. Current Torch build is CPU-only; laptop GPU has 4 GB VRAM; no Boltz weights provisioned.',molecular_dynamics='Not run; illustrative transforms only'))
 (ROOT/'reports/cpi_coverage.json').write_text(json.dumps(report,indent=2))
 versions={name:importlib.metadata.version(name) for name in ['fastapi','uvicorn','torch','rdkit','numpy','scipy','biopython','tape-proteins','typed-argument-parser','pandas','scikit-learn','meeko','gemmi','openbabel-wheel','plip','lxml','playwright']}
 (ROOT/'reports/application_versions.json').write_text(json.dumps(versions,indent=2))
 (ROOT/'requirements-app.txt').write_text('\n'.join(f'{k}=={v}' for k,v in versions.items() if k not in ('plip','openbabel-wheel','lxml'))+'\n')
 # PLIP requires the openbabel package name, while this Windows wheel provides
 # its module under a different distribution name. Install these without deps.
 (ROOT/'requirements-contacts.txt').write_text('\n'.join(f'{k}=={versions[k]}' for k in ('openbabel-wheel','lxml','plip'))+'\n')
 print(json.dumps(report,indent=2))

if __name__=='__main__':main()

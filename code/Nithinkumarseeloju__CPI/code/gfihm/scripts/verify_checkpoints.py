"""Recover test ordering, then reproduce predictions without SMILES-only joins."""
import ast,csv,json,shutil,hashlib
from pathlib import Path
from cpi_inference import ROOT,predict,predict_reference_batch,checkpoint_path
report={}
for ds in ('davis','kiba','metz'):
 src=Path(fr'H:\siddu\perceiver_gpu\data\splits\{ds}\novel_pair\fold0_test.csv')
 dest=ROOT/f'models/reference_splits/{ds}_test.csv';dest.parent.mkdir(parents=True,exist_ok=True)
 if src.exists():shutil.copy2(src,dest)
 with dest.open() as f:original=list(csv.DictReader(f))
 with (ROOT/f'models/runs/{ds}/fold_0/test_preds.csv').open() as f:saved=list(csv.DictReader(f))
 ordered=len(original)==len(saved) and all(ast.literal_eval(b['smiles'])==[a['smiles']] for a,b in zip(original,saved))
 differences=[];batch_differences=[]
 if ordered:
  for i in (0,len(original)//2,len(original)-1):
   r=original[i];fresh=predict(ds,r['smiles'],r['sequence']);differences.append(dict(test_row=i+2,fresh=fresh['score'],saved=float(saved[i]['label']),absolute_error=abs(fresh['score']-float(saved[i]['label']))))
  for start in sorted({0,(len(original)//2//50)*50,((len(original)-1)//50)*50}):
   fresh=predict_reference_batch(ds,original[start:start+50])
   batch_differences.extend(abs(x-float(saved[start+j]['label'])) for j,x in enumerate(fresh))
 report[ds]=dict(original_test_rows=len(original),saved_prediction_rows=len(saved),entire_smiles_order_matches=ordered,ordering_evidence='Recovered original fold0_test.csv; verified every ordered compound against the saved prediction file. Protein comes from that same original row. Numerical checks additionally test this inferred ordering.',single_pair_samples=differences,batch_samples=len(batch_differences),batch_max_error=max(batch_differences,default=None),numerically_reproduced=ordered and max(batch_differences)<1e-4,tolerance=1e-4,batch_dependence='Original mpn.py uses mean over padded neighbor slots. Single-pair predictions need not equal predictions with other molecules in a batch. Live API uses deterministic singleton batches.')
for ds in report:report[ds]['checkpoint_sha256']=hashlib.sha256(checkpoint_path(ds).read_bytes()).hexdigest()
(ROOT/'reports/checkpoint_verification.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))

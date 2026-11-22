"""Strict checkpoint loading; original Perceiver CPI featurization and scaler."""
import sys,hashlib,json,threading,io,os
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'model_source'))
LOCK=threading.Lock();CACHE={}

def checkpoint_path(dataset):
 if dataset not in ('davis','kiba','metz'):raise ValueError('Unknown dataset')
 base=Path(os.environ['CPI_MODEL_ROOT']).expanduser().resolve() if os.environ.get('CPI_MODEL_ROOT') else ROOT/'models/runs'
 return base/dataset/'fold_0/model_0/model.pt'
def predict(dataset,smiles,sequence):
 if dataset not in ('davis','kiba','metz'):raise ValueError('Unknown dataset')
 import torch
 from chemprop.args import TrainArgs
 from chemprop.models import InteractionModel
 from chemprop.data import MoleculeDatapoint,MoleculeDataset
 from tape import TAPETokenizer
 torch.set_num_threads(2)
 path=checkpoint_path(dataset)
 with LOCK:
  checkpoint_bytes=path.read_bytes()
  checkpoint_sha=hashlib.sha256(checkpoint_bytes).hexdigest()
  if dataset not in CACHE or CACHE[dataset][3]!=checkpoint_sha:
   # User-supplied training checkpoints; only these local files are deserialized.
   state=torch.load(io.BytesIO(checkpoint_bytes),map_location='cpu',weights_only=False)
   args=TrainArgs();args.from_dict(vars(state['args']),skip_unsettable=True);args.device=torch.device('cpu')
   model=InteractionModel(args);model.load_state_dict(state['state_dict'],strict=True);model.eval()
   CACHE[dataset]=(model,args,state['data_scaler'],checkpoint_sha)
  model,args,scaler,sha=CACHE[dataset]
  tok=TAPETokenizer(vocab='unirep');encoded=list(tok.encode(list(sequence)));n=len(encoded)
  encoded=(encoded+[0]*args.sequence_length)[:args.sequence_length]
  data=MoleculeDataset([MoleculeDatapoint(smiles=[smiles],sequences=[sequence])])
  with torch.inference_mode():out=model(data.batch_graph(),torch.tensor([encoded],dtype=torch.long),torch.tensor(np.asarray(data.add_features()),dtype=torch.float32)).cpu().numpy()
  if scaler is not None:out=out.astype(float)*np.asarray(scaler['stds'])+np.asarray(scaler['means'])
  score=float(out[0,0])
  if not np.isfinite(score):raise ValueError('The model returned an invalid number.')
  display_path=str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path)
  return dict(dataset=dataset,score=score,score_label='Predicted KIBA score' if dataset=='kiba' else f'Predicted {dataset.title()} score (source scale; units unverified)',checkpoint=display_path,checkpoint_sha256=sha,strict_weights_verified=True,sequence_tokens=n,sequence_limit=args.sequence_length,sequence_handling=f'Original training rule: UniRep tokens including start/stop, zero-pad then retain first {args.sequence_length} tokens.',truncated=n>args.sequence_length,batch_policy='Deterministic single-pair inference. Original MPN averages padded neighbors; historical batch predictions can differ depending on companion molecules.')

def predict_reference_batch(dataset,rows):
 """Reproduce original test batches, including original neighbor padding."""
 predict(dataset,rows[0]['smiles'],rows[0]['sequence'])
 import torch
 from chemprop.data import MoleculeDatapoint,MoleculeDataset
 from tape import TAPETokenizer
 with LOCK:
  model,args,scaler,_=CACHE[dataset];tok=TAPETokenizer(vocab='unirep')
  encoded=[(list(tok.encode(list(r['sequence'])))+[0]*args.sequence_length)[:args.sequence_length] for r in rows]
  data=MoleculeDataset([MoleculeDatapoint(smiles=[r['smiles']],sequences=[r['sequence']]) for r in rows])
  with torch.inference_mode():out=model(data.batch_graph(),torch.tensor(encoded,dtype=torch.long),torch.tensor(np.asarray(data.add_features()),dtype=torch.float32)).cpu().numpy().astype(float)
  if scaler is not None:out=out*np.asarray(scaler['stds'])+np.asarray(scaler['means'])
  return out[:,0].tolist()
if __name__=='__main__':
 import csv
 reports={}
 for ds in ('davis','kiba','metz'):
  with (ROOT/f'{ds}.csv').open() as f:r=next(csv.DictReader(f))
  try:reports[ds]=predict(ds,r['compound_iso_smiles'],r['target_sequence'])
  except Exception as e:reports[ds]=dict(error=str(e));raise
 (ROOT/'reports/live_inference.json').write_text(json.dumps(reports,indent=2));print(json.dumps(reports,indent=2))

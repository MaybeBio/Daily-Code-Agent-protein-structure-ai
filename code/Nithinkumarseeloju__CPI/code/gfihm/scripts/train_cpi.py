"""Train the recovered score architecture on prepared splits, with timing/resume."""
import argparse,csv,hashlib,importlib,json,random,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def main():
 p=argparse.ArgumentParser(description=__doc__)
 p.add_argument('--dataset',required=True,choices=['davis','kiba','metz'])
 p.add_argument('--epochs',type=int)
 p.add_argument('--batch-size',type=int,default=16)
 p.add_argument('--device',choices=['auto','cpu','cuda'],default='auto')
 p.add_argument('--threads',type=int,default=2)
 p.add_argument('--smoke',action='store_true',help='Use 128 train/32 validation/32 test rows; a code check, not an accuracy experiment.')
 p.add_argument('--resume',action='store_true')
 p.add_argument('--output',type=Path)
 args=p.parse_args();epochs=args.epochs if args.epochs is not None else (1 if args.smoke else 150)
 if epochs<1 or args.batch_size<1 or args.threads<1:p.error('Epochs, batch size and threads must be positive.')
 output=(args.output or ROOT/'training_runs'/(args.dataset+('_smoke' if args.smoke else ''))).resolve()
 if not output.is_relative_to((ROOT/'training_runs').resolve()):p.error(f'Training output must be inside {ROOT / "training_runs"}, so supplied models cannot be overwritten.')
 manifest_path=output/'run_manifest.json'
 if output.exists() and any(output.iterdir()) and not args.resume:p.error('This output already contains files. Use --resume or choose a new --output folder.')
 source_paths={split:ROOT/f'processed/{args.dataset}/{split}.csv' for split in ('train','val','test')}
 source_hashes={split:hashlib.sha256(path.read_bytes()).hexdigest() for split,path in source_paths.items()}
 signature=dict(dataset=args.dataset,source_sha256=source_hashes,batch_size=args.batch_size,smoke=args.smoke,seed=42,architecture='Recovered PerceiverCPI, sequence_length=500, original featurization')
 if args.resume:
  if not manifest_path.exists():p.error('No matching training manifest exists in this output folder.')
  if json.loads(manifest_path.read_text())['signature']!=signature:p.error('Dataset, split files or training settings changed. Use a new output folder.')
 output.mkdir(parents=True,exist_ok=True);data_paths={};counts={};full_counts={}
 for split,path in source_paths.items():
  with path.open(newline='',encoding='utf-8') as f:rows=list(csv.DictReader(f))
  full_counts[split]=len(rows)
  if args.smoke:
   rows=random.Random(42).sample(rows,min(len(rows),128 if split=='train' else 32))
   dest=output/f'{split}.csv'
   with dest.open('w',newline='',encoding='utf-8') as f:
    writer=csv.DictWriter(f,fieldnames=['smiles','sequence','label']);writer.writeheader();writer.writerows({k:r[k] for k in writer.fieldnames} for r in rows)
   data_paths[split]=dest
  else:data_paths[split]=path
  counts[split]=len(rows)
 sys.path.insert(0,str(ROOT/'model_source'))
 import torch
 torch.set_num_threads(args.threads)
 use_cuda=torch.cuda.is_available() if args.device=='auto' else args.device=='cuda'
 if use_cuda and not torch.cuda.is_available():p.error('This Torch installation cannot use CUDA. Choose --device cpu, or install and verify a compatible GPU environment separately.')
 from chemprop.args import TrainArgs
 from chemprop.train.cross_validate import cross_validate
 module=importlib.import_module('chemprop.train.run_training')
 train_args=TrainArgs().parse_args([
  '--data_path',str(data_paths['train']),'--separate_val_path',str(data_paths['val']),
  '--separate_test_path',str(data_paths['test']),'--save_dir',str(output),
  '--dataset_type','regression','--target_columns','label','--smiles_columns','smiles',
  '--metric','mse','--epochs',str(epochs),'--batch_size',str(args.batch_size),
  '--num_workers','0','--ensemble_size','1','--num_folds','1','--seed','42','--pytorch_seed','42',
  '--aggregation','mean','--dropout','0.1','--sequence_length','500','--save_preds','--resume',
 ]+([] if use_cuda else ['--no_cuda']))
 manifest=dict(signature=signature,device='cuda' if use_cuda else 'cpu',torch=torch.__version__,threads=args.threads,epochs=epochs,rows=counts,full_split_rows=full_counts,notes='Original score architecture; this trains affinity scores, not poses or physical motion. Smoke-test metrics do not establish accuracy.')
 manifest_path.write_text(json.dumps(manifest,indent=2),encoding='utf-8')
 times=[]
 def timed(phase,func):
  def wrapped(*a,**kw):
   if use_cuda:torch.cuda.synchronize()
   start=time.perf_counter();result=func(*a,**kw)
   if use_cuda:torch.cuda.synchronize()
   record=dict(phase=phase,seconds=time.perf_counter()-start)
   times.append(record)
   with (output/'timings.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps(record)+'\n')
   print(json.dumps(record),flush=True);return result
  return wrapped
 module.train=timed('training_epoch',module.train);module.evaluate=timed('validation_epoch',module.evaluate)
 started=time.perf_counter();cross_validate(train_args,train_func=module.run_training)
 report=dict(result='PASS',dataset=args.dataset,device=manifest['device'],torch=manifest['torch'],threads=args.threads,batch_size=args.batch_size,epochs_requested=epochs,rows=counts,full_split_rows=full_counts,wall_seconds=time.perf_counter()-started,timings=times,output=str(output),checkpoint=str(output/'fold_0/model_0/model.pt'),resume_checkpoint=str(output/'fold_0/model_0/resume.pt'))
 (output/'training_report.json').write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report,indent=2))
if __name__=='__main__':main()

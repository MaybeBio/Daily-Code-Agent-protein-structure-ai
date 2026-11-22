"""Resumable batch over all valid original pairs; safe to restart."""
import argparse,json
from cpi_app import connect,submit,pool,coverage,prediction,Query,init,recover
p=argparse.ArgumentParser();p.add_argument('--dataset',choices=['davis','kiba','metz'],required=True);p.add_argument('--limit',type=int,default=0);p.add_argument('--scores',action='store_true');p.add_argument('--matched-only',action='store_true');p.add_argument('--recover',action='store_true',help='Recover interrupted jobs. Stop the web server before using this option.');p.add_argument('--method',choices=['experimental','dock','redock'],default='experimental');args=p.parse_args()
init().close()
if args.recover:recover()
with connect() as c:
 sql='SELECT DISTINCT p.* FROM pairs p JOIN measurements m ON p.id=m.pair_id WHERE m.dataset=?'
 if args.matched_only:sql+=' AND EXISTS(SELECT 1 FROM matches x WHERE x.pair_id=p.id)'
 rows=list(c.execute(sql+' ORDER BY p.id',(args.dataset,)))
if args.limit:rows=rows[:args.limit]
for i,r in enumerate(rows):
 submit(r['id'],args.method)
 if args.scores:
  try:prediction(Query(dataset=args.dataset,smiles=r['smiles'],sequence=r['sequence']))
  except Exception as e:print(r['id'],str(e),flush=True)
 if i%500==0:print(i,'submitted',flush=True)
pool.shutdown(wait=True);print(json.dumps(coverage(),indent=2))

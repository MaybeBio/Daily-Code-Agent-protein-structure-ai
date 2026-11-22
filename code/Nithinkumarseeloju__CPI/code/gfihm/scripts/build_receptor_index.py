"""Resume protein-only indexing for docking new compounds at known pockets."""
import argparse,csv,json,hashlib,time,collections,zipfile
from concurrent.futures import ProcessPoolExecutor
from cpi_data import ROOT,init,connect
from preprocess import parse_protein,AA
ARCHIVE=None

def initialize():
 global ARCHIVE
 ARCHIVE=zipfile.ZipFile(ROOT/'P-L.zip')

def scan(row):
 pdb=row['pdb_id']
 try:
  meta=json.loads((ROOT/f'processed/pdbbind/complexes/{pdb}/metadata.json').read_text())
  pocket_chains={a['chain'] for a in meta['pocket_atom_metadata']}
  chains=collections.defaultdict(list);seen=set()
  for line in ARCHIVE.read(row['protein_archive_path']).decode().splitlines():
   if line.startswith('ENDMDL'):break
   if line[:6].strip() not in ('ATOM','HETATM') or line[17:20].strip() not in AA:continue
   chain=line[21:22].strip();residue=(chain,line[22:26],line[26:27])
   if residue in seen:continue
   seen.add(residue);chains[chain].append(AA[line[17:20].strip()])
  records=[(pdb,chain,''.join(letters)) for chain,letters in chains.items() if chain in pocket_chains and len(letters)>=50 and 'X' not in letters]
  return pdb,records,None
 except Exception as exc:return pdb,[],str(exc)

def main():
 parser=argparse.ArgumentParser();parser.add_argument('--workers',type=int,default=4);args=parser.parse_args()
 init().close();manifest=ROOT/'processed/pdbbind/manifest.csv';source=ROOT/'P-L.zip'
 fingerprint=hashlib.sha256(manifest.read_bytes()).hexdigest()+f':{source.stat().st_size}:{source.stat().st_mtime_ns}:v1'
 with manifest.open(newline='',encoding='utf-8') as handle:rows=[r for r in csv.DictReader(handle) if r['status']=='accepted']
 with connect() as c:
  previous=c.execute("SELECT value FROM receptor_index_state WHERE key='sources'").fetchone()
  if previous and previous[0]!=fingerprint:raise ValueError('Source structures changed. Rebuild into a new database or explicitly clear only the receptor index tables after preserving the old index.')
  c.execute("INSERT OR IGNORE INTO receptor_index_state VALUES ('sources',?)",(fingerprint,));c.commit()
  done={r[0] for r in c.execute('SELECT pdb_id FROM receptor_scanned')}
 pending=[r for r in rows if r['pdb_id'] not in done];errors=[];started=time.time()
 with ProcessPoolExecutor(max_workers=args.workers,initializer=initialize) as pool,connect() as c:
  for count,(pdb,records,error) in enumerate(pool.map(scan,pending,chunksize=16),1):
   if error:errors.append(dict(pdb_id=pdb,error=error))
   else:
    c.executemany('INSERT OR REPLACE INTO receptors VALUES (?,?,?)',records)
    c.execute('INSERT OR IGNORE INTO receptor_scanned VALUES (?)',(pdb,))
   # Never keep a SQLite write transaction open while waiting for workers.
   # That would block the website's job and score updates during indexing.
   c.commit()
   if count%250==0:print(f'Protein structures indexed: {count}/{len(pending)}',flush=True)
  c.commit()
  report=dict(eligible_structures=len(rows),scanned_structures=c.execute('SELECT count(*) FROM receptor_scanned').fetchone()[0],contacting_chains=c.execute('SELECT count(*) FROM receptors').fetchone()[0],unique_chain_sequences=c.execute('SELECT count(DISTINCT sequence) FROM receptors').fetchone()[0],reused_structures=len(done),errors=errors,seconds=time.time()-started,matching='Exact contacting chain/domain sequence; Biopython verifies candidates before docking. Independent of compound identity; no sequence similarity approximation.')
 (ROOT/'reports/receptor_index.json').write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report,indent=2))
if __name__=='__main__':main()

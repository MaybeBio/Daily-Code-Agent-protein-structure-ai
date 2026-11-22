"""All source rows retained; explicit flags and truthful coverage accounting."""
import csv,json,hashlib,collections,time,io,zipfile,sys
from rdkit import Chem,RDLogger
from Bio.PDB import PDBParser
from cpi_data import ROOT,init,connect
from preprocess import AA

def audit():
 RDLogger.DisableLog('rdApp.*');c=init();c.execute('CREATE TABLE IF NOT EXISTS row_flags(dataset TEXT,row_id INTEGER,flags TEXT,PRIMARY KEY(dataset,row_id))')
 cache={};totals={}
 for ds in ('davis','kiba','metz'):
  rows=list(c.execute('SELECT * FROM measurements WHERE dataset=? ORDER BY row_id',(ds,)));groups=collections.defaultdict(list)
  with (ROOT/f'{ds}.csv').open(newline='',encoding='utf-8-sig') as f:source=list(csv.DictReader(f))
  assert len(rows)==len(source)
  for r,s in zip(rows,source):
   assert r['original_smiles']==s['compound_iso_smiles'] and r['original_sequence']==s['target_sequence'] and r['original_score']==s['affinity']
   groups[r['pair_id']].append(r)
  counts=collections.Counter()
  for pair,rs in groups.items():
   scores={r['original_score'] for r in rs};seen={}
   for r in rs:
    flags=[]
    if len(scores)>1:flags.append('conflicting_scores_preserved')
    if r['original_score'] in seen:flags.append('duplicate_of_row_'+str(seen[r['original_score']]))
    else:seen[r['original_score']]=r['row_id']
    if pair:
     smiles=c.execute('SELECT smiles FROM pairs WHERE id=?',(pair,)).fetchone()[0]
     if smiles not in cache:
      m=Chem.MolFromSmiles(smiles);cache[smiles]=any(str(x.specified)=='Unspecified' for x in Chem.FindPotentialStereo(m))
     if cache[smiles]:flags.append('unspecified_stereochemistry')
    if not pair:flags.append('invalid_pair')
    for flag in flags:counts['duplicate_preserved' if flag.startswith('duplicate') else flag]+=1
    c.execute('INSERT OR REPLACE INTO row_flags VALUES (?,?,?)',(ds,r['row_id'],';'.join(flags)))
  c.commit();totals[ds]=dict(rows=len(rows),unique_pairs=len(groups),flags=dict(counts))
 # Independently parse each matched structure with Biopython and compare the
 # selected chain, domain boundaries, and actual ligand-contact chain.
 checked=0;removed=[]
 with zipfile.ZipFile(ROOT/'P-L.zip') as z:
  for r in list(c.execute('SELECT x.*,p.sequence FROM matches x JOIN pairs p ON x.pair_id=p.id')):
   meta=json.loads((ROOT/f"processed/pdbbind/complexes/{r['pdb_id']}/metadata.json").read_text());text=z.read(meta['protein_archive_path']).decode()
   model=next(PDBParser(QUIET=True).get_structure(r['pdb_id'],io.StringIO(text)).get_models());chain=model[r['chain']]
   sequence=''.join(AA.get(res.resname,'X') for res in chain if res.id[0]==' ' or res.resname in AA)
   pocket_chains={a['chain'] for a in meta['pocket_atom_metadata']}
   assert sequence==r['sequence'][r['query_start']-1:r['query_end']]
   if r['chain'] not in pocket_chains:
    c.execute('DELETE FROM matches WHERE pair_id=? AND pdb_id=? AND chain=?',(r['pair_id'],r['pdb_id'],r['chain']));removed.append([r['pdb_id'],r['chain']])
   else:checked+=1
 c.commit();c.close()
 report=dict(source_rows_verified=totals,matched_chains_verified=checked,nonpocket_chain_matches_removed=removed,policy='Every original row and score string preserved. Conflicting measurements remain searchable. Training CSV filters are a separate view.',result='PASS')
 (ROOT/'reports/cpi_source_audit.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))
if __name__=='__main__':audit()

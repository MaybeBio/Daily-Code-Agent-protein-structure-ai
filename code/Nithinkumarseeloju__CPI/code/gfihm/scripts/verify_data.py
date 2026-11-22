"""Independent checks of every emitted graph and split; no model training."""
import collections,csv,hashlib,json,math,sys,time,zipfile
from pathlib import Path
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
def rows(path):
    with Path(path).open(encoding='utf-8',newline='') as f:return list(csv.DictReader(f))

def main():
    start=time.time();manifest=rows(ROOT/'processed/pdbbind/manifest.csv');errors=[];checked=0;edge_count=0
    for r in manifest:
        if not r['graph_path']:continue
        try:
            with np.load(ROOT/r['graph_path'],allow_pickle=False) as g:
                x,f,e,d=g['positions'],g['node_features'],g['edge_index'],g['edge_distance']
                n=int(g['ligand_atom_count'])
                assert x.ndim==2 and x.shape[1]==3
                assert f.shape==(len(x),10) and n==int(r['ligand_atoms'])
                assert np.isfinite(x).all() and np.isfinite(f).all() and np.isfinite(d).all()
                assert e.shape==(2,len(d)) and e.min()>=0 and e.max()<len(x)
                assert np.all(e[0]!=e[1]) and np.all(d<=4.50001)
                assert np.allclose(d,np.linalg.norm(x[e[0]]-x[e[1]],axis=1),atol=2e-5)
                assert np.all(f[:n,9]==1) and np.all(f[n:,9]==0)
                assert np.all(f[n:,4]==0), 'Protein partial charges must be unknown'
                assert np.all(f[f[:,4]==0,3]==0), 'Unknown charge placeholders must be zero'
                assert np.allclose(float(g['p_affinity']),-math.log10(float(r['affinity_molar'])),atol=2e-6)
                assert np.array_equal(e[:,:e.shape[1]//2],e[::-1,e.shape[1]//2:])
                b=g['ligand_bond_index'];assert b.shape[0]==2 and b.min()>=0 and b.max()<n
                edge_count+=len(d)
            checked+=1
        except Exception as exc:errors.append(dict(pdb_id=r['pdb_id'],error=str(exc),type=type(exc).__name__))
        if checked%3000==0:print('Verified',checked,'graphs',flush=True)
    splits={s:rows(ROOT/f'processed/pdbbind/{s}.csv') for s in ('train','val','test')}
    membership=collections.Counter(r['pdb_id'] for rs in splits.values() for r in rs)
    eligible={r['pdb_id'] for r in manifest if r['training_eligible']=='True'}
    assert set(membership)==eligible and all(v==1 for v in membership.values())
    byid={r['pdb_id']:r for r in manifest}
    for s,rs in splits.items():
        for r in rs:
            assert byid[r['pdb_id']]['affinity_operator']=='='
            assert byid[r['pdb_id']]['status']=='accepted'
            assert float(r['p_affinity'])==float(byid[r['pdb_id']]['p_affinity'])
    seqs={s:{h for r in rs for h in byid[r['pdb_id']]['protein_chain_hashes'].split(';')} for s,rs in splits.items()}
    for a,b in [('train','val'),('train','test'),('val','test')]:assert not seqs[a]&seqs[b]
    tables=json.loads((ROOT/'reports/table_summary.json').read_text())
    for name,summary in tables['datasets'].items():
        assert summary['input_rows']==summary['accepted_unique_pairs']+summary['excluded_rows']
        seen=set()
        for s in ('train','val','test'):
            for r in rows(ROOT/f'processed/{name}/{s}.csv'):
                key=hashlib.sha256((r['smiles']+'|'+r['sequence']).encode()).hexdigest()
                assert key==r['pair_id'] and key not in seen;seen.add(key)
                bucket=int(key[:16],16)%10000
                assert s==('train' if bucket<8000 else 'val' if bucket<9000 else 'test')
        assert len(seen)==summary['accepted_unique_pairs']
    report=dict(result='PASS' if not errors else 'FAIL',graphs_checked=checked,directed_edges_checked=edge_count,errors=errors,checks=['All emitted NPZ arrays readable with allow_pickle=False','Finite coordinates/features and correct shapes','All spatial edges in range and distances recomputed','Directed edges paired in both directions','Ligand bonds index ligand atoms only','Unknown protein partial charges masked','All labels independently recalculated from molar values','Training eligibility and complete disjoint PDB-ID splits','Zero exact observed protein chain overlap across PDBbind splits','All CSV row totals and pair identities/splits'],seconds=round(time.time()-start,1))
    (ROOT/'reports/data_validation.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))
    if errors:sys.exit(1)

if __name__=='__main__':main()

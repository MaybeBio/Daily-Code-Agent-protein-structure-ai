"""Validate the new 2D feature outputs and assay-specific split exports."""
import csv,json
from pathlib import Path
import numpy as np
from rdkit import Chem

ROOT=Path(__file__).resolve().parents[1]
def rows(path):
    with Path(path).open(encoding='utf-8',newline='') as f:return list(csv.DictReader(f))

unique={}
for name in ('davis','kiba','metz'):
    for r in rows(ROOT/f'processed/{name}/ligand_lookup.csv'):unique[r['compound_id']]=r
for cid,r in unique.items():
    mol=Chem.MolFromSmiles(r['smiles'])
    with np.load(ROOT/r['graph_path'],allow_pickle=False) as g:
        f,e,b=g['node_features'],g['bond_index'],g['bond_features']
        assert 'positions' not in g.files
        assert f.shape==(mol.GetNumAtoms(),6) and np.isfinite(f).all()
        assert e.shape==(2,2*mol.GetNumBonds()) and b.shape==(2*mol.GetNumBonds(),4)
        assert np.array_equal(f[:,0],[a.GetAtomicNum() for a in mol.GetAtoms()])
        assert np.array_equal(f[:,1],[a.GetFormalCharge() for a in mol.GetAtoms()])
        for i in range(e.shape[1]):
            bond=mol.GetBondBetweenAtoms(int(e[0,i]),int(e[1,i]));assert bond is not None
            assert b[i,0]==bond.GetBondTypeAsDouble()
split_counts={}
for split in ('train','val','test'):
    base=rows(ROOT/f'processed/pdbbind/{split}.csv');seen=set()
    for kind in ('Kd','Ki','IC50'):
        subset=rows(ROOT/f'processed/pdbbind/by_affinity_type/{kind}/{split}.csv')
        assert all(r['affinity_type']==kind for r in subset)
        assert not seen&{r['pdb_id'] for r in subset}
        seen.update(r['pdb_id'] for r in subset);split_counts[f'{kind}/{split}']=len(subset)
    assert seen=={r['pdb_id'] for r in base}
report=dict(result='PASS',unique_2d_graphs_checked=len(unique),assay_split_counts=split_counts,checks=['Every 2D graph matches RDKit atom identities, formal charges and bond orders','All features finite; no invented coordinate arrays','Assay subsets contain exactly the base split records with the right assay type'])
(ROOT/'reports/additional_validation.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))

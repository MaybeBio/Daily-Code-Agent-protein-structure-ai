"""Chemical graphs for CSV compounds. No coordinates or binding poses are invented."""
import collections,csv,hashlib,json
from pathlib import Path
import numpy as np
from rdkit import Chem,RDLogger
from rdkit.Chem import rdPartialCharges

ROOT=Path(__file__).resolve().parents[1]
FEATURES=['atomic_number','formal_charge','gasteiger_charge','gasteiger_charge_known','aromatic','hybridization_rdkit_enum']

def main():
    RDLogger.DisableLog('rdApp.*');by_dataset={};all_smiles=set()
    for name in ('davis','kiba','metz'):
        unique=set()
        for split in ('train','val','test'):
            with (ROOT/f'processed/{name}/{split}.csv').open(newline='',encoding='utf-8') as f:
                unique.update(r['smiles'] for r in csv.DictReader(f))
        by_dataset[name]=unique;all_smiles.update(unique)
    out=ROOT/'processed/ligands2d';out.mkdir(parents=True,exist_ok=True);catalog={};warnings=[]
    for smiles in sorted(all_smiles):
        cid=hashlib.sha256(smiles.encode()).hexdigest();mol=Chem.MolFromSmiles(smiles)
        if mol is None:raise ValueError('Previously validated ligand became unreadable')
        charges=None
        try:
            m=Chem.AddHs(mol);rdPartialCharges.ComputeGasteigerCharges(m,throwOnParamFailure=True)
            charges=np.array([float(m.GetAtomWithIdx(i).GetProp('_GasteigerCharge')) for i in range(mol.GetNumAtoms())])
            if not np.isfinite(charges).all():raise ValueError('nonfinite')
        except Exception:charges=None;warnings.append(cid)
        features=[[a.GetAtomicNum(),a.GetFormalCharge(),charges[i] if charges is not None else 0,int(charges is not None),int(a.GetIsAromatic()),int(a.GetHybridization())] for i,a in enumerate(mol.GetAtoms())]
        edges=[];ef=[]
        for b in mol.GetBonds():
            i,j=b.GetBeginAtomIdx(),b.GetEndAtomIdx()
            for u,v in ((i,j),(j,i)):
                edges.append([u,v]);ef.append([b.GetBondTypeAsDouble(),b.GetIsAromatic(),b.GetIsConjugated(),b.IsInRing()])
        np.savez_compressed(out/f'{cid}.npz',node_features=np.asarray(features,np.float32),bond_index=np.asarray(edges,np.int32).reshape(-1,2).T,bond_features=np.asarray(ef,np.float32).reshape(-1,4))
        catalog[smiles]=dict(compound_id=cid,smiles=smiles,graph_path=f'processed/ligands2d/{cid}.npz',atom_count=mol.GetNumAtoms(),partial_charges_known=charges is not None)
    for name,ss in by_dataset.items():
        with (ROOT/f'processed/{name}/ligand_lookup.csv').open('w',newline='',encoding='utf-8') as f:
            w=csv.DictWriter(f,fieldnames=['compound_id','smiles','graph_path','atom_count','partial_charges_known']);w.writeheader();w.writerows(catalog[s] for s in sorted(ss))
    result=dict(unique_compounds=len(catalog),per_dataset={n:len(s) for n,s in by_dataset.items()},node_feature_names=FEATURES,bond_features=['bond_order','aromatic','conjugated','in_ring'],partial_charge_unavailable_compound_ids=warnings,coordinates_available=False,usage='Join each dataset split to its ligand_lookup.csv on canonical smiles. Graphs encode ligand chemistry only, not 3D positions or protein pockets.')
    (ROOT/'reports/ligand2d_summary.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result,indent=2))

if __name__=='__main__':main()

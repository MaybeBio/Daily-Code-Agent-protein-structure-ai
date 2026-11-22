"""Read the generic graph format without PyTorch or pickle."""
import argparse,json
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('pdb_id',nargs='?',default='10gs');args=p.parse_args()
    if len(args.pdb_id)!=4 or not args.pdb_id.isalnum():p.error('Use a four-character PDB ID.')
    folder=ROOT/'processed/pdbbind/complexes'/args.pdb_id.lower()
    meta=json.loads((folder/'metadata.json').read_text())
    with np.load(folder/'graph.npz',allow_pickle=False) as graph:
        for name in graph.files:print(name,graph[name].shape,graph[name].dtype)
        print('Label:',meta['affinity_raw'],'=>',meta['p_affinity_operator'],meta['p_affinity'],'type:',meta['affinity_type'])
        print('Training eligible:',meta['training_eligible'])
        print('Feature order:',meta['node_feature_names'])
    # A downstream PyTorch adapter can use torch.from_numpy for each array.
    # Convert edge indices to int64, retain masks, and keep affinity_type.
    # Do not feed mixed pKd/pKi/pIC50 targets to a model without an assay policy.

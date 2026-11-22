import argparse
from pathlib import Path

import torch
from torch import tensor
from pandas import concat
from torch.nn.utils.rnn import pad_sequence
from atom3d.datasets import LMDBDataset


def pdb_loader(dict, mode='train', path='../../split-by-protein/data/', dist_bar=6, output_dir='../data/pdb'):
    source = Path(path) / mode
    if mode == 'val' and not source.is_dir() and (source.parent / 'valid').is_dir():
        source = source.parent / 'valid'
    dataset = LMDBDataset(str(source))
    x, pos, y = [], [], []
    for i in range(len(dataset)):
        struct = dataset[i]
        if struct['label'] == 'A':
            y += [1]
            key = 'atoms_active'
        else:
            y += [0]
            key = 'atoms_inactive'

        atoms = struct[key]
        lig = atoms[atoms.resname == 'UNK']
        protein = atoms[atoms.resname != 'UNK']
        dist = torch.cdist(tensor(protein[['x', 'y', 'z']].values), tensor(lig[['x', 'y', 'z']].values))
        mask = (torch.sum(dist <= dist_bar, dim=-1) > 0)
        atoms = concat((protein[mask.numpy()], lig))

        pos.append(tensor(atoms[['x', 'y', 'z']].values))
        x_tmp = []
        for m in atoms['element']:
            if m in dict.keys():
                x_tmp.append(dict[m])
            else:
                x_tmp.append(len(dict) + 1)
                dict[m] = len(dict) + 1
        x.append(tensor(x_tmp))

    x = pad_sequence(x, batch_first=True, padding_value=0)
    pos = pad_sequence(pos, batch_first=True, padding_value=0)
    y = tensor(y)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    torch.save([x, pos, y], output_dir / f'lep_{mode}.pt')
    print(f'Loading {len(x)} data samples with {len(dict)} atom types.')
    return dict


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Prepare ATOM3D LEP splits.')
    parser.add_argument('--input-dir', required=True, help='Directory containing the split LMDBs.')
    parser.add_argument('--output-dir', default='data/pdb')
    args = parser.parse_args()
    vocabulary = {}
    for mode in ('train', 'val', 'test'):
        pdb_loader(vocabulary, mode=mode, path=args.input_dir, output_dir=args.output_dir)

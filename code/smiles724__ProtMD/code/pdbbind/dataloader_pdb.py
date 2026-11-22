import argparse
from pathlib import Path

import numpy as np
import json
import torch
from torch.nn.utils.rnn import pad_sequence
from atom3d.datasets import LMDBDataset
import atom3d.util.formats as fo


def pdb_loader(dict, mode='train', split='30', path='../../../../split-by-sequence-identity-*/data/', output_dir='../data/pdb'):
    path = path.replace('*', split)
    source = Path(path) / mode
    if mode == 'val' and not source.is_dir() and (source.parent / 'valid').is_dir():
        source = source.parent / 'valid'
    dataset = LMDBDataset(str(source))
    x, idx, pos = [], [], []
    for i in range(len(dataset)):
        if i % 1000 == 0: print(f'Currently processed at {i}')
        struct = dataset[i]
        atoms_pocket = struct['atoms_pocket']
        atoms_ligand = struct['atoms_ligand']
        x_tmp = []
        for m in np.append(atoms_pocket['element'], atoms_ligand['element']):
            if m in dict.keys():
                x_tmp.append(dict[m])
            else:
                x_tmp.append(len(dict) + 1)
                dict[m] = len(dict) + 1
        pos_1, pos_2 = fo.get_coordinates_from_df(atoms_pocket), fo.get_coordinates_from_df(atoms_ligand)
        x.append(torch.tensor(x_tmp))
        pos.append(torch.tensor(np.append(pos_1, pos_2, axis=0)))

    x = pad_sequence(x, batch_first=True, padding_value=0)
    pos = pad_sequence(pos, batch_first=True, padding_value=0)
    y = torch.tensor([item['scores']['neglog_aff'] for item in dataset])
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    torch.save([x, idx, pos, y], output_dir / f'pdb_{mode}_{split}.pt')
    print(f'Loading {len(x)} data samples with {len(dict)} atom types. \n Atom types are {dict}')
    return dict


def load_final(path='../../../../split-by-sequence-identity-*/data/', split='30', output_dir='../data/pdb'):
    vocabulary = {}
    for mode in ('train', 'val', 'test'):
        pdb_loader(vocabulary, mode=mode, split=split, path=path, output_dir=output_dir)


def load_60_identity(split_path='../../pdbbind/metadata/identity60_split.json',
                     aff_path='../../pdbbind/metadata/affinities.json', pdb_path='../../pdbbind/pdb_files/'):
    f = open(split_path)
    data = json.load(f)
    train_index, val_index, test_index = data['train'], data['valid'], data['test']
    f.close()
    f = open(aff_path)
    aff = json.load(f)
    f.close()

    d = dict()

    for mode, index in zip(("train", "val", "test"), (train_index, val_index, test_index)):
        x, pos, idx, y = [], [], [], []
        for i in index:
            x_tmp, pos_tmp = [], []
            try:
                with open(pdb_path + i + f'/{i}_pocket.pdb') as f:
                    for line in f.readlines()[3:]:
                        if not line.startswith('ATOM'):
                            break
                        try:
                            pos_tmp.append([float(xzy.split()[0]) for xzy in [line[30:38], line[38:46], line[46:54]]])
                        except:
                            print(f'Error occur for {i}: e.g., {[line[30:38], line[38:46], line[46:54]]}')
                            break
                        atom = line[-2]
                        if atom in d.keys():
                            x_tmp.append(d[atom])
                        else:
                            d[atom] = len(d) + 1
                            x_tmp.append(len(d))
            except FileNotFoundError:
                print(f'Warining: {i} not in the dataset.')
                continue

            with open(pdb_path + i + f'/{i}_ligand.sdf') as f:
                for line in f.readlines()[4:]:
                    if len(line) < 45:
                        break
                    tmp = line.split()
                    pos_tmp.append([float(xzy) for xzy in tmp[:3]])
                    if tmp[3] in d.keys():
                        x_tmp.append(d[tmp[3]])
                    else:
                        d[tmp[3]] = len(d) + 1
                        x_tmp.append(len(d))
            x.append(torch.tensor(x_tmp))
            pos.append(torch.tensor(pos_tmp))
            y.append(aff[i])

        x = pad_sequence(x, batch_first=True, padding_value=0)
        pos = pad_sequence(pos, batch_first=True, padding_value=0)
        y = torch.tensor(y)
        output_dir = Path('../data/pdb')
        output_dir.mkdir(parents=True, exist_ok=True)
        torch.save([x, idx, pos, y], output_dir / f'pdb_{mode}_60.pt')
        print(f'Loading {len(x)} data samples with {len(d)} atom types. \n Atom types are {d}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Prepare ATOM3D LBA splits.')
    parser.add_argument('--input-dir', required=True, help='Directory containing the split LMDBs.')
    parser.add_argument('--output-dir', default='data/pdb')
    parser.add_argument('--split', choices=['30', '60'], default='30')
    args = parser.parse_args()
    load_final(path=args.input_dir, split=args.split, output_dir=args.output_dir)

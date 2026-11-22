from pathlib import Path

import torch
import numpy as np
import torch.nn.functional as F
from torch.nn.utils.rnn import pad_sequence

atom_dict = {'C': 6, 'H': 1, 'O': 8, 'N': 7, 'S': 9, 'P': 10, 'F': 11, 'I': 12, 'B': 13}


class PDBMDDataset():
    def __init__(self, backprop, pdb_list, prompt=None, data_dir='data/md/', max_len=10000, noise=True, echo=False, split_ratio=0.9):
        self.backprop = backprop
        self.noise = noise
        x_0_, x_t_ = [], []
        feats_, prompt_ = [], []
        if prompt is None:
            prompt = [1]
        if not prompt or any(offset <= 0 for offset in prompt):
            raise ValueError('Frame offsets must be positive integers.')
        if max_len <= 0:
            raise ValueError('max_len must be positive.')

        # 遍历所有的pdb
        for file in pdb_list:
            if not file.endswith('.npy'):
                if echo: print(f'Warning: data {file} is not a numpy file.')
                continue
            d = np.load(Path(data_dir) / file, allow_pickle=True).item()

            # x.shape: (T,N,3)
            x = torch.as_tensor(d['R'], dtype=torch.float32)
            if x.ndim != 3 or x.size(-1) != 3 or x.size(1) == 0 or len(d['z']) < x.size(1):
                raise ValueError(f'{file}: expected R with shape (frames, atoms, 3) and one symbol per atom')
            x = x[:, :max_len]
            z = torch.tensor([atom_dict[symbol] for symbol in d['z'][:x.size(1)]])
            n_times = len(x)
            if backprop:
                x = x[:int(split_ratio * n_times)]
            else:
                x = x[int(split_ratio * n_times):]

            # 遍历所有的prompt
            for pt in prompt:
                if pt >= len(x):
                    continue
                x_0, x_t = x[:-pt], x[pt:]
                x_0_.append(x_0)
                x_t_.append(x_t)
                feats_ += [z] * len(x_0)
                prompt_ += [pt] * len(x_0)
        if not feats_:
            self.mole_idx = torch.empty((0, 0), dtype=torch.long)
            self.prompt = torch.empty((0, 1), dtype=torch.long)
            self.x_0 = self.x_t = torch.empty((0, 0, 3))
            return
        self.mole_idx = pad_sequence(feats_, batch_first=True, padding_value=0)[:, :max_len]
        self.prompt = torch.tensor(prompt_).unsqueeze(-1)
        for i in range(len(x_0_)):
            x_0_[i] = F.pad(x_0_[i], (0, 0, 0, self.mole_idx.shape[-1] - x_0_[i].shape[1]))
            x_t_[i] = F.pad(x_t_[i], (0, 0, 0, self.mole_idx.shape[-1] - x_t_[i].shape[1]))
        self.x_0, self.x_t = torch.cat(x_0_)[:, :max_len], torch.cat(x_t_)[:, :max_len]
        if echo: print('Got {:d} proteins!'.format(len(x_0_)))

    def __getitem__(self, i):
        # noise均值为0，标准差为0.1
        if self.backprop and self.noise:
            noise = torch.randn_like(self.x_0[i]) / 10
            noise = noise.masked_fill(self.mole_idx[i, :, None] == 0, 0)
            return self.x_0[i] + noise, self.mole_idx[i], self.x_t[i], self.prompt[i]

        # 返初始时刻的坐标，原子种类，结束时刻的坐标
        return self.x_0[i], self.mole_idx[i], self.x_t[i], self.prompt[i]

    def __len__(self):
        return len(self.x_0)
#





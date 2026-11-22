from math import isfinite
from pathlib import Path
from time import strftime

import torch
import torch.nn.functional as F
from torch import nn, optim

from data.dataset import PDBMDDataset
from egnn import Classifier, EGNN_Network
from utils.utils import Logger, parse_args, select_device, set_seed


def train(args, model, optimizer, scaler, backprop=True, n_samples=16, max_samples=64, echo=False):
    model.train(backprop)
    device = next(model.parameters()).device
    encoder = model[0] if args.ordering else model
    offsets = [int(value) for value in args.prompt.split(',')]
    files = sorted(path.name for path in Path(args.data_dir).glob('*.npy') if path.is_file())[:max_samples]
    if not files:
        raise ValueError(f'No .npy trajectory files found in {args.data_dir}')

    losses, n_frames = 0.0, 0
    for start in range(0, len(files), n_samples):
        dataset = PDBMDDataset(
            backprop=backprop, pdb_list=files[start:start + n_samples], data_dir=args.data_dir,
            max_len=args.max_len, noise=args.noise, prompt=offsets, split_ratio=args.split_ratio,
        )
        loader = torch.utils.data.DataLoader(dataset, batch_size=args.bs, shuffle=backprop and len(dataset) > 0)
        for data in loader:
            loc, charges, loc_end, lag = [value.to(device) for value in data]
            mask = charges.ne(0)
            prompt = None
            if len(offsets) > 1:
                choices = lag.new_tensor(offsets)
                prompt = lag.eq(choices).long().argmax(dim=-1, keepdim=True)

            with torch.set_grad_enabled(backprop), torch.autocast(device_type=device.type, enabled=device.type == 'cuda'):
                loc_pred, feats = encoder(charges, loc, prompt=prompt, mask=mask)
                error = (loc_pred.float() - loc_end).square().masked_fill(~mask.unsqueeze(-1), 0)
                loss = (error.sum(dim=(1, 2)) / (3 * mask.sum(dim=1))).mean()
                if args.ordering:
                    _, end_feats = encoder(charges, loc_end, prompt=prompt, mask=mask)
                    count = mask.sum(dim=1, keepdim=True)
                    start_repr = feats.masked_fill(~mask.unsqueeze(-1), 0).sum(dim=1) / count
                    end_repr = end_feats.masked_fill(~mask.unsqueeze(-1), 0).sum(dim=1) / count
                    order = model[1](start_repr.float(), end_repr.float())
                    reverse = model[1](end_repr.float(), start_repr.float())
            if args.ordering:
                with torch.set_grad_enabled(backprop):
                    loss = loss + (
                        F.binary_cross_entropy(order.float(), torch.ones_like(order, dtype=torch.float32))
                        + F.binary_cross_entropy(reverse.float(), torch.zeros_like(reverse, dtype=torch.float32))
                    ) / 2
            if backprop:
                optimizer.zero_grad()
                scaler.scale(loss).backward()
                scaler.step(optimizer)
                scaler.update()
            losses += loss.item() * len(loc)
            n_frames += len(loc)

    if not n_frames:
        split = 'training' if backprop else 'validation'
        raise ValueError(f'No frame pairs in the {split} split. Check --prompt and --split_ratio.')
    if echo and backprop:
        print(f'Finished {n_frames} frame pairs.')
    return losses / n_frames, n_frames


def main():
    args = parse_args('pretrain')
    offsets = [int(value) for value in args.prompt.split(',')]
    if min(offsets) <= 0 or len(set(offsets)) != len(offsets):
        raise ValueError('--prompt must contain distinct positive frame offsets')

    device, parallel = select_device(args.gpu)
    set_seed(args.seed)
    folder = Path(args.save_path) / strftime('pretrain_%Y-%m-%d_%H-%M-%S')
    folder.mkdir(parents=True)
    log = Logger(folder, 'loss.log')
    encoder = EGNN_Network(
        num_tokens=args.tokens, dim=args.dim, depth=args.depth, num_nearest_neighbors=args.num_nearest,
        dropout=args.dropout, global_linear_attn_every=1, norm_coors=True, coor_weights_clamp_value=2.,
        num_prompt=len(offsets), aggregate=False,
    ).to(device)
    model = nn.DataParallel(encoder) if parallel else encoder
    if args.ordering:
        classifier = Classifier(args.dim).to(device)
        model = nn.ModuleList([model, nn.DataParallel(classifier) if parallel else classifier])
    optimizer = optim.Adam(model.parameters(), lr=args.lr, weight_decay=args.weight_decay)
    scheduler = optim.lr_scheduler.ReduceLROnPlateau(optimizer, 'min', factor=0.6, patience=5, min_lr=args.min_lr)
    scaler = torch.amp.GradScaler('cuda', enabled=device.type == 'cuda')

    best_loss = float('inf')
    for epoch in range(1, args.epochs + 1):
        train_loss, train_size = train(args, model, optimizer, scaler, max_samples=args.max_sample)
        val_loss, val_size = train(args, model, optimizer, scaler, backprop=False, max_samples=args.max_sample)
        if not (isfinite(train_loss) and isfinite(val_loss)):
            raise ValueError(f'Non-finite pretraining loss at epoch {epoch}')
        log.logger.info(f'Epoch {epoch} | Train loss {train_loss:.6f} ({train_size} pairs) | '
                        f'Validation loss {val_loss:.6f} ({val_size} pairs)')
        if val_loss < best_loss:
            best_loss = val_loss
            prefix = f'pre_n{args.max_sample}' if args.max_sample < 60 else 'pre'
            path = folder / f'{prefix}_e{epoch}.pt'
            checkpoint = {'model': encoder.state_dict(), 'epochs': epoch}
            if args.ordering:
                checkpoint['classifier'] = classifier.state_dict()
            torch.save(checkpoint, path)
            log.logger.info(f'Saved {path}')
        scheduler.step(val_loss)


if __name__ == '__main__':
    main()

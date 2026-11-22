import copy
import math
from pathlib import Path
from time import strftime, time

import torch
from scipy import stats
from sklearn.metrics import average_precision_score, roc_auc_score
from torch import nn, optim
from torch.nn.functional import mse_loss
from torch.utils.data import DataLoader, TensorDataset

from egnn import EGNN_Network, predictor
from utils.utils import Logger, parse_args, select_device, set_seed


def run_eval(args, model, loader, y_gt):
    model.eval()
    device = next(model.parameters()).device
    predictions = []
    with torch.no_grad():
        for x, pos, _ in loader:
            x = x.to(device=device, dtype=torch.long)
            pos = pos.to(device=device, dtype=torch.float32)
            out = model(x, pos, mask=x.ne(0))[1][..., 0]
            predictions.append(out.cpu())
    y_pred = torch.cat(predictions)
    y_gt = y_gt.reshape(-1).cpu()
    if args.data == 'lba':
        spearman = stats.spearmanr(y_pred.numpy(), y_gt.numpy())[0]
        pearson = stats.pearsonr(y_pred.numpy(), y_gt.numpy())[0]
        return spearman, pearson, mse_loss(y_pred, y_gt.float()).item()
    return roc_auc_score(y_gt.numpy(), y_pred.numpy()), average_precision_score(y_gt.numpy(), y_pred.numpy()), 0


def load_split(args, split):
    if args.data == 'lba':
        prefix = 'docking' if split == 'test' and args.unknown else 'pdb'
        filename = f'{prefix}_{split}_{args.split}.pt'
    else:
        filename = f'lep_{split}.pt'
    path = Path(args.data_dir) / filename
    if not path.is_file():
        raise FileNotFoundError(f'Missing {split} dataset: {path}. See the README for the expected files.')
    tensors = torch.load(path, map_location='cpu', weights_only=True)
    if args.data == 'lba':
        x, _, pos, y = tensors
    else:
        x, pos, y = tensors
    if x.ndim != 2 or pos.shape != (*x.shape, 3) or len(x) == 0 or y.numel() != len(x):
        raise ValueError(f'{path}: expected nonempty token [B,N], position [B,N,3], and label [B] tensors.')
    return TensorDataset(x, pos, y.reshape(-1))


def main():
    args = parse_args('downstream')
    device, parallel = select_device(args.gpu)
    set_seed(args.seed)
    save_dir = Path(args.save_path)
    log_dir = save_dir / (f'pdbbind_{args.split}' if args.data == 'lba' else 'lep')
    log = Logger(log_dir, strftime('%Y-%m-%d_%H-%M-%S.log'))

    train_data, val_data, test_data = (load_split(args, split) for split in ('train', 'val', 'test'))
    train_loader = DataLoader(train_data, batch_size=args.bs, shuffle=True)
    val_loader = DataLoader(val_data, batch_size=args.bs * 2)
    test_loader = DataLoader(test_data, batch_size=args.bs * 2)
    y_val, y_test = val_data.tensors[-1], test_data.tensors[-1]

    model = EGNN_Network(
        num_tokens=args.tokens, dim=args.dim, depth=args.depth, num_nearest_neighbors=args.num_nearest,
        dropout=args.dropout, global_linear_attn_every=1, norm_coors=True, coor_weights_clamp_value=2.,
        aggregate=False,
    )
    checkpoint_name = 'no_pre'
    if args.pretrain:
        checkpoint_path = Path(args.pretrain)
        if not checkpoint_path.is_file():
            checkpoint_path = save_dir / checkpoint_path
        checkpoint = torch.load(checkpoint_path, map_location='cpu', weights_only=True)
        state = checkpoint['model'].copy()
        state.pop('prompt_embed.weight', None)
        model.load_state_dict(state)
        checkpoint_name = checkpoint_path.stem
        if args.linear_probe:
            model.requires_grad_(False)
    model.aggregate = True
    model.out = predictor(args.dim)
    model.to(device)
    encoder = model
    if parallel:
        model = nn.DataParallel(model)

    regression = args.data == 'lba'
    criterion = nn.MSELoss() if regression else nn.BCEWithLogitsLoss()
    best_metric = math.inf if regression else -math.inf
    optimizer = optim.Adam(
        (param for param in model.parameters() if param.requires_grad),
        lr=args.lr, weight_decay=args.weight_decay,
    )
    scheduler = optim.lr_scheduler.ReduceLROnPlateau(
        optimizer, 'min' if regression else 'max', factor=0.6, patience=10, min_lr=args.min_lr,
    )
    log.logger.info(f'Task {args.data} | Train {len(train_data)} | Validation {len(val_data)} | Test {len(test_data)}')
    t0 = time()
    best_state = None
    for epoch in range(1, args.epochs + 1):
        model.train()
        if args.linear_probe:
            encoder.eval()
            encoder.out.train()
        loss_sum = 0.0
        for x, pos, y in train_loader:
            x = x.to(device=device, dtype=torch.long)
            pos = pos.to(device=device, dtype=torch.float32)
            y = y.to(device=device, dtype=torch.float32)
            optimizer.zero_grad()
            out = model(x, pos, mask=x.ne(0))[1][..., 0]
            loss = criterion(out, y)
            loss.backward()
            optimizer.step()
            loss_sum += loss.item() * len(y)

        first, second, mse = run_eval(args, model, val_loader, y_val)
        metric = mse if regression else first
        if not math.isfinite(metric):
            raise ValueError(f'Non-finite validation metric at epoch {epoch}')
        validation = (
            f'RMSE {mse ** 0.5:.3f} | Pearson {second:.3f} | Spearman {first:.3f}'
            if regression else f'AUROC {first:.3f} | AUPRC {second:.3f}'
        )
        log.logger.info(f'Epoch {epoch} | Loss {loss_sum / len(train_data):.6f} | {validation}')
        scheduler.step(metric)
        if (regression and metric < best_metric) or (not regression and metric > best_metric):
            best_metric, best_epoch = metric, epoch
            best_state = copy.deepcopy(encoder.state_dict())
        if epoch - best_epoch >= 50:
            log.logger.info('Early stopping after 50 epochs without improvement.')
            break

    encoder.load_state_dict(best_state)
    first, second, mse = run_eval(args, model, test_loader, y_test)
    suffix = 'Linear' if args.linear_probe else 'False'
    prefix = f'PDB_{args.split}' if regression else 'LEP'
    path = save_dir / f'{prefix}_{checkpoint_name}_{suffix}.pt'
    torch.save({'model': best_state, 'epochs': best_epoch}, path)
    metrics = (
        f'RMSE {mse ** 0.5:.3f} | Pearson {second:.3f} | Spearman {first:.3f}'
        if regression else f'AUROC {first:.3f} | AUPRC {second:.3f}'
    )
    log.logger.info(f'Saved {path} | Best epoch {best_epoch} | Test {metrics} | Time {time() - t0:.1f}s')


if __name__ == '__main__':
    main()

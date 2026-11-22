import torch

import os
import logging
import argparse
import random
import numpy as np


def parse_bool(value):
    value = value.lower()
    if value in ('true', '1'):
        return True
    if value in ('false', '0'):
        return False
    raise argparse.ArgumentTypeError('expected true or false')


def parse_args(stage=None):
    parser = argparse.ArgumentParser(description="Train or fine-tune ProtMD.")
    # set pretraining hyper-parameters
    parser.add_argument('--ordering', type=parse_bool, nargs="?", const=True, default=False, help='Whether to use the snapshot ordering task.')
    parser.add_argument('--noise', type=parse_bool, nargs="?", const=True, default=True, help='Whether to add noise during pretraining.')
    parser.add_argument('--prompt', type=str, default='1', help='Comma-separated positive frame offsets.')
    parser.add_argument('--max_sample', type=int, default=64, help='The default number of pre-train samples.')

    # set fine-tune hyper-parameters
    parser.add_argument('--data', type=str, default='lba', choices=['lba', 'lep'])
    parser.add_argument('--unknown', type=parse_bool, nargs="?", const=True, default=True, help='Whether to use docking structures.')
    parser.add_argument('--pretrain', type=str, default='', help='Whether to load the pretrained model weights.')
    parser.add_argument('--linear_probe', default=False, action='store_true')

    # set model hyper-parameters
    parser.add_argument('--num_nearest', type=int, default=32, help='The default number of nearest neighbors.')
    parser.add_argument('--tokens', type=int, default=100, help='The default number of atom classes.')
    parser.add_argument('--depth', type=int, default=6, help='Number of stacked layers.')
    parser.add_argument('--dim', type=int, default=128, help='Dimension of features.')
    parser.add_argument('--dropout', type=float, default=0.15, help='Dropout rate.')
    parser.add_argument('--max_len', type=int, default=10000, help='Maximum number of nodes for the input graph.')

    # set training details
    parser.add_argument('--seed', type=int, default=1234)
    parser.add_argument('--split_ratio', type=float, default=0.9)
    parser.add_argument('--epochs', type=int, default=None, help='Number of epochs.')
    parser.add_argument('--bs', type=int, default=None, help='Batch size.')
    parser.add_argument('--lr', type=float, default=None, help='Learning rate.')
    parser.add_argument('--min_lr', type=float, default=5e-7, help='The minimum learning rate.')
    parser.add_argument('--weight_decay', type=float, default=1e-10, metavar='N', help='Timing experiment')

    # set training environment
    parser.add_argument('--split', type=str, default='30', choices=['30', '60'])
    parser.add_argument('--data_dir', type=str, default='data/md/' if stage != 'downstream' else 'data/pdb/', help='Dataset directory.')
    parser.add_argument('--gpu', type=str, default='0', help='Comma-separated CUDA device IDs, or cpu.')
    parser.add_argument('--save_path', default='save/', help='Path to save the model and the logger.')

    args = parser.parse_args()
    gpu_ids = args.gpu.split(',') if args.gpu != 'cpu' else []
    if any(not gpu.isdecimal() for gpu in gpu_ids) or len(set(gpu_ids)) != len(gpu_ids):
        parser.error('--gpu must be cpu or a comma-separated list of distinct CUDA device IDs')
    devices = max(1, len(gpu_ids))
    default_epochs, default_bs, default_lr = {
        'pretrain': (200, 16 * devices, 1e-4 / devices),
        'downstream': (1000, 4 * devices, 1e-4 * devices),
        None: (1000, 32, 5e-4),
    }[stage]
    for name, default in [('epochs', default_epochs), ('bs', default_bs), ('lr', default_lr)]:
        if getattr(args, name) is None:
            setattr(args, name, default)
        if getattr(args, name) <= 0:
            parser.error(f'--{name} must be positive')
    if not 0 < args.split_ratio < 1:
        parser.error('--split_ratio must be between zero and one')
    if min(args.max_len, args.max_sample) <= 0:
        parser.error('--max_len and --max_sample must be positive')
    if stage == 'downstream' and args.linear_probe and not args.pretrain:
        parser.error('--linear_probe requires --pretrain')
    if args.num_nearest > args.max_len: args.num_nearest = args.max_len
    return args


def select_device(gpu):
    if gpu == 'cpu':
        return torch.device('cpu'), False
    os.environ['CUDA_VISIBLE_DEVICES'] = gpu
    if not torch.cuda.is_available():
        raise RuntimeError('CUDA is unavailable. Use --gpu cpu to run on CPU.')
    return torch.device('cuda'), ',' in gpu


def set_seed(s):
    torch.manual_seed(s)
    torch.cuda.manual_seed(s)
    torch.cuda.manual_seed_all(s)
    np.random.seed(s)
    random.seed(s)

    # keep cudnn stable for CNN，https://learnopencv.com/ensuring-training-reproducibility-in-pytorch/
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False


class Logger(object):
    level_relations = {'debug': logging.DEBUG, 'info': logging.INFO, 'warning': logging.WARNING,
                       'error': logging.ERROR, 'crit': logging.CRITICAL}  # 日志级别关系映射

    def __init__(self, path, filename, level='info'):
        os.makedirs(path, exist_ok=True)
        log_path = os.path.join(path, filename)
        self.logger = logging.getLogger(log_path)
        self.logger.setLevel(self.level_relations.get(level))

        sh = logging.StreamHandler()
        self.logger.addHandler(sh)

        th = logging.FileHandler(log_path, encoding='utf-8')
        self.logger.addHandler(th)


if __name__ == '__main__':
    print()

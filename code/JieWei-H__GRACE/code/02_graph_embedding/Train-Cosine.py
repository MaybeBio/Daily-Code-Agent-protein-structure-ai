import os
import csv
import sys
import argparse
import time
import math
import warnings
import torch
import torch.distributed as dist
from torch import optim, nn
import torch.nn.functional as F
from AttentionPooling import process_esm2_directory
from contextlib import nullcontext
from tqdm import tqdm
from GAT import GATConfig, GAT_Model
from GraphBuilder import PPIGraphBuilder
from PPIData import PPIDataset, PPIDataLoader
import pickle
import numpy as np
import pandas as pd
from Annotation import GraphAnnotationCompleter
from sklearn.metrics import f1_score, precision_score, recall_score, accuracy_score
import random
import gc
from torch.utils.data.distributed import DistributedSampler
from torch.nn.parallel import DistributedDataParallel as DDP
from functools import partial

warnings.filterwarnings('ignore')
  
# 打印日志，只打印主进程（rank=0）的日志。
def Logger(content):
    if not ddp or dist.get_rank() == 0:
        print(content)

# 学习率调整，余弦退火学习率调度函数
def get_lr(current_step, total_steps, lr):
    return lr / 10 + 0.5 * lr * (1 + math.cos(math.pi * current_step / total_steps))

def train_epoch(model, graph_builder, dataloader, optimizer, device, epoch):
    """训练一个epoch"""
    model.train()
    total_loss = 0
    # total_ppi_correct = 0
    total_ppi_samples = 0
    
    start_time = time.time()
    
    # 进度条仅在主进程显示
    progress_bar = tqdm(dataloader, desc=f"Epoch {epoch+1}", disable=ddp and dist.get_rank() != 0)
    for step, batch in enumerate(progress_bar):
        
        # if step >= 200:
        #     break
        
        iter_per_epoch = len(dataloader)
        # 动态学习率调整
        lr = get_lr(epoch * iter_per_epoch + step, args.epochs * iter_per_epoch, args.learning_rate)
        for param_group in optimizer.param_groups:
            param_group['lr'] = lr
        
        # 获取节点索引和标签
        node_indices = batch['node_indices']
        ppi_labels = batch['labels'].to(device)
        
        # 获取节点特征
        node_features = [graph_builder.node_features[i].to(device) for i in node_indices]
        
        # 获取子图邻接矩阵
        subgraph_adj = graph_builder.adj[node_indices, :][:, node_indices].to(device)
        
        # 前向传播
        optimizer.zero_grad()
        
        # 获取节点对在子图中的索引
        node1_sub_idx = []
        node2_sub_idx = []
        for node1, node2 in batch['node_pairs']:
            idx1 = graph_builder.get_node_index(node1)
            idx2 = graph_builder.get_node_index(node2)
            
            # 在子图中的索引
            sub_idx1 = node_indices.index(idx1)
            sub_idx2 = node_indices.index(idx2)
            
            node1_sub_idx.append(sub_idx1)
            node2_sub_idx.append(sub_idx2)
        
        # 转换为Tensor
        node1_sub_idx = torch.tensor(node1_sub_idx, device=device)
        node2_sub_idx = torch.tensor(node2_sub_idx, device=device)
        
        # 多任务前向传播
        outputs, node_embeddings = model(node_features, subgraph_adj, node1_sub_idx, node2_sub_idx)
        
        # 准备多任务目标
        # targets = {'ppi': ppi_labels.unsqueeze(1)}
        
        # criterion = nn.BCELoss()
        
        # 计算多任务损失
        # loss = criterion(outputs['ppi'], targets['ppi'])
        
        loss = compute_distance_loss(
            embeddings=node_embeddings,
            src_indices=node1_sub_idx,
            tgt_indices=node2_sub_idx,
            labels=ppi_labels,
            Q=args.Q,
            model_params=model.parameters()
        )
        
        # 反向传播
        loss.backward()
        optimizer.step()
        
        # 计算PPI准确率
        ppi_predictions = outputs['ppi'] > 0.5
        # ppi_correct = (ppi_predictions == targets['ppi'].byte()).sum().item()
        
        # 更新统计信息
        batch_samples = len(ppi_labels)
        total_loss += loss.item() * batch_samples
        # total_ppi_correct += ppi_correct
        total_ppi_samples += batch_samples
        
        # 日志记录与监控
        if step % args.log_interval == 0:
            # 计算各种指标
            avg_loss = total_loss / total_ppi_samples if total_ppi_samples > 0 else 0
            # ppi_accuracy = total_ppi_correct / total_ppi_samples if total_ppi_samples > 0 else 0
            
            # 计算F1分数、精确率和召回率（注释掉）
            # with torch.no_grad():
            #     # 获取预测概率
            #     ppi_probs = outputs['ppi']
            #     
            #     # 计算精确率和召回率
            #     true_positives = ((ppi_predictions == 1) & (targets['ppi'].byte() == 1)).sum().item()
            #     false_positives = ((ppi_predictions == 1) & (targets['ppi'].byte() == 0)).sum().item()
            #     false_negatives = ((ppi_predictions == 0) & (targets['ppi'].byte() == 1)).sum().item()
            #     
            #     precision = true_positives / (true_positives + false_positives) if (true_positives + false_positives) > 0 else 0
            #     recall = true_positives / (true_positives + false_negatives) if (true_positives + false_negatives) > 0 else 0
            #     f1 = 2 * (precision * recall) / (precision + recall) if (precision + recall) > 0 else 0
   
            # 计算训练时间
            spend_time = time.time() - start_time
            epoch_time = spend_time / (step + 1) * iter_per_epoch / 60  # 预计完成整个epoch需要的分钟数
            
            # 获取当前学习率
            current_lr = optimizer.param_groups[0]['lr']
            
            # 打印日志
            log_msg = (
                f'Epoch:[{epoch+1}/{args.epochs}]({step}/{iter_per_epoch}) \n'
                # f'loss:{avg_loss:.4f} PPI_Acc:{ppi_accuracy:.4f} F1:{f1:.4f} P:{precision:.4f} R:{recall:.4f} \n'
                f'loss:{avg_loss:.4f} lr:{current_lr:.8f} Time:{epoch_time:.1f}min'
            )
            Logger(log_msg)
            
            # 记录到CSV文件（仅主进程）
            if not ddp or dist.get_rank() == 0:
                os.makedirs(args.log_dir, exist_ok=True)
                csv_path = os.path.join(args.log_dir, "training_logs.csv")
                with open(csv_path, 'a', newline='') as f:
                    writer = csv.writer(f)
                    writer.writerow([
                        epoch + 1,                          # Epoch
                        step,                               # Step
                        avg_loss,                           # Loss
                        # ppi_accuracy,                       # PPI Accuracy
                        # f1,                                 # F1 Score
                        # precision,                          # Precision
                        # recall,                             # Recall
                        current_lr,                         # Learning Rate
                    ])
            
            # 打印节点覆盖情况（仅当 dataloader 支持时，如非 DDP 模式）
            if hasattr(dataloader, 'get_covered_nodes'):
                covered_nodes = dataloader.get_covered_nodes()
                Logger(f"Batch {step}: Covered {len(covered_nodes)}/{graph_builder.num_nodes} nodes")
        
        # 模型保存（仅主进程）
        if (step + 1) % args.save_interval == 0:
            model.eval()  # 切换评估模式
            
            # 生成检查点文件名
            ckp = f'{args.save_dir}/model_epoch_{epoch}_step_{step}.pth'
            
            # 保存检查点
            if not ddp or dist.get_rank() == 0:
                torch.save({
                    'epoch': epoch,
                    'step': step,
                    'model_state_dict': model.state_dict(),
                    'optimizer_state_dict': optimizer.state_dict(),
                    'loss': avg_loss,
                }, ckp)
                Logger(f"Checkpoint saved: {ckp}")
            model.train()  # 恢复训练模式
    
    # 更新进度条
    avg_loss = total_loss / total_ppi_samples if total_ppi_samples > 0 else 0
    # ppi_accuracy = total_ppi_correct / total_ppi_samples if total_ppi_samples > 0 else 0
    
    progress_bar.set_postfix({
        'Loss': f'{avg_loss:.4f}',
        # 'PPI_Acc': f'{ppi_accuracy:.4f}'
    })
    
    # 最终模型保存（在每个epoch结束时，仅主进程）
    model.eval()
    final_ckp = f'{args.save_dir}/model_epoch_{epoch}_final.pth'
    if not ddp or dist.get_rank() == 0:
        torch.save({
            'epoch': epoch,
            'model_state_dict': model.state_dict(),
            'optimizer_state_dict': optimizer.state_dict(),
            'loss': avg_loss,
        }, final_ckp)
        Logger(f"Final model saved: {final_ckp}")
    model.train()

def init_model(config, graph_builder):
    model = GAT_Model(config, graph_builder)
    
    Logger(f'模型总参数量：{sum(p.numel() for p in model.parameters() if p.requires_grad) / 1e6:.3f} M')
    return model

def init_distributed_mode():
    if not ddp: return
    global ddp_local_rank, DEVICE

    dist.init_process_group(backend="nccl")
    ddp_rank = int(os.environ["RANK"])
    ddp_local_rank = int(os.environ["LOCAL_RANK"])
    ddp_world_size = int(os.environ["WORLD_SIZE"])
    DEVICE = f"cuda:{ddp_local_rank}"
    torch.cuda.set_device(DEVICE)

def compute_distance_loss(embeddings, src_indices, tgt_indices, labels, Q=1.0, model_params=None):
    """
    计算基于欧氏距离的 batch 级损失：正样本对距离近，负样本对距离远。

    Args:
        embeddings (torch.Tensor): 当前 batch 所有节点的嵌入，形状 [num_nodes, emb_dim]
        src_indices (torch.Tensor): 源节点索引，形状 [num_pairs]
        tgt_indices (torch.Tensor): 目标节点索引，形状 [num_pairs]
        labels (torch.Tensor): 标签（1 正，0 负），形状 [num_pairs]
        Q (float): 负样本损失权重
        model_params (iterable): 模型参数列表，用于 L2 惩罚（若 lambd>0 则必须提供）

    Returns:
        torch.Tensor: 标量损失
    """
    eps = 1e-8
    device = embeddings.device

    # 分离正负样本对
    pos_mask = labels == 1
    neg_mask = labels == 0

    if pos_mask.sum() == 0 or neg_mask.sum() == 0:
        # 如果 batch 中缺少正或负样本，则损失为 0（实际训练中应避免）
        return torch.tensor(0.0, device=device)

    # 计算所有样本对的欧氏距离
    src_emb = embeddings[src_indices]
    tgt_emb = embeddings[tgt_indices]
    distances = torch.norm(src_emb - tgt_emb, dim=1)  # [num_pairs]

    # 正样本损失：log(sigmoid(-dist))，取负号
    pos_dists = distances[pos_mask]
    pos_loss = -torch.mean(torch.log(torch.sigmoid(-pos_dists) + eps))

    # 负样本损失：Q * log(sigmoid(dist))，取负号
    neg_dists = distances[neg_mask]
    neg_loss = -Q * torch.mean(torch.log(torch.sigmoid(neg_dists) + eps))

    loss = pos_loss + neg_loss

    return loss

# 自定义 collate_fn，用于 DDP 模式下替代 PPIDataLoader
def ddp_collate_fn(batch, graph_builder):
    """
    batch: list of samples, each sample is expected to be a tuple (node1_id, node2_id, label)
    Returns a dictionary compatible with train_epoch.
    """
    node_pairs = []
    labels = []
    all_node_ids = set()
    for item in batch:
        # 假设每个样本是 (node1, node2, label)
        node1, node2, label = item
        node_pairs.append((node1, node2))
        labels.append(label)
        all_node_ids.add(node1)
        all_node_ids.add(node2)
    
    # 将节点ID转换为全局索引并去重
    node_indices = [graph_builder.get_node_index(nid) for nid in all_node_ids]
    
    return {
        'node_indices': node_indices,
        'node_pairs': node_pairs,
        'labels': torch.tensor(labels, dtype=torch.float32)
    }

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="GNNTraining")
    parser.add_argument("--out_dir", type=str, default="./out-2")
    parser.add_argument("--epochs", type=int, default=10)
    parser.add_argument("--batch_size", type=int, default=64)
    parser.add_argument("--learning_rate", type=float, default=1e-4)
    parser.add_argument("--device", type=str, default="cuda:0" if torch.cuda.is_available() else "cpu")
    parser.add_argument("--dtype", type=str, default="bfloat16")
    parser.add_argument("--num_workers", type=int, default=1)
    parser.add_argument("--ddp", action="store_true")
    parser.add_argument("--accumulation_steps", type=int, default=8)
    parser.add_argument("--grad_clip", type=float, default=1.0)
    parser.add_argument("--warmup_iters", type=int, default=0)
    parser.add_argument("--log_interval", type=int, default=100)
    parser.add_argument("--save_interval", type=int, default=1000)
    parser.add_argument('--local_rank', type=int, default=-1)
    parser.add_argument('--input_size', default=1280, type=int)
    parser.add_argument('--out_size', default=512, type=int)
    parser.add_argument('--num_hidden_layers', default=4, type=int)
    parser.add_argument('--log_dir',type=str, default="./log-2")
    parser.add_argument('--node_dir', type=str, default="../../ESM/")
    parser.add_argument("--Q", type=float, default=1.0)
    parser.add_argument('--ppi_file', type=str, default="../GraphData/final_ppi_network.csv")
    parser.add_argument('--neg_samples', type=int, default=2, help="Number of negative samples per positive sample")
    parser.add_argument('--track_metrics', action='store_true', help="Track metrics for biological annotation tasks")
    args = parser.parse_args()

    # 配置模型
    GAT_config = GATConfig(
        out_feats=args.out_size, 
        n_layers=args.num_hidden_layers, 
        in_feats=args.input_size
    )
    
    args.save_dir = os.path.join(args.out_dir)
    os.makedirs(args.save_dir, exist_ok=True)
    os.makedirs(args.out_dir, exist_ok=True)
    device_type = "cuda" if "cuda" in args.device else "cpu"

    ctx = nullcontext() if device_type == "cpu" else torch.cuda.amp.autocast()

    ddp = int(os.environ.get("RANK", -1)) != -1  # is this a ddp run?
    ddp_local_rank, DEVICE = 0, "cuda:0"

    # 随机种子（所有进程保持一致，保证模型初始化相同）
    base_seed = 20030201
    torch.manual_seed(base_seed)
    torch.cuda.manual_seed(base_seed)
    
    # 分布式设置
    if ddp:
        init_distributed_mode()
        args.device = torch.device(DEVICE)
        rank = dist.get_rank()
        # 注意：每个进程的种子应相同（否则模型初始化会不一致），但数据打乱由sampler控制
        torch.manual_seed(base_seed)
        torch.cuda.manual_seed(base_seed)

    # 检查文件是否存在
    if os.path.exists("graph_builder.pt"):
        # 如果文件存在，直接加载
        graph_builder = torch.load("graph_builder.pt")
    else:
        # 如果文件不存在，初始化并构建
        graph_builder = PPIGraphBuilder(args.node_dir, args.ppi_file)
        torch.save(graph_builder, "graph_builder.pt")
    
    ################################### 图结构嵌入
    # 初始化模型
    model = init_model(GAT_config, graph_builder)
    model = model.to(args.device)
    
    # 分布式模型包装
    if ddp:
        model = DDP(model, device_ids=[ddp_local_rank], output_device=ddp_local_rank)
    
    # 优化器
    optimizer = optim.AdamW(model.parameters(), lr=args.learning_rate)
    
    # 学习率调度器
    scheduler = optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=args.epochs)
    
    # 训练循环
    for epoch in range(args.epochs):  # 修正为 args.epochs
        # 每个 epoch 使用相同的种子（保证可复现，但不同进程数据由 sampler 打乱）
        epoch_seed = base_seed + epoch * 1000
        random.seed(epoch_seed)
        np.random.seed(epoch_seed)
        torch.manual_seed(epoch_seed)
        torch.cuda.manual_seed(epoch_seed)
        
        # 创建数据集
        dataset = PPIDataset(
            ppi_pairs=graph_builder.train_pairs,
            node_id_to_idx=graph_builder.node_id_to_idx,
            num_neg_samples=args.neg_samples
        )
        
        # 根据是否 DDP 选择不同的 DataLoader
        if ddp:
            # 使用 DistributedSampler
            sampler = DistributedSampler(dataset, shuffle=True)
            sampler.set_epoch(epoch)  # 保证每个 epoch 打乱方式不同
            # 自定义 collate_fn，使用 graph_builder 将节点ID转换为索引
            collate_fn = partial(ddp_collate_fn, graph_builder=graph_builder)
            dataloader = torch.utils.data.DataLoader(
                dataset,
                batch_size=args.batch_size,
                sampler=sampler,
                num_workers=args.num_workers,
                pin_memory=True,
                collate_fn=collate_fn,
                drop_last=False
            )
        else:
            # 原始方式：手动打乱（可选）
            shuffled_pairs = graph_builder.train_pairs.copy()
            random.shuffle(shuffled_pairs)
            dataset.ppi_pairs = shuffled_pairs
            dataloader = PPIDataLoader(dataset, batch_size=args.batch_size, shuffle=False)
        
        train_epoch(model, graph_builder, dataloader, optimizer, args.device, epoch)
        scheduler.step()

import os
import csv
import sys
import argparse
import time
import math
import warnings
import torch
import torch.distributed as dist
from contextlib import nullcontext
from torch import optim, nn
from torch.nn.parallel import DistributedDataParallel
from torch.utils.data import DataLoader, DistributedSampler
from transformers import AutoTokenizer, AutoModelForCausalLM
from ModelLM import Config, ForCausalLM
from tqdm import tqdm
from Tokenizer import GeneTokenizer, tokenizer
from Dataset import PretrainDataset

warnings.filterwarnings('ignore')

# 打印日志，只打印主进程（rank=0）的日志
def Logger(content):
    if not args.ddp or dist.get_rank() == 0:
        print(f"[Rank {dist.get_rank() if args.ddp else 0}] {content}")

# 学习率调整，余弦退火学习率调度函数
def get_lr(current_step, total_steps, lr):
    return lr / 10 + 0.5 * lr * (1 + math.cos(math.pi * current_step / total_steps))

# 训练
def train_epoch(epoch, wandb):
    # 设置采样器 epoch
    if args.ddp:
        train_loader.sampler.set_epoch(epoch)
  
    loss_fct = nn.CrossEntropyLoss(reduction='none')
    start_time = time.time()
    
    # 添加监控指标计算所需的变量
    total_tokens = 0
    total_loss = 0
    top1_correct = 0
    top5_correct = 0
    total_masked_tokens = 0
    
    for step, (X, Y, loss_mask) in enumerate(tqdm(train_loader, desc=f"Epoch {epoch}")):
        # 数据处理与设备转移

        X = X.to(args.device)
        Y = Y.to(args.device)
        loss_mask = loss_mask.to(args.device)
        
        # 动态学习率调整
        lr = get_lr(epoch * iter_per_epoch + step, args.epochs * iter_per_epoch, args.learning_rate)
        for param_group in optimizer.param_groups:
            param_group['lr'] = lr

        # 混合精度训练与梯度累积
        with ctx:
            res = model(X)
            loss = loss_fct(
                res.logits.view(-1, res.logits.size(-1)),
                Y.view(-1)
            ).view(Y.size())

            loss = (loss * loss_mask).sum() / loss_mask.sum()
            loss += res.aux_loss
            loss = loss / args.accumulation_steps
        
        # 反向传播
        scaler.scale(loss).backward()
        
        # 梯度裁剪与参数更新
        if (step + 1) % args.accumulation_steps == 0:
            scaler.unscale_(optimizer)
            
            # 监控梯度范数
            total_norm = torch.nn.utils.clip_grad_norm_(
                model.parameters(), 
                args.grad_clip,
            #    error_if_nonfinite=True  # 检测非有限梯度
            )
            
            scaler.step(optimizer)
            scaler.update()
            optimizer.zero_grad(set_to_none=True)

        # 在梯度累积时，需要确保所有进程同步
        if args.ddp and (step + 1) % args.accumulation_steps == 0:
            # 等待所有进程完成梯度计算
            dist.barrier()
        
        # 日志记录与监控
        if step % args.log_interval == 0:
            # 计算准确率
            preds = torch.argmax(res.logits, dim=-1)
            correct = (preds == Y)                         
            valid_correct = correct[loss_mask.bool()]       
            acc = valid_correct.float().mean()              
            
            # 计算top-5准确率
            with torch.no_grad():
                # 获取top-5预测结果
                top5_preds = torch.topk(res.logits, 5, dim=-1).indices
                # 检查真实标签是否在top-5预测中
                top5_correct_mask = (top5_preds == Y.unsqueeze(-1)).any(dim=-1)
                top5_valid_correct = top5_correct_mask[loss_mask.bool()]
                top5_acc = top5_valid_correct.float().mean()
            
            # 更新监控指标
            batch_masked_tokens = loss_mask.sum().item()
            total_masked_tokens += batch_masked_tokens
            total_loss += loss.item() * args.accumulation_steps * batch_masked_tokens
            top1_correct += valid_correct.sum().item()
            top5_correct += top5_valid_correct.sum().item()
            
            # 计算PPL和BPT
            avg_loss = total_loss / total_masked_tokens if total_masked_tokens > 0 else 0
            ppl = math.exp(avg_loss) if avg_loss < 20 else float('inf')  # 防止溢出
            bpt = avg_loss / math.log(2)  # 比特每token
            
            # 计算top-1和top-5准确率
            top1_accuracy = top1_correct / total_masked_tokens if total_masked_tokens > 0 else 0
            top5_accuracy = top5_correct / total_masked_tokens if total_masked_tokens > 0 else 0
            
            spend_time = time.time() - start_time
            Logger(
                'Epoch:[{}/{}]({}/{}) loss:{:.3f} PPL:{:.3f} BPT:{:.3f} top1:{:.3f} top5:{:.3f} lr:{:.12f} epoch_Time:{:.1f}min'.format(
                    epoch + 1,
                    args.epochs,
                    step,
                    iter_per_epoch,
                    avg_loss,
                    ppl,
                    bpt,
                    top1_accuracy,
                    top5_accuracy,
                    optimizer.param_groups[-1]['lr'],
                    spend_time / (step + 1) * iter_per_epoch // 60
                ))

            if (wandb is not None) and (not args.ddp or dist.get_rank() == 0):
                wandb.log({
                    "loss": avg_loss,
                    "ppl": ppl,
                    "bpt": bpt,
                    "top1_accuracy": top1_accuracy,
                    "top5_accuracy": top5_accuracy,
                    "lr": optimizer.param_groups[-1]['lr'],
                    "epoch_time": spend_time / (step + 1) * iter_per_epoch // 60,
                    "grad_norm": total_norm.item() if 'total_norm' in locals() else 0,
                })
            
            # 重置监控指标
            total_tokens = 0
            total_loss = 0
            top1_correct = 0
            top5_correct = 0
            total_masked_tokens = 0
            
            # 仅主进程写入CSV
            os.makedirs(args.log_dir, exist_ok=True)
            if (not args.ddp or dist.get_rank() == 0):
                csv_path = os.path.join(args.log_dir, "training_logs_sft.csv")
                with open(csv_path, 'a', newline='') as f:
                    writer = csv.writer(f)
                    writer.writerow([
                        epoch + 1,                          # Epoch
                        step,                                # Step
                        avg_loss, # Loss
                        optimizer.param_groups[-1]['lr'],    # LearningRate
                        ppl,    
                        bpt,
                        top1_accuracy,
                        top5_accuracy,
                    ])
        
        # 模型保存
        if (step + 1) % args.save_interval == 0 and (not args.ddp or dist.get_rank() == 0):
            model.eval()    # 切换评估模式（关闭Dropout等）
            
            #根据MoE配置生成文件名标识
            moe_path = '_moe' if lm_config.use_moe else ''
            ckp = f'{args.save_dir}/full_sft_{lm_config.hidden_size}{moe_path}_{epoch}_{step}.pth'

            # 获取模型状态（兼容DDP分布式训练）
            state_dict = model.module.state_dict() if isinstance(model, torch.nn.parallel.DistributedDataParallel) else model.state_dict()
            
            # 仅保存可序列化的权重（跳过可能的问题参数）
            save_dict = {}
            for k, v in state_dict.items():
                if not torch.isnan(v).any() and not torch.isinf(v).any():
                    save_dict[k] = v.half()  # 转为FP16
                else:
                    Logger(f"警告: 跳过无效参数 {k}")
            
            torch.save(save_dict, ckp)    # 保存检查点
            
            model.train()    # 恢复训练模式
    
    # 最终模型保存
    if not args.ddp or dist.get_rank() == 0:
        model.eval()
        moe_path = '_moe' if lm_config.use_moe else ''
        ckp = f'{args.save_dir}/full_sft_{lm_config.hidden_size}{moe_path}_{epoch}.pth'
        
        # 获取模型状态
        state_dict = model.module.state_dict() if isinstance(model, torch.nn.parallel.DistributedDataParallel) else model.state_dict()
        
        # 仅保存可序列化的权重（跳过可能的问题参数）
        save_dict = {}
        for k, v in state_dict.items():
            if not torch.isnan(v).any() and not torch.isinf(v).any():
                save_dict[k] = v.half()  # 转为FP16
            else:
                Logger(f"警告: 跳过无效参数 {k}")
        torch.save(save_dict, ckp)

# 加载模型
def load_model(lm_config):
    model = ForCausalLM(lm_config).to(args.device)
    
    # 从预训练检查点加载
    moe_path = '_moe' if lm_config.use_moe else ''
    ckp = f'../out_pretrain-1/pretrain_{lm_config.hidden_size}{moe_path}_4.pth'
    
    if os.path.exists(ckp):
        state_dict = torch.load(ckp, map_location=args.device)
        model.load_state_dict(state_dict, strict=False)
        Logger(f'加载预训练模型成功，LLM可训练总参数量：{sum(p.numel() for p in model.parameters() if p.requires_grad) / 1e6:.3f} M')
    else:
        Logger(f'警告: 未找到预训练检查点 {ckp}，从头开始训练')
    
    return model

# 初始化模型（兼容分布式）
def init_model(lm_config, args):
    model = load_model(lm_config)
    
    # 封装为 DDP 模型
    if args.ddp:
        model = DistributedDataParallel(
            model,
            device_ids=[args.local_rank],
            output_device=args.local_rank,
            find_unused_parameters=False  # 如果模型有分支可能需要这个
        )
    
    Logger(f'LLM可训练总参数量：{sum(p.numel() for p in model.parameters() if p.requires_grad) / 1e6:.3f} M')
    return model

# 初始化分布式模式（与Pretrain保持一致）
def init_distributed_mode(args):
    if 'RANK' in os.environ and 'WORLD_SIZE' in os.environ:
        args.rank = int(os.environ["RANK"])
        args.world_size = int(os.environ["WORLD_SIZE"])
        args.local_rank = int(os.environ['LOCAL_RANK'])
        args.ddp = True
    elif hasattr(args, 'ddp') and args.ddp:
        # 单机多卡手动启动的情况
        args.rank = 0
        args.local_rank = 0
        args.world_size = torch.cuda.device_count()
        os.environ['MASTER_ADDR'] = 'localhost'
        os.environ['MASTER_PORT'] = '29500'
    else:
        args.ddp = False
        return
    
    # 初始化进程组
    dist.init_process_group(
        backend="nccl",
        init_method="env://",
        world_size=args.world_size,
        rank=args.rank
    )
    
    # 设置设备
    torch.cuda.set_device(args.local_rank)
    args.device = f"cuda:{args.local_rank}"
    
    # 设置同步
    dist.barrier()
    Logger(f"初始化进程组完成: rank={args.rank}, world_size={args.world_size}, device={args.device}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Full SFT")
    parser.add_argument("--out_dir", type=str, default="../out_sft-1")
    parser.add_argument("--epochs", type=int, default=2)
    parser.add_argument("--batch_size", type=int, default=64)
    parser.add_argument("--learning_rate", type=float, default=5e-6)
    parser.add_argument("--device", type=str, default="cuda:0" if torch.cuda.is_available() else "cpu")
    parser.add_argument("--dtype", type=str, default="bfloat16")
    parser.add_argument("--use_wandb", action="store_true")
    parser.add_argument("--wandb_project", type=str, default="Full-SFT")
    parser.add_argument("--num_workers", type=int, default=1)
    parser.add_argument("--ddp", action="store_true")
    parser.add_argument("--accumulation_steps", type=int, default=1)
    parser.add_argument("--grad_clip", type=float, default=1.0)
    parser.add_argument("--warmup_iters", type=int, default=0)
    parser.add_argument("--log_interval", type=int, default=100)
    parser.add_argument("--save_interval", type=int, default=5000)
    parser.add_argument('--local_rank', type=int, default=-1)
    parser.add_argument('--hidden_size', default=512, type=int)
    parser.add_argument('--num_hidden_layers', default=16, type=int)
    parser.add_argument('--max_seq_len', default=128, type=int)
    parser.add_argument('--use_moe', default=False, type=bool)
    parser.add_argument('--freeze_embedding', default=False, type=bool)
    parser.add_argument('--use_external_embedding', default=False, type=bool)
    parser.add_argument('--use_annotation_bias', default=False, type=bool)
    parser.add_argument('--vocab_size', type=int, default=len(tokenizer.vocab))
    parser.add_argument('--log_dir', type=str, default="../log_sft-1")
    parser.add_argument("--data_path", type=str, default="../sft_0.json")

    args = parser.parse_args()

    # 配置模型
    lm_config = Config(hidden_size=args.hidden_size, 
                       num_hidden_layers=args.num_hidden_layers, 
                       use_moe=args.use_moe, 
                       freeze_embedding=args.freeze_embedding,
                       use_external_embedding=args.use_external_embedding,
                       use_annotation_bias=args.use_annotation_bias,
                       vocab_size=args.vocab_size)
    
    args.save_dir = os.path.join(args.out_dir)
    os.makedirs(args.save_dir, exist_ok=True)
    os.makedirs(args.out_dir, exist_ok=True)
    tokens_per_iter = args.batch_size * args.max_seq_len
    device_type = "cuda" if "cuda" in args.device else "cpu"

    # 初始化分布式
    init_distributed_mode(args)

    args.wandb_run_name = f"Full-SFT-Epoch-{args.epochs}-BatchSize-{args.batch_size}-LearningRate-{args.learning_rate}"

    ctx = nullcontext() if device_type == "cpu" else torch.cuda.amp.autocast()

    # 随机种子
    base_seed = 20030201
    torch.manual_seed(base_seed)
    torch.cuda.manual_seed(base_seed)
    
    # 如果使用分布式，为每个进程设置不同的随机种子
    if args.ddp:
        torch.manual_seed(base_seed + args.rank)
        torch.cuda.manual_seed(base_seed + args.rank)

    # WandB初始化
    if args.use_wandb and (not args.ddp or (args.ddp and args.rank == 0)):
        import wandb
        wandb.init(project=args.wandb_project, name=args.wandb_run_name)
    else:
        wandb = None

    # 初始化模型和数据
    model = init_model(lm_config, args)
    dataset = PretrainDataset(args.data_path, tokenizer, max_length=args.max_seq_len)
    
    # 数据加载器 (分布式采样器)
    train_sampler = DistributedSampler(dataset) if args.ddp else None
    train_loader = DataLoader(
        dataset,
        batch_size=args.batch_size,
        pin_memory=True,
        drop_last=False,
        shuffle=(train_sampler is None),  # 只有在非分布式时shuffle
        num_workers=args.num_workers,
        sampler=train_sampler
    )

    # 优化器和混合精度
    scaler = torch.cuda.amp.GradScaler(enabled=(args.dtype in ['float16', 'bfloat16']))
    optimizer = optim.AdamW(model.parameters(), lr=args.learning_rate)
    
    iter_per_epoch = len(train_loader)
    for epoch in range(args.epochs):
        train_epoch(epoch, wandb)

    # 清理
    if args.ddp:
        dist.destroy_process_group()

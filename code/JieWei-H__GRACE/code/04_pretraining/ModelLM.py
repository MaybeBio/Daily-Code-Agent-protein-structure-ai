from transformers import PretrainedConfig

class Config(PretrainedConfig):
    model_type = ""

    def __init__(
            self,
            dropout: float = 0.0,
            bos_token_id: int = 1,
            eos_token_id: int = 2,
            hidden_act: str = 'silu',
            hidden_size: int = 512,
            intermediate_size: int = None,
            max_position_embeddings: int = 32768,
            num_attention_heads: int = 8,
            num_hidden_layers: int = 32,
            num_key_value_heads: int = 2,
            vocab_size: int = 6000,
            rms_norm_eps: float = 1e-05,
            rope_theta: int = 1000000.0,
            flash_attn: bool = True,
            ## Embedding + Annotation
            use_external_embedding: bool = True,
            external_embedding_path: str = "../node_embeddings_PPI.pt",
            freeze_embedding: bool = False,
            use_annotation_bias: bool = False,
            annotation_sim_path: str = "../integrated_similarity_All.pt",
            alpha: float = 1,
            ####################################################
            # Here are the specific configurations of MOE
            # When use_moe is false, the following is invalid
            ####################################################
            use_moe: bool = False,
            num_experts_per_tok: int = 2,
            n_routed_experts: int = 4,
            n_shared_experts: int = 1,
            scoring_func: str = 'softmax',
            aux_loss_alpha: float = 0.1,
            seq_aux: bool = True,
            norm_topk_prob: bool = True,
            **kwargs
    ):
        super().__init__(**kwargs)
        self.dropout = dropout
        self.bos_token_id = bos_token_id
        self.eos_token_id = eos_token_id
        self.hidden_act = hidden_act
        self.hidden_size = hidden_size
        self.intermediate_size = intermediate_size
        self.max_position_embeddings = max_position_embeddings
        self.num_attention_heads = num_attention_heads
        self.num_hidden_layers = num_hidden_layers
        self.num_key_value_heads = num_key_value_heads
        self.vocab_size = vocab_size
        self.rms_norm_eps = rms_norm_eps
        self.rope_theta = rope_theta
        self.flash_attn = flash_attn
        ####################################################
        # Here are the specific configurations of MOE
        # When use_moe is false, the following is invalid
        ####################################################
        self.freeze_embedding = freeze_embedding
        self.use_external_embedding = use_external_embedding
        self.use_annotation_bias = use_annotation_bias
        self.alpha = alpha
        self.annotation_sim_path = annotation_sim_path
        self.external_embedding_path = external_embedding_path
        self.use_moe = use_moe
        self.num_experts_per_tok = num_experts_per_tok  # 每个token选择的专家数量
        self.n_routed_experts = n_routed_experts  # 总的专家数量
        self.n_shared_experts = n_shared_experts  # 共享专家
        self.scoring_func = scoring_func  # 评分函数，默认为'softmax'
        self.aux_loss_alpha = aux_loss_alpha  # 辅助损失的alpha参数
        self.seq_aux = seq_aux  # 是否在序列级别上计算辅助损失
        self.norm_topk_prob = norm_topk_prob  # 是否标准化top-k概率


####################### LM Model
import math
import torch
from torch import nn
from transformers.activations import ACT2FN
from typing import Optional, Tuple, List, Union
import torch.nn.functional as F
from transformers import PreTrainedModel, GenerationMixin, PretrainedConfig
from transformers.modeling_outputs import CausalLMOutputWithPast

## 层归一化，相比于LayerNorm省去均值计算（可用LayerNorm替换该部分）
class RMSNorm(torch.nn.Module):
    def __init__(self, dim: int, eps: float = 1e-5):
        super().__init__()
        self.eps = eps
        self.weight = nn.Parameter(torch.ones(dim))

    def _norm(self, x):
        return x * torch.rsqrt(x.pow(2).mean(-1, keepdim=True) + self.eps)

    def forward(self, x):
        return self.weight * self._norm(x.float()).type_as(x)

## 旋转位置编码封装（RoPE），相对位置编码
def precompute_freqs_cis(dim: int, end: int = int(32 * 1024), theta: float = 1e6):
    # dim：隐藏层维度（需为偶数），表示位置编码的维度。
    # end：最大序列长度（默认32K），支持长上下文处理。
    # theta：频率基数（默认1e6），控制旋转频率分布
    freqs = 1.0 / (theta ** (torch.arange(0, dim, 2)[: (dim // 2)].float() / dim))
    t = torch.arange(end, device=freqs.device)
    freqs = torch.outer(t, freqs).float()
    freqs_cos = torch.cat([torch.cos(freqs), torch.cos(freqs)], dim=-1)
    freqs_sin = torch.cat([torch.sin(freqs), torch.sin(freqs)], dim=-1)
    return freqs_cos, freqs_sin

## 旋转位置编码
def apply_rotary_pos_emb(q, k, cos, sin, position_ids=None, unsqueeze_dim=1):
    def rotate_half(x):
        return torch.cat((-x[..., x.shape[-1] // 2:], x[..., : x.shape[-1] // 2]), dim=-1)

    q_embed = (q * cos.unsqueeze(unsqueeze_dim)) + (rotate_half(q) * sin.unsqueeze(unsqueeze_dim))
    k_embed = (k * cos.unsqueeze(unsqueeze_dim)) + (rotate_half(k) * sin.unsqueeze(unsqueeze_dim))
    return q_embed, k_embed


## 分组查询注意力GAQ
def repeat_kv(x: torch.Tensor, n_rep: int) -> torch.Tensor:
    """torch.repeat_interleave(x, dim=2, repeats=n_rep)"""
    bs, slen, num_key_value_heads, head_dim = x.shape
    if n_rep == 1:
        return x
    return (
        x[:, :, :, None, :]
        .expand(bs, slen, num_key_value_heads, n_rep, head_dim)
        .reshape(bs, slen, num_key_value_heads * n_rep, head_dim)
    )

## 多头注意力机制
class Attention(nn.Module):
    def __init__(self, args: Config):
        super().__init__()
        self.num_key_value_heads = args.num_attention_heads if args.num_key_value_heads is None else args.num_key_value_heads
        assert args.num_attention_heads % self.num_key_value_heads == 0
        self.n_local_heads = args.num_attention_heads  ## 注意力头（查询）
        self.n_local_kv_heads = self.num_key_value_heads  ## 注意力头（广播），一个对应多个查询
        self.n_rep = self.n_local_heads // self.n_local_kv_heads ## 对多个查询进行广播
        self.head_dim = args.hidden_size // args.num_attention_heads ## 每个头的特征维度
        self.q_proj = nn.Linear(args.hidden_size, args.num_attention_heads * self.head_dim, bias=False) 
        self.k_proj = nn.Linear(args.hidden_size, self.num_key_value_heads * self.head_dim, bias=False)
        self.v_proj = nn.Linear(args.hidden_size, self.num_key_value_heads * self.head_dim, bias=False)
        self.o_proj = nn.Linear(args.num_attention_heads * self.head_dim, args.hidden_size, bias=False) ## 整合多个头
        self.attn_dropout = nn.Dropout(args.dropout)
        self.resid_dropout = nn.Dropout(args.dropout)
        self.dropout = args.dropout
        self.flash = hasattr(torch.nn.functional, 'scaled_dot_product_attention') and args.flash_attn ## 加速训练
        # print("WARNING: using slow attention. Flash Attention requires PyTorch >= 2.0")

    def forward(self,
                x: torch.Tensor,
                position_embeddings: Tuple[torch.Tensor, torch.Tensor],
                past_key_value: Optional[Tuple[torch.Tensor, torch.Tensor]] = None,
                use_cache=False,
                attention_mask: Optional[torch.Tensor] = None):
        bsz, seq_len, _ = x.shape
        xq, xk, xv = self.q_proj(x), self.k_proj(x), self.v_proj(x)
        xq = xq.view(bsz, seq_len, self.n_local_heads, self.head_dim)
        xk = xk.view(bsz, seq_len, self.n_local_kv_heads, self.head_dim)
        xv = xv.view(bsz, seq_len, self.n_local_kv_heads, self.head_dim)

        cos, sin = position_embeddings 
        xq, xk = apply_rotary_pos_emb(xq, xk, cos[:seq_len], sin[:seq_len])

        # kv_cache实现
        if past_key_value is not None:
            xk = torch.cat([past_key_value[0], xk], dim=1)
            xv = torch.cat([past_key_value[1], xv], dim=1)
        past_kv = (xk, xv) if use_cache else None

        xq, xk, xv = (
            xq.transpose(1, 2),
            repeat_kv(xk, self.n_rep).transpose(1, 2),
            repeat_kv(xv, self.n_rep).transpose(1, 2)
        )

        if self.flash and seq_len != 1:
            dropout_p = self.dropout if self.training else 0.0
            attn_mask = None
            if attention_mask is not None:
                attn_mask = attention_mask.view(bsz, 1, 1, -1).expand(bsz, self.n_local_heads, seq_len, -1)
                attn_mask = attn_mask.bool() if attention_mask is not None else None

            output = F.scaled_dot_product_attention(xq, xk, xv, attn_mask=attn_mask, dropout_p=dropout_p, is_causal=True)
        else:
            # 1. 计算注意力分数
            scores = (xq @ xk.transpose(-2, -1)) / math.sqrt(self.head_dim)
            
            # 2. 添加因果掩码（防止未来信息泄漏）
            scores = scores + torch.triu(
                torch.full((seq_len, seq_len), float("-inf"), device=scores.device),
                diagonal=1
            ).unsqueeze(0).unsqueeze(0)  # scores+mask

            # 3. 处理自定义注意力掩码（如填充位置）
            if attention_mask is not None:
                extended_attention_mask = attention_mask.unsqueeze(1).unsqueeze(2)
                extended_attention_mask = (1.0 - extended_attention_mask) * -1e9
                scores = scores + extended_attention_mask
            
            # 4. Softmax + Dropout
            scores = F.softmax(scores.float(), dim=-1).type_as(xq)
            scores = self.attn_dropout(scores)
            
            # 5. 加权求和
            output = scores @ xv

        output = output.transpose(1, 2).reshape(bsz, seq_len, -1)
        output = self.resid_dropout(self.o_proj(output))
        return output, past_kv

## 门控前馈神经网络层
class FeedForward(nn.Module):
    def __init__(self, config: Config):
        super().__init__()
        if config.intermediate_size is None:
            intermediate_size = int(config.hidden_size * 8 / 3) 
            config.intermediate_size = 64 * ((intermediate_size + 64 - 1) // 64)  ## 中间层
        self.gate_proj = nn.Linear(config.hidden_size, config.intermediate_size, bias=False) ## 输入层 * 中间层(门控)
        self.down_proj = nn.Linear(config.intermediate_size, config.hidden_size, bias=False) ## 中间层 *输出层(下层)
        self.up_proj = nn.Linear(config.hidden_size, config.intermediate_size, bias=False) ## 输入层 * 中间层(上层)
        self.dropout = nn.Dropout(config.dropout)
        self.act_fn = ACT2FN[config.hidden_act] 

    def forward(self, x):
        return self.dropout(self.down_proj(self.act_fn(self.gate_proj(x)) * self.up_proj(x)))  ## 注意门控和上层信息累乘（不是矩阵相乘）

## 专家门控部件：MoEGate
class MoEGate(nn.Module):
    def __init__(self, config: Config):
        super().__init__()
        self.config = config
        self.top_k = config.num_experts_per_tok  # 每个token使用的专家数量
        self.n_routed_experts = config.n_routed_experts  # 路由专家的总数

        self.scoring_func = config.scoring_func   # 评分函数，通常为'softmax'
        self.alpha = config.aux_loss_alpha    # 辅助损失系数
        self.seq_aux = config.seq_aux   # 是否使用序列级别的辅助损失

        self.norm_topk_prob = config.norm_topk_prob  # 是否对topk权重进行归一化，默认True
        self.gating_dim = config.hidden_size   # 门控维度，即隐藏层大小
        self.weight = nn.Parameter(torch.empty((self.n_routed_experts, self.gating_dim)))  
        self.reset_parameters()

    def reset_parameters(self) -> None:
        import torch.nn.init as init
        init.kaiming_uniform_(self.weight, a=math.sqrt(5))

    def forward(self, hidden_states):
        bsz, seq_len, h = hidden_states.shape  # 输入维度: (bsz, seq_len, hidden_dim)
        hidden_states = hidden_states.view(-1, h)  # 展平: (bsz*seq_len, hidden_dim)
        
        # 线性映射计算专家得分 [batch*seq_len, n_routed_experts]
        logits = F.linear(hidden_states, self.weight, None)
        
        # Softmax 转换为概率分布
        if self.scoring_func == 'softmax':
            scores = logits.softmax(dim=-1)
        else:
            raise NotImplementedError(f'insupportable scoring function for MoE gating: {self.scoring_func}')
        
        # 选取top-k的专家
        topk_weight, topk_idx = torch.topk(scores, k=self.top_k, dim=-1, sorted=False) 

        # 归一化 TopK 权重（确保和为 1）
        if self.top_k > 1 and self.norm_topk_prob:
            denominator = topk_weight.sum(dim=-1, keepdim=True) + 1e-20
            topk_weight = topk_weight / denominator

        # 计算辅助损失（负载均衡）
        if self.training and self.alpha > 0.0:
            scores_for_aux = scores
            aux_topk = self.top_k
            topk_idx_for_aux_loss = topk_idx.view(bsz, -1)
            if self.seq_aux:
                # 1. 计算专家选择频率 [bsz, n_experts]
                scores_for_seq_aux = scores_for_aux.view(bsz, seq_len, -1)
                ce = torch.zeros(bsz, self.n_routed_experts, device=hidden_states.device)
                ce.scatter_add_(1, topk_idx_for_aux_loss,
                                torch.ones(bsz, seq_len * aux_topk, device=hidden_states.device))
                # 2. 归一化频率: 实际频率 vs 均匀分布
                ce.div_(seq_len * aux_topk / self.n_routed_experts)
                # 3. 损失 = (频率 * 平均门控分数) 的批次均值
                scores_seq = scores.view(bsz, seq_len, -1)  # [batch, seq_len, n_routed_experts]
                aux_loss = (ce * scores_seq.mean(dim=1)).sum(dim=1).mean() * self.alpha
            else:
                mask_ce = F.one_hot(topk_idx_for_aux_loss.view(-1), num_classes=self.n_routed_experts)  # [batch*seq_len*topK, n_routed_experts]
                ce = mask_ce.float().mean(0)   # 各专家被选中的全局概率
                Pi = scores_for_aux.mean(0)    # 各专家的平均门控分数
                fi = ce * self.n_routed_experts    # 频率缩放因子（理想值=1）
                aux_loss = (Pi * fi).sum() * self.alpha    # 点积衡量偏离程度
        else:
            aux_loss = 0
        return topk_idx, topk_weight, aux_loss

## MoE混合专家系统，可替换前馈网络层部件
class MOEFeedForward(nn.Module):
    def __init__(self, config: Config):
        super().__init__()
        self.config = config
        self.experts = nn.ModuleList([
            FeedForward(config)
            for _ in range(config.n_routed_experts)
        ])
        self.gate = MoEGate(config)
        if config.n_shared_experts > 0:
            self.shared_experts = nn.ModuleList([
                FeedForward(config)
                for _ in range(config.n_shared_experts)
            ])

    def forward(self, x):
        identity = x  # 保留原始输入 (bsz, seq_len, hidden_dim)
        orig_shape = x.shape
        bsz, seq_len, _ = x.shape
        
        # 门控网络输出：
        #   topk_idx: 专家索引 (bsz, seq_len, num_experts_per_tok)
        #   topk_weight: 专家权重 (同形状)
        #   aux_loss: 负载均衡损失
        topk_idx, topk_weight, aux_loss = self.gate(x) 
        
        # 维度变换：
        x = x.view(-1, x.shape[-1])   # (bsz*seq_len, hidden_dim)
        flat_topk_idx = topk_idx.view(-1)   # (bsz*seq_len*num_experts_per_tok,)
        if self.training:
            # 复制输入：为每个token的每个专家准备输入
            x = x.repeat_interleave(self.config.num_experts_per_tok, dim=0)  # (bsz*seq_len, hidden_dim)
            y = torch.empty_like(x, dtype=torch.float16)  
            # 遍历所有专家
            for i, expert in enumerate(self.experts):
                mask = (flat_topk_idx == i)  # 当前专家应处理的token掩码
                y[mask] = expert(x[mask]).to(y.dtype)  # 专家计算
            
            # 加权融合：y * topk_weight
            y = (y.view(*topk_weight.shape, -1) * topk_weight.unsqueeze(-1)).sum(dim=1)
            y = y.view(*orig_shape)  # (bsz, seq_len, hidden_dim)
        else:
            y = self.moe_infer(x, flat_topk_idx, topk_weight.view(-1, 1)).view(*orig_shape)
        if self.config.n_shared_experts > 0:
            for expert in self.shared_experts:
                y = y + expert(identity)
        self.aux_loss = aux_loss
        return y

    @torch.no_grad()
    def moe_infer(self, x, flat_expert_indices, flat_expert_weights):
        # 初始化输出缓存
        expert_cache = torch.zeros_like(x)
        # 对专家索引排序（便于分组处理）
        idxs = flat_expert_indices.argsort()
        # 计算每个专家处理的token数量（累计和）
        tokens_per_expert = flat_expert_indices.bincount().cpu().numpy().cumsum(0)
        # 计算原始token索引（考虑每个token有多个专家）
        token_idxs = idxs // self.config.num_experts_per_tok
        # 当tokens_per_expert = [6, 15, 20, 26]，tokens_per_expert.shape[0]即为专家数量（此时为4）
        # 且token_idxs = [3, 7, 19, 21, 24, 25,  4,  5,  6, 10, 11, 12...] 时
        # 意味token_idxs[:6] -> [3, 7, 19, 21, 24, 25]这6个位置属于专家0处理的token（每个token有可能被多个专家处理，这取决于num_experts_per_tok）
        # 接下来9个位置token_idxs[6:15] -> [4,  5,  6, 10, 11, 12...]属于专家1处理的token...依此类推
        for i, end_idx in enumerate(tokens_per_expert):
            start_idx = 0 if i == 0 else tokens_per_expert[i - 1]
            if start_idx == end_idx:
                continue
            expert = self.experts[i]
            exp_token_idx = token_idxs[start_idx:end_idx]
            expert_tokens = x[exp_token_idx]
            expert_out = expert(expert_tokens).to(expert_cache.dtype)
            expert_out.mul_(flat_expert_weights[idxs[start_idx:end_idx]])
            expert_cache.scatter_add_(0, exp_token_idx.view(-1, 1).repeat(1, x.shape[-1]), expert_out)

        return expert_cache

## block封装（多头注意力机制 + 规范化/残差链接 + MoE层 + 规范化/残差链接）
class Block(nn.Module):
    def __init__(self, layer_id: int, config: Config):
        super().__init__()
        self.num_attention_heads = config.num_attention_heads  ## 注意力头数
        self.hidden_size = config.hidden_size   ## 特征维度
        self.head_dim = config.hidden_size // config.num_attention_heads  ##每个头的维度 = 特征维度/注意力头数
        self.self_attn = Attention(config) ## 注意力参数

        self.layer_id = layer_id  ## 层id
        self.input_layernorm = RMSNorm(config.hidden_size, eps=config.rms_norm_eps) ## 规范化1
        self.post_attention_layernorm = RMSNorm(config.hidden_size, eps=config.rms_norm_eps) ## 规范化2
        self.mlp = FeedForward(config) if not config.use_moe else MOEFeedForward(config) ## 前馈网络层 或 MoE专家模式

    def forward(self, hidden_states, position_embeddings, past_key_value=None, use_cache=False, attention_mask=None):
        ## 输入特征
        residual = hidden_states  
        
        ## 多头自注意力机制
        hidden_states, present_key_value = self.self_attn(
            self.input_layernorm(hidden_states), position_embeddings,
            past_key_value, use_cache, attention_mask
        )
        ## 残差连接
        hidden_states += residual
        
        ## 规范化+残差连接
        hidden_states = hidden_states + self.mlp(self.post_attention_layernorm(hidden_states))
        
        return hidden_states, present_key_value

## 模型架构
class Model(nn.Module):
    def __init__(self, config: Config): 
        super().__init__()
        self.config = config
        self.vocab_size, self.num_hidden_layers = config.vocab_size, config.num_hidden_layers
        
        # 简化的嵌入层初始化（实际会被ForCausalLM替换）
        self.embed_tokens = nn.Embedding(config.vocab_size, config.hidden_size)
        
        self.dropout = nn.Dropout(config.dropout)  # Dropout层防止过拟合
        self.layers = nn.ModuleList([Block(l, config) for l in range(self.num_hidden_layers)]) # 堆叠多个Transformer Block
        self.norm = RMSNorm(config.hidden_size, eps=config.rms_norm_eps)   # 最终层归一化（使用RMSNorm而非LayerNorm）

        freqs_cos, freqs_sin = precompute_freqs_cis(dim=config.hidden_size // config.num_attention_heads,
                                                    end=config.max_position_embeddings, 
                                                    theta=config.rope_theta)
        
        # 注册为不参与持久化的缓冲区（不保存到模型文件）
        self.register_buffer("freqs_cos", freqs_cos, persistent=False)
        self.register_buffer("freqs_sin", freqs_sin, persistent=False)

    def forward(self,
                input_ids: Optional[torch.Tensor] = None,
                attention_mask: Optional[torch.Tensor] = None,
                past_key_values: Optional[List[Tuple[torch.Tensor, torch.Tensor]]] = None,
                use_cache: bool = False,
                **kwargs):
        batch_size, seq_length = input_ids.shape  # 输入维度: (batch_size, seq_len)
        past_key_values = past_key_values or [None] * len(self.layers)   # 初始化past_key_values（用于增量解码）
        start_pos = past_key_values[0][0].shape[1] if past_key_values[0] is not None else 0    # 计算当前解码位置（用于旋转位置编码）

        # 词嵌入 + Dropout
        hidden_states = self.dropout(self.embed_tokens(input_ids))  # 维度: (bs, seq_len) → (bs, seq_len, hidden_size)

        # 位置编码动态切片
        position_embeddings = (
            self.freqs_cos[start_pos:start_pos + seq_length],
            self.freqs_sin[start_pos:start_pos + seq_length]
        )
        
        presents = []  # 存储每层的当前KV缓存
        # 逐层Transformer Block处理
        for layer_idx, (layer, past_key_value) in enumerate(zip(self.layers, past_key_values)):
            hidden_states, present = layer(
                hidden_states,
                position_embeddings,
                past_key_value=past_key_value,
                use_cache=use_cache,
                attention_mask=attention_mask
            )
            presents.append(present)

        hidden_states = self.norm(hidden_states)

        # MoE损失值
        aux_loss = sum(
            layer.mlp.aux_loss
            for layer in self.layers
            if isinstance(layer.mlp, MOEFeedForward)
        )

        return hidden_states, presents, aux_loss

# 因果语言模型
class ForCausalLM(PreTrainedModel, GenerationMixin):
    config_class = Config

    def __init__(self, config: Config = None):
        self.config = config or Config()
        super().__init__(self.config)
      
        self.use_external_embedding = config.use_external_embedding
        self.external_embedding_path = config.external_embedding_path
        self.freeze_embedding = config.freeze_embedding
        self.use_annotation_bias = config.use_annotation_bias
        self.annotation_sim_path = config.annotation_sim_path
        self.alpha = config.alpha
        
        # 处理外部嵌入特征（如果有）
        if self.use_external_embedding:
            try:
                # 加载外部嵌入
                full_embeddings = torch.load(self.external_embedding_path)
                print(f"成功加载外部词嵌入，形状: {full_embeddings.shape}")
                
                # 确保外部嵌入的维度与模型配置一致
                if full_embeddings.shape[1] != self.config.hidden_size:
                    raise ValueError(f"外部嵌入维度 {full_embeddings.shape[1]} 与模型隐藏层维度 {self.config.hidden_size} 不匹配")
                
                # LayerNorm式标准化
                full_embeddings = F.layer_norm(
                    full_embeddings, 
                    [self.config.hidden_size],
                    weight=None,  # 不使用可学习的缩放
                    bias=None,    # 不使用可学习的偏置
                    eps=1e-5
                )
                
                print(f"完整嵌入矩阵形状: {full_embeddings.shape}")
                
                # 直接创建嵌入层
                self.embed_tokens = nn.Embedding.from_pretrained(
                    full_embeddings, 
                    freeze=self.freeze_embedding
                )
                
            except FileNotFoundError:
                print(f"警告: 未找到外部嵌入文件 {external_embedding_path}，使用随机初始化")
                self.embed_tokens = nn.Embedding(self.config.vocab_size, self.config.hidden_size)
        else:
            # 使用随机初始化的嵌入层
            self.embed_tokens = nn.Embedding(self.config.vocab_size, self.config.hidden_size)
            # 在创建 embed_tokens 之后
            if self.freeze_embedding:
                self.embed_tokens.weight.requires_grad = False
        
        
        # 主干模型（Transformer解码器）
        self.model = Model(self.config)  
        
        # 替换Model中的嵌入层为我们创建好的嵌入层
        self.model.embed_tokens = self.embed_tokens
        
        # 语言模型头：将隐藏状态映射为词表概率
        self.lm_head = nn.Linear(self.config.hidden_size, self.config.vocab_size, bias=False) 
        
        if self.use_annotation_bias:
            try:
                # 加载预计算的注释相似性矩阵
                self.annotation_sim_matrix = torch.load(self.annotation_sim_path)
                print(f"成功加载注释相似性矩阵，形状: {self.annotation_sim_matrix.shape}")
                # 注册为缓冲区，不参与训练
                self.register_buffer("sim_matrix", self.annotation_sim_matrix)
            except FileNotFoundError:
                print(f"警告: 未找到注释相似性文件 {annotation_sim_path}，禁用注释偏置")
                self.use_annotation_bias = False
                self.sim_matrix = None
        else:
            self.sim_matrix = None
            
        
        # 标准化输出容器（兼容Hugging Face接口）
        self.OUT = CausalLMOutputWithPast()
    
    def apply_annotation_bias(self, logits, input_ids):
        """在推理时对 logits 添加偏置（仅当当前 token 为图节点时有效）"""
        if not self.use_annotation_bias or self.sim_matrix is None:
            return logits

        batch, seq_len, vocab_size = logits.shape
        device = logits.device
        dtype = logits.dtype

        # 创建偏置张量（通常 seq_len 为 1，但通用处理）
        bias_matrix = torch.zeros(batch, seq_len, vocab_size, device=device, dtype=dtype)

        for b in range(batch):
            for t in range(seq_len):
                token_id = input_ids[b, t].item()
                # 从稀疏矩阵中取出对应行并转为密集向量
                row_bias = self.sim_matrix[token_id].to_dense()  # (vocab_size,)
                bias_matrix[b, t] = row_bias * self.alpha

        return logits + bias_matrix
    
    def prepare_inputs_for_generation(self, input_ids, past_key_values=None, attention_mask=None, **kwargs):
        # 如果存在 past_key_values，说明是增量解码，只需最后一个 token
        if past_key_values is not None:
            # 只保留最后一个 token
            input_ids = input_ids[:, -1:]
            # attention_mask 也必须同步截取到最后（与 input_ids 长度一致）
            if attention_mask is not None:
                attention_mask = attention_mask[:, -1:]
        
        return {
            "input_ids": input_ids,
            "past_key_values": past_key_values,
            "attention_mask": attention_mask,
            "apply_bias": True,  # 生成时启用偏置
            **kwargs
        }
     
    def forward(self,
                input_ids: Optional[torch.Tensor] = None,
                attention_mask: Optional[torch.Tensor] = None,
                past_key_values: Optional[List[Tuple[torch.Tensor, torch.Tensor]]] = None,
                use_cache: bool = False,
                logits_to_keep: Union[int, torch.Tensor] = 0,
                apply_bias: bool = False,
                **args):
        # 主干模型计算（返回隐藏状态、KV缓存、辅助损失）
        h, past_kvs, aux_loss = self.model(
            input_ids=input_ids,
            attention_mask=attention_mask,
            past_key_values=past_key_values,
            use_cache=use_cache,
            **args
        )
        
        # 首先计算所有位置的logits
        all_logits = self.lm_head(h)  # [batch_size, seq_len, vocab_size]
        
        # 然后应用注释相似性偏置（在所有位置上）
        if apply_bias and self.use_annotation_bias and input_ids is not None:
            all_logits = self.apply_annotation_bias(all_logits, input_ids)
        
        # 最后进行logits切片
        slice_indices = slice(-logits_to_keep, None) if isinstance(logits_to_keep, int) else logits_to_keep
        logits = all_logits[:, slice_indices, :]
        
        self.OUT.__setitem__('last_hidden_state', h)
        self.OUT.__setitem__('logits', logits)
        self.OUT.__setitem__('aux_loss', aux_loss)
        self.OUT.__setitem__('past_key_values', past_kvs)
        return self.OUT

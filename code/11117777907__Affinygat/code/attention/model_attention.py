import torch
import torch.nn as nn
from torch_geometric.nn import GATConv, global_mean_pool

class GATEncoder(nn.Module):
    def __init__(self, in_channels, hidden_channels=128, out_channels=256,
                 num_layers=3, heads=4, dropout=0.3, batchnorm=True):
        super().__init__()
        self.convs = nn.ModuleList()
        self.norms = nn.ModuleList() if batchnorm else None
        self.dropout = nn.Dropout(dropout)

        # First layer
        self.convs.append(GATConv(in_channels, hidden_channels, heads=heads, edge_dim=3, concat=True))
        if batchnorm:
            self.norms.append(nn.BatchNorm1d(hidden_channels * heads))

        # Middle layers
        for _ in range(num_layers - 2):
            self.convs.append(GATConv(hidden_channels * heads, hidden_channels, heads=heads, edge_dim=3, concat=True))
            if batchnorm:
                self.norms.append(nn.BatchNorm1d(hidden_channels * heads))

        # Last layer
        self.convs.append(GATConv(hidden_channels * heads, out_channels, heads=1, edge_dim=3, concat=False))
        if batchnorm:
            self.norms.append(nn.BatchNorm1d(out_channels))

        self.relu = nn.ReLU()

    def forward(self, x, edge_index, edge_attr, batch, return_attn=False):
        for i, conv in enumerate(self.convs[:-1]):
            x = conv(x, edge_index, edge_attr)
            if self.norms is not None:
                x = self.norms[i](x)
            x = self.relu(x)
            x = self.dropout(x)

        # === 核心修改：拦截最后一层以提取 Attention 权重 ===
        if return_attn:
            # 开启 return_attention_weights=True，返回 (特征, (边索引, 注意力权重))
            x, (attn_edge_index, attn_weights) = self.convs[-1](x, edge_index, edge_attr, return_attention_weights=True)
            
            # 即使最后一层 heads=1，attn_weights 的维度仍为 [E, heads]。
            # 求平均将其标准化为一维张量 [E]，便于后续取 Top K
            mean_attn_weights = attn_weights.mean(dim=1)
            
            # 直接中断前向传播，返回图注意力数据
            return attn_edge_index, mean_attn_weights
        else:
            # 正常的前向传播逻辑
            x = self.convs[-1](x, edge_index, edge_attr)
            if self.norms is not None:
                x = self.norms[-1](x)

            x = global_mean_pool(x, batch)
            return x


class AffinityGAT(nn.Module):
    def __init__(self, in_channels=34, hidden_channels=128, out_channels=256,
                 num_layers=3, heads=4, dropout=0.3, batchnorm=True):
        super().__init__()
        self.encoder = GATEncoder(
            in_channels=in_channels,
            hidden_channels=hidden_channels,
            out_channels=out_channels,
            num_layers=num_layers,
            heads=heads,
            dropout=dropout,
            batchnorm=batchnorm
        )
        self.head = nn.Sequential(
            nn.Linear(out_channels, 128),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(128, 1)
        )

    # 增加 return_attn=False 参数
    def forward(self, data, return_attn=False):
        batch = data.batch if hasattr(data, 'batch') else torch.zeros(data.x.size(0), dtype=torch.long, device=data.x.device)
        
        if return_attn:
            # 开启提取模式：透传 return_attn，并直接返回 Encoder 的输出（边索引和权重），跳过回归头
            return self.encoder(data.x, data.edge_index, data.edge_attr, batch, return_attn=True)
        else:
            # 正常预测模式：计算特征并回归出最终的 pKd
            h = self.encoder(data.x, data.edge_index, data.edge_attr, batch)
            out = self.head(h)
            return out.view(-1)
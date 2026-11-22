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

    def forward(self, x, edge_index, edge_attr, batch):
        for i, conv in enumerate(self.convs[:-1]):
            x = conv(x, edge_index, edge_attr)
            if self.norms is not None:
                x = self.norms[i](x)
            x = self.relu(x)
            x = self.dropout(x)

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

    def forward(self, data):
        batch = data.batch if hasattr(data, 'batch') else torch.zeros(data.x.size(0), dtype=torch.long, device=data.x.device)
        h = self.encoder(data.x, data.edge_index, data.edge_attr, batch)
        out = self.head(h)
        return out.view(-1)
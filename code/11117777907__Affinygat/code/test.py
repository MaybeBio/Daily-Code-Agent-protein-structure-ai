import os
import csv
import json
import torch
import numpy as np
from torch.utils.data import Dataset, DataLoader
from torch_geometric.data import Batch
from model import AffinityGAT
from datetime import datetime
from tqdm import tqdm

# ============================= CONFIG =============================
GRAPH_DIR = "data/graphs_test_2016"
CSV_FILE = "affinity_test2016.csv"
STATS_FILE = "training_stats.json"
DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")
BATCH_SIZE = 32
OUTPUT_CSDIR = "3_2016"
os.makedirs(OUTPUT_CSDIR, exist_ok=True)

print("="*60)
print("Protein-Ligand Affinity Prediction - Test on PDBbind 2016")
print("="*60)
print(f"Test set directory : {GRAPH_DIR}")
print(f"Affinity CSV       : {CSV_FILE}")
print(f"Training stats     : {STATS_FILE}")
print(f"Device             : {DEVICE}")
print(f"Batch size         : {BATCH_SIZE}")
print(f"Output directory   : {OUTPUT_CSDIR}")
print("-"*60)

# Load statistics
with open(STATS_FILE) as f:
    stats = json.load(f)
aff_mean = torch.tensor(stats["aff_mean"], device=DEVICE)
aff_std  = torch.tensor(stats["aff_std"],  device=DEVICE)
edge_mu  = torch.tensor(stats["edge_mu"],  device=DEVICE)
edge_sig = torch.tensor(stats["edge_sigma"], device=DEVICE)

print(f"Affinity  mean/std : {stats['aff_mean']:.4f} / {stats['aff_std']:.4f}")
print(f"Edge dist mean/std : {stats['edge_mu']:.4f} / {stats['edge_sigma']:.4f}")
print("-"*60)


class TestDataset(Dataset):
    def __init__(self, graph_dir, csv_file):
        self.graph_dir = graph_dir
        self.affinities = {}
        self.pdb_ids = []
        with open(csv_file) as f:
            for row in csv.reader(f):
                if len(row)!=2 or row[0].lower()=="pdb_id": continue
                pid, val = row
                try: self.affinities[pid] = float(val)
                except: pass
        for f in os.listdir(graph_dir):
            if f.endswith("_combined.pt"):
                pid = f[:-len("_combined.pt")]
                if pid in self.affinities:
                    self.pdb_ids.append(pid)
        print(f"Found {len(self.pdb_ids)} valid complexes in test set")

    def __len__(self): return len(self.pdb_ids)
    def __getitem__(self, i):
        pid = self.pdb_ids[i]
        data = torch.load(os.path.join(self.graph_dir, f"{pid}_combined.pt"), map_location='cpu',weights_only=False)
        aff = torch.tensor([self.affinities[pid]], dtype=torch.float)
        return data, aff, pid

def collate_fn(b):
    d,a,p = zip(*b)
    return Batch.from_data_list(list(d)), torch.stack(a).view(-1), p


def evaluate_ensemble(model_paths):
    print(f"Loading {len(model_paths)} ensemble models...")
    models = []
    for i, path in enumerate(model_paths):
        if not os.path.exists(path):
            raise FileNotFoundError(f"Model not found: {path}")
        model = AffinityGAT(in_channels=34).to(DEVICE)
        model.load_state_dict(torch.load(path, map_location=DEVICE))
        model.eval()
        models.append(model)
        print(f"  [{i+1}/{len(model_paths)}] Loaded {path}")

    dataset = TestDataset(GRAPH_DIR, CSV_FILE)
    loader = DataLoader(dataset, batch_size=BATCH_SIZE, shuffle=False, collate_fn=collate_fn)

    all_pred, all_true, rows = [], [], []
    print("Starting prediction...")
    with torch.no_grad():
        for data, aff, pids in tqdm(loader, desc="Predicting", unit="batch"):
            data = data.to(DEVICE)
            aff = aff.to(DEVICE)

            if data.edge_attr is not None:
                dist = data.edge_attr[:, 0]
                data.edge_attr[:, 0] = (dist - edge_mu) / (edge_sig + 1e-12)

            # Ensemble prediction
            preds = torch.stack([m(data) for m in models]).mean(dim=0)
            pred_pkd = preds * aff_std + aff_mean

            all_pred.extend(pred_pkd.cpu().numpy())
            all_true.extend(aff.cpu().numpy())
            for pid, t, p in zip(pids, aff.cpu().numpy(), pred_pkd.cpu().numpy()):
                rows.append((pid, t, p))

    # Metrics
    all_pred = np.array(all_pred)
    all_true = np.array(all_true)
    rmse = np.sqrt(np.mean((all_pred - all_true)**2))
    rp = np.corrcoef(all_pred, all_true)[0,1]
    mae = np.mean(np.abs(all_pred - all_true))
    sd = np.sqrt(np.mean((all_pred - all_true - (all_pred - all_true).mean())**2))

    # Print results
    print("="*60)
    print("FINAL RESULTS (PDBbind 2016 Core Set)")
    print("="*60)
    print(f"Samples           : {len(all_true)}")
    print(f"RMSE              : {rmse:.4f}")
    print(f"Pearson Rp        : {rp:.4f}")
    print(f"MAE               : {mae:.4f}")
    print(f"SD                : {sd:.4f}")
    print(f"R²                : {rp**2:.4f}")
    print("-"*60)

    # Save results
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    result_file = os.path.join(OUTPUT_CSDIR, f"test_results_{timestamp}.csv")
    with open(result_file, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["pdb_id", "true_pKd", "pred_pKd", "error"])
        for pid, t, p in rows:
            w.writerow([pid, f"{t:.4f}", f"{p:.4f}", f"{p-t:.4f}"])

    summary_file = os.path.join(OUTPUT_CSDIR, "summary.txt")
    with open(summary_file, "w") as f:
        f.write(f"Test Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"Samples: {len(all_true)}\n")
        f.write(f"RMSE: {rmse:.4f}\n")
        f.write(f"Rp: {rp:.4f}\n")
        f.write(f"MAE: {mae:.4f}\n")
        f.write(f"SD: {sd:.4f}\n")
        f.write(f"Models: {', '.join([os.path.basename(p) for p in model_paths])}\n")

    print(f"Detailed results saved to: {result_file}")
    print(f"Summary saved to        : {summary_file}")

if __name__ == "__main__":
    paths = [f"model/affinity_model_{i}.pt" for i in range(3)]
    evaluate_ensemble(paths)
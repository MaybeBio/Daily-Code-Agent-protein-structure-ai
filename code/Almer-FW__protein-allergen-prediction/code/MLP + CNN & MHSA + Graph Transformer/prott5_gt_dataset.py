import hashlib
import re
import torch
from torch.utils.data import Dataset
from pathlib import Path
from Bio import SeqIO
from transformers import T5Tokenizer, T5EncoderModel


def resolve_data_dir() -> Path:
    """
    Locates the directory containing all.train.fasta and all.test.fasta whether they are in:
    - The current script directory (e.g., MLP + CNN & MHSA + Graph Transformer/)
    - ./data or ../data
    - D:/PPLM + Graph Transformer or D:/DeepAlgPro/data
    """
    current_dir = Path(__file__).resolve().parent
    candidates = [
        current_dir,
        current_dir / "data",
        current_dir.parent / "data",
        current_dir.parent / "DeepAlgPro" / "data",
        current_dir.parent.parent / "data",
        Path(r"D:\PPLM + Graph Transformer"),
        Path(r"D:\PPLM + Graph Transformer\data"),
        Path(r"D:\DeepAlgPro\data"),
    ]
    for candidate in candidates:
        if (candidate / "all.train.fasta").exists():
            return candidate
        if candidate.name == "data" and candidate.exists() and candidate.is_dir():
            return candidate
    return current_dir


class ProtT5BatchExtractor:
    """
    Implements Rostlab's official ProtT5-XL extraction workflow using
    self.tokenizer(..., add_special_tokens=True, padding='longest', return_tensors='pt')
    and caches per-residue embeddings [seq_len, 1024] in ./cache_prott5/.
    """
    def __init__(
        self,
        model_name: str = "Rostlab/prot_t5_xl_uniref50",
        device: torch.device = None,
        cache_dir: Path = None,
        extract_batch_size: int = 8,
    ):
        self.device = device or torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.model_name = model_name
        self.extract_batch_size = extract_batch_size
        self.cache_dir = cache_dir or (Path(__file__).resolve().parent / "cache_prott5")
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        self.tokenizer = None
        self.model = None

    def _cache_path(self, rec_id: str, seq: str) -> Path:
        seq_hash = hashlib.md5(seq.encode("utf-8")).hexdigest()[:10]
        safe_id = re.sub(r"[^a-zA-Z0-9_-]", "_", rec_id)
        return self.cache_dir / f"{safe_id}_{seq_hash}_1L.pt"

    def _lazy_load(self):
        if self.model is None:
            print(f"Loading ProtT5-XL Encoder ({self.model_name}) on {self.device}...")
            self.tokenizer = T5Tokenizer.from_pretrained(self.model_name, do_lower_case=False)
            dtype = torch.float16 if self.device.type == "cuda" else torch.float32
            self.model = T5EncoderModel.from_pretrained(self.model_name, torch_dtype=dtype)
            self.model = self.model.to(self.device)
            self.model.eval()

    def unload_from_gpu(self):
        if self.model is not None:
            del self.model
            del self.tokenizer
            self.model = None
            self.tokenizer = None
            if torch.cuda.is_available():
                torch.cuda.empty_cache()

    @torch.no_grad()
    def ensure_dataset_cached(self, records: list):
        """
        Pre-extracts any uncached sequences in batches using Rostlab's official
        tokenization workflow, then unloads ProtT5 from GPU VRAM.
        """
        uncached = [
            (rec_id, seq)
            for rec_id, seq, _ in records
            if not self._cache_path(rec_id, seq).exists()
        ]
        if not uncached:
            return

        self._lazy_load()
        print(f"Caching {len(uncached)} sequences with ProtT5-XL in batches of {self.extract_batch_size}...")

        # Sort by length so padding="longest" within each mini-batch is minimal
        uncached.sort(key=lambda x: len(x[1]))

        for start in range(0, len(uncached), self.extract_batch_size):
            batch_items = uncached[start : start + self.extract_batch_size]
            raw_seqs = [item[1] for item in batch_items]
            seq_lengths = [len(s) for s in raw_seqs]

            # Official Rostlab preprocessing: replace U, Z, O, B with X and space-separate residues
            sequence_examples = [
                " ".join(list(re.sub(r"[UZOB]", "X", seq.upper()))) for seq in raw_seqs
            ]

            ids = self.tokenizer(
                sequence_examples,
                add_special_tokens=True,
                padding="longest",
                return_tensors="pt",
            )
            input_ids = ids["input_ids"].to(self.device)
            attention_mask = ids["attention_mask"].to(self.device)

            embedding_repr = self.model(input_ids=input_ids, attention_mask=attention_mask)

            # Slice [:seq_len] for each sequence in the batch to remove padding & special tokens
            for i, (rec_id, orig_seq) in enumerate(batch_items):
                L = seq_lengths[i]
                emb_i = embedding_repr.last_hidden_state[i, :L].detach().cpu().half()
                torch.save(emb_i, self._cache_path(rec_id, orig_seq))

            done = min(start + self.extract_batch_size, len(uncached))
            if done % 200 == 0 or done == len(uncached):
                print(f"  Cached {done}/{len(uncached)} protein sequences...")

        self.unload_from_gpu()

    def load_cached_features(self, rec_id: str, seq: str) -> torch.Tensor:
        cache_file = self._cache_path(rec_id, seq)
        if not cache_file.exists():
            self.ensure_dataset_cached([(rec_id, seq, 0.0)])
        return torch.load(cache_file, map_location="cpu", weights_only=True).float()


class ProteinGraphTransformerDataset(Dataset):
    def __init__(
        self,
        fasta_path: Path,
        extractor: ProtT5BatchExtractor,
        max_len: int = 1000,
    ):
        self.fasta_path = Path(fasta_path)
        self.extractor = extractor
        self.records = []

        for record in SeqIO.parse(str(self.fasta_path), "fasta"):
            seq_str = str(record.seq).strip()
            if 0 < len(seq_str) <= max_len:
                label = 1.0 if record.id.startswith("allergen") else 0.0
                self.records.append((record.id, seq_str, label))

        print(f"Loaded {len(self.records)} sequences (<= {max_len} aa) from {self.fasta_path.name}")
        self.extractor.ensure_dataset_cached(self.records)

    def __len__(self):
        return len(self.records)

    def __getitem__(self, idx: int):
        rec_id, seq_str, label = self.records[idx]
        x = self.extractor.load_cached_features(rec_id, seq_str)  # [V, 1024]
        y = torch.tensor(label, dtype=torch.float32)
        return x, y, rec_id


def collate_graph_transformer_batch(batch):
    """
    Pads a batch of variable-length residue node feature tensors [V_i, 1024]
    to [B, L_max, 1024] and creates a boolean residue mask [B, L_max] (True = valid residue).
    """
    xs, ys, rec_ids = zip(*batch)
    batch_size = len(xs)
    feat_dim = xs[0].size(-1)
    max_len = max(x.size(0) for x in xs)

    padded_x = torch.zeros((batch_size, max_len, feat_dim), dtype=torch.float32)
    residue_mask = torch.zeros((batch_size, max_len), dtype=torch.bool)

    for i, x in enumerate(xs):
        v_len = x.size(0)
        padded_x[i, :v_len, :] = x
        residue_mask[i, :v_len] = True

    labels = torch.stack(ys, dim=0).view(batch_size, 1)
    return padded_x, residue_mask, labels, list(rec_ids)
from pathlib import Path
import re
import numpy as np
import torch

# 20 Standard Amino Acids
AA_LIST = "ACDEFGHIKLMNPQRSTVWY"
AA_TO_IDX = {aa: idx for idx, aa in enumerate(AA_LIST)}

# Standard BLOSUM62 Substitution Matrix (20x20 in AA_LIST order)
# Used as a single-step fallback when precomputed PSI-BLAST descriptor files are not provided.
BLOSUM62_MATRIX = np.array([
    # A   C   D   E   F   G   H   I   K   L   M   N   P   Q   R   S   T   V   W   Y
    [ 4,  0, -2, -1, -2,  0, -2, -1, -1, -1, -1, -2, -1, -1, -1,  1,  0,  0, -3, -2],  # A
    [ 0,  9, -3, -4, -2, -3, -3, -1, -3, -1, -1, -3, -3, -3, -3, -1, -1, -1, -2, -2],  # C
    [-2, -3,  6,  2, -3, -1, -1, -3, -1, -4, -3,  1, -1,  0, -2,  0, -1, -3, -4, -3],  # D
    [-1, -4,  2,  5, -3, -2,  0, -3,  1, -3, -2,  0, -1,  2,  0,  0, -1, -2, -3, -2],  # E
    [-2, -2, -3, -3,  6, -3, -1,  0, -3,  0,  0, -3, -4, -3, -3, -2, -2, -1,  1,  3],  # F
    [ 0, -3, -1, -2, -3,  6, -2, -4, -2, -4, -3,  0, -2, -2, -2,  0, -2, -3, -2, -3],  # G
    [-2, -3, -1,  0, -1, -2,  8, -3, -1, -3, -2,  1, -2,  0,  0, -1, -2, -3, -2,  2],  # H
    [-1, -1, -3, -3,  0, -4, -3,  4, -3,  2,  1, -3, -3, -3, -3, -2, -1,  3, -3, -1],  # I
    [-1, -3, -1,  1, -3, -2, -1, -3,  5, -2, -1,  0, -1,  1,  2,  0, -1, -2, -3, -2],  # K
    [-1, -1, -4, -3,  0, -4, -3,  2, -2,  4,  2, -3, -3, -2, -2, -2, -1,  1, -2, -1],  # L
    [-1, -1, -3, -2,  0, -3, -2,  1, -1,  2,  5, -2, -2,  0, -1, -1, -1,  1, -1, -1],  # M
    [-2, -3,  1,  0, -3,  0,  1, -3,  0, -3, -2,  6, -2,  0,  0,  1,  0, -3, -4, -2],  # N
    [-1, -3, -1, -1, -4, -2, -2, -3, -1, -3, -2, -2,  7, -1, -2, -1, -1, -2, -4, -3],  # P
    [-1, -3,  0,  2, -3, -2,  0, -3,  1, -2,  0,  0, -1,  5,  1,  0, -1, -2, -2, -1],  # Q
    [-1, -3, -2,  0, -3, -2,  0, -3,  2, -2, -1,  0, -2,  1,  5, -1, -1, -3, -3, -2],  # R
    [ 1, -1,  0,  0, -2,  0, -1, -2,  0, -2, -1,  1, -1,  0, -1,  4,  1, -2, -3, -2],  # S
    [ 0, -1, -1, -1, -2, -2, -2, -1, -1, -1, -1,  0, -1, -1, -1,  1,  5,  0, -2, -2],  # T
    [ 0, -1, -3, -2, -1, -3, -3,  3, -2,  1,  1, -3, -2, -2, -3, -2,  0,  4, -3, -1],  # V
    [-3, -2, -4, -3,  1, -2, -2, -3, -3, -2, -1, -4, -4, -2, -3, -3, -2, -3, 11,  2],  # W
    [-2, -2, -3, -2,  3, -3,  2, -1, -2, -1, -1, -2, -3, -1, -2, -2, -2, -1,  2,  7],  # Y
], dtype=np.float32)

_TRIU_I, _TRIU_J = np.triu_indices(20)


def _norm_seq(seq: str) -> str:
    return re.sub(r"[^A-Z]", "", seq.strip().upper())


def get_blosum62_profile(seq: str) -> tuple[np.ndarray, np.ndarray]:
    seq_indices = np.array([AA_TO_IDX.get(ch, 0) for ch in seq], dtype=np.int64)
    raw_blosum = BLOSUM62_MATRIX[seq_indices]
    profile = 1.0 / (1.0 + np.exp(-raw_blosum))
    return seq_indices, profile


def compute_pssm400(seq_indices: np.ndarray, pssm: np.ndarray) -> np.ndarray:
    out = np.zeros((20, 20), dtype=np.float32)
    for aa_idx in range(20):
        mask = seq_indices == aa_idx
        if np.any(mask):
            out[aa_idx] = pssm[mask].mean(axis=0)
    return out.reshape(-1)


def compute_dpc_pssm(pssm: np.ndarray) -> np.ndarray:
    L = pssm.shape[0]
    if L < 2:
        return np.zeros(400, dtype=np.float32)
    dpc = (pssm[:-1].T @ pssm[1:]) / float(L - 1)
    return dpc.astype(np.float32).reshape(-1)


def compute_dfmca_pssm(pssm: np.ndarray) -> np.ndarray:
    L = pssm.shape[0]
    if L < 2:
        return np.zeros(210, dtype=np.float32)
    centered = pssm - pssm.mean(axis=0, keepdims=True)
    cov = (centered.T @ centered) / float(L)
    return cov[_TRIU_I, _TRIU_J].astype(np.float32)


def compute_single_average(seq_indices: np.ndarray, pssm: np.ndarray) -> np.ndarray:
    L = max(pssm.shape[0], 1)
    out = np.zeros((20, 20), dtype=np.float32)
    for aa_idx in range(20):
        mask = seq_indices == aa_idx
        if np.any(mask):
            out[aa_idx] = pssm[mask].sum(axis=0) / float(L)
    return out.reshape(-1)


def extract_four_pssm_descriptors(seq: str) -> torch.Tensor:
    """
    Single-step BLOSUM62 extraction of the 4 evolutionary descriptors (1,410 dims):
      PSSM400 (400) + DPC_PSSM (400) + DFMCA_PSSM (210) + Single_Average (400).
    """
    seq_clean = _norm_seq(seq)
    seq_indices, pssm = get_blosum62_profile(seq_clean)
    combined = np.concatenate([
        compute_pssm400(seq_indices, pssm),
        compute_dpc_pssm(pssm),
        compute_dfmca_pssm(pssm),
        compute_single_average(seq_indices, pssm),
    ], axis=0)
    return torch.from_numpy(combined).float()


def _read_sequence_lines(seq_file: Path) -> list[str]:
    """
    Reads autoBioSeqpy sequence files (trpos2840.txt, trneg2840.txt, tepos710.txt, teneg710.txt).
    Supports both multi-line FASTA format and raw one-sequence-per-line text.
    """
    with open(seq_file, "r", encoding="utf-8", errors="ignore") as f:
        lines = [raw.strip() for raw in f if raw.strip()]

    if any(line.startswith(">") for line in lines):
        seqs, cur = [], []
        for line in lines:
            if line.startswith(">"):
                if cur:
                    seqs.append(_norm_seq("".join(cur)))
                    cur = []
            else:
                cur.append(line)
        if cur:
            seqs.append(_norm_seq("".join(cur)))
        return seqs

    return [_norm_seq(line) for line in lines]


def _read_numeric_matrix(feat_file: Path, expected_dim: int) -> np.ndarray:
    """
    Reads an autoBioSeqpy 'other' feature file (CSV, TSV, or whitespace-separated).
    Supports header rows (#name,V1,...) and leading textual sample-ID columns
    (e.g. trpos2840.txt_allergen_93,8.6,3.2,...).
    """
    rows = []
    with open(feat_file, "r", encoding="utf-8", errors="ignore") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            tokens = [t for t in re.split(r"[\s,;]+", line) if t]
            if len(tokens) == expected_dim + 1:
                # Drop leading sample-ID / index / label column (textual or numeric)
                tokens = tokens[1:]
            try:
                vals = [float(t) for t in tokens]
            except ValueError:
                # Skip header row (e.g., name,V1,V2,...)
                continue
            if len(vals) != expected_dim:
                raise ValueError(
                    f"Expected {expected_dim} features per row in {feat_file.name}, got {len(vals)}"
                )
            rows.append(vals)
    return np.asarray(rows, dtype=np.float32)


def load_multimodal_algpro_lookup(algpro_dir: Path) -> dict[str, torch.Tensor]:
    """
    Loads the top 4 precomputed PSI-BLAST descriptors from Multimodal-AlgPro's
    'Independent' folder (trpo/trne/tepo/tene) and maps each normalized protein
    sequence to its 1,410-dim concatenated vector:
      [PSSM400 (400), DPC_PSSM (400), DFMCA_PSSM (210), Single_Average (400)].
    """
    algpro_dir = Path(algpro_dir)
    splits = [
        ("trpos2840.txt", "trpo"),
        ("trneg2840.txt", "trne"),
        ("tepos710.txt", "tepo"),
        ("teneg710.txt", "tene"),
    ]
    desc_specs = [
        ("pssm400", 400),
        ("dpc_pssm", 400),
        ("DFMCA_PSSM", 210),
        ("single_Average", 400),
    ]

    seq_to_vec: dict[str, torch.Tensor] = {}
    for seq_fname, prefix in splits:
        seq_path = algpro_dir / seq_fname
        if not seq_path.exists():
            raise FileNotFoundError(f"Missing Multimodal-AlgPro sequence file: {seq_path}")
        seqs = _read_sequence_lines(seq_path)

        mats = []
        for suffix, dim in desc_specs:
            feat_path = algpro_dir / f"{prefix}-{suffix}.txt"
            if not feat_path.exists():
                raise FileNotFoundError(f"Missing Multimodal-AlgPro descriptor file: {feat_path}")
            mat = _read_numeric_matrix(feat_path, expected_dim=dim)
            if len(mat) != len(seqs):
                raise ValueError(
                    f"Row count mismatch in {feat_path.name}: {len(mat)} rows vs {len(seqs)} in {seq_fname}"
                )
            mats.append(mat)

        combined = np.concatenate(mats, axis=1)  # [N, 1410]
        for seq_str, vec in zip(seqs, combined):
            seq_to_vec[seq_str] = torch.from_numpy(vec.copy()).float()

    print(f"Loaded {len(seq_to_vec)} sequence->1410-dim descriptor mappings from {algpro_dir}")
    return seq_to_vec
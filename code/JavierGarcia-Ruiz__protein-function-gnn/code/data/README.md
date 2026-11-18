# PDB Enzyme Commission (EC) Structure Benchmark Data

This directory contains the curated experimental protein 3D backbone structures, spatial contact graphs, and multi-label Enzyme Commission (EC) functional annotations built from **4,709 real crystal enzyme chains** combining **CATH 4.2 coordinates**, **RCSB GraphQL `rcsb_ec_lineage` annotations**, and **RCSB 30% sequence-identity clusters** (chains `40–500 aa` with $\ge 85\%$ resolved crystal density).

## Partition Details (<30% Sequence Identity)
To evaluate genuine structural and functional generalization rather than sequence memorization, the dataset is clustered and partitioned strictly at **<30% sequence identity** (`0` cluster overlap across splits):
- **Total Experimental Chains**: `4,709` crystal enzyme chains
- **Training Set**: `3,578` enzyme chains
- **Validation Set**: `443` enzyme chains
- **Held-Out Test Set**: `688` enzyme chains (`<30%` sequence identity and `0` cluster overlap with training/validation)

## File Manifest
- `raw/ec_pdb_splits.csv`: Curated metadata including PDB chain ID, amino acid sequence, sequence length, split partition (`train`, `val`, `test`), EC annotations, and flattened $C_\alpha$ 3D coordinate strings.
- `raw/ec_pdb_splits.npz`: Compressed packed NumPy archive containing pre-parsed sequence arrays, coordinate matrices (`(L, 3)`), and annotation labels for high-throughput loading.

## Hierarchical EC Nomenclature
Benchmark annotations cover the **Top-25 populated fine-grained EC subclasses** spanning the **5 primary EC divisions** represented in the dataset:
1. `EC 1`: Oxidoreductases
2. `EC 2`: Transferases
3. `EC 3`: Hydrolases
4. `EC 4`: Lyases
5. `EC 6`: Ligases

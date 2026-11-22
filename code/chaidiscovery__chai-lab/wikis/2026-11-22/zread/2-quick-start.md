

Get Chai-1 running in minutes. This page walks you through **installation**, **preparing your first input**, **running a structure prediction**, and **interpreting the output** — everything you need to go from zero to your first predicted structure. No prior experience with Chai-1 is assumed.

![performance](https://github.com/chaidiscovery/chai-lab/blob/main/assets/performance_barplot.png?raw=true)

Sources: [README.md](/README.md#L1-L194), [__init__.py](/chai_lab/__init__.py#L1-L6)

## Prerequisites and Installation

Chai-1 requires **Linux**, **Python ≥ 3.10**, and an **NVIDIA GPU with CUDA and bfloat16 support**. The model weights are downloaded automatically on first use. The table below summarizes the hardware landscape:

| GPU | VRAM | Suitability |
|-----|------|-------------|
| H100 80GB / A100 80GB | 80 GB | ✅ Recommended — handles large complexes comfortably |
| L40S | 48 GB | ✅ Recommended — good for most complexes |
| A10 / A30 | 24 GB | ⚠️ Works for smaller complexes only |
| RTX 4090 | 24 GB | ⚠️ Community-verified for smaller complexes |

> [!TIP]
> Set the `CHAI_DOWNLOADS_DIR` environment variable to control where model weights are stored (e.g., on a mounted drive in Docker). Without it, weights land in your Python site-packages directory.

Install the stable release from PyPI:

```bash
pip install chai_lab==0.6.1
```

Or install the latest development version directly from GitHub:

```bash
pip install git+https://github.com/chaidiscovery/chai-lab.git
```

The `chai-lab` command-line tool is registered automatically via the `chai-lab` console script entry point, which maps to `chai_lab.main:cli`.

Sources: [README.md](/README.md#L21-L35), [pyproject.toml](/pyproject.toml#L1-L73), [Dockerfile.chailab](/Dockerfile.chailab#L1-L85), [requirements.in](/requirements.in#L1-L32)

## Your First Prediction — The Flow

The entire prediction workflow follows a clear pipeline from input to ranked output structures. Here is what happens at each stage:

```mermaid
flowchart LR
    A["📝 Prepare FASTA"] --> B["🚀 Run Inference"]
    B --> C["⚙️ Feature Assembly"]
    C --> D["🔁 Trunk Recycles"]
    D --> E["🌀 Diffusion Denoising"]
    E --> F["📊 Confidence Scoring"]
    F --> G["🏆 Rank & Export CIF"]
```

1. **Prepare FASTA** — Define your protein, ligand, RNA, DNA, or glycan entities in a FASTA-like format.
2. **Run Inference** — Call `chai-lab fold` (CLI) or `run_inference()` (Python).
3. **Feature Assembly** — The system constructs the `AllAtomFeatureContext`, generating ESM embeddings, loading MSAs, and assembling restraints.
4. **Trunk Recycles** — The trunk model iterates on token-level representations (default: 3 recycles).
5. **Diffusion Denoising** — A stochastic denoising process generates 3D atomic coordinates (default: 200 timesteps, 5 samples).
6. **Confidence Scoring** — pAE, pDE, and pLDDT are predicted for each sample.
7. **Rank & Export** — Samples are ranked by aggregate score and written as `.cif` files.

Sources: [chai1.py](/chai_lab/chai1.py#L500-L545), [chai1.py](/chai_lab/chai1.py#L700-L830)

## Preparing Input — The FASTA Format

Chai-1 uses a **FASTA-like format** where each entity (protein, ligand, DNA, RNA, or glycan) is specified as a separate entry. The header line encodes the **entity type** and a **unique name**; the sequence line provides the residue string or SMILES.

### Header Syntax

```
>{entity_type}|name={unique_name}
```

### Entity Types and Sequence Formats

| Entity Type | Header Prefix | Sequence Content | Example |
|-------------|--------------|------------------|---------|
| Protein | `protein` | Amino acid one-letter codes | `AGSHSMRYFSTSVSRPGRGE...` |
| Ligand | `ligand` | SMILES string | `CCCCCCCCCCCCCC(=O)O` |
| DNA | `dna` | Nucleotide one-letter codes | `ATCGATCG` |
| RNA | `rna` | Nucleotide one-letter codes | `AUCGAUCG` |
| Glycan | `glycan` | Glycan notation (e.g., `NAG(4-1 NAG)`) | `NAG(4-1 NAG)` |

Modified residues are encoded inline using parenthetical notation within a protein sequence, e.g., `AAA(SEP)AAA` for phosphoserine at that position.

### Complete Example

```fasta
>protein|name=example-of-long-protein
AGSHSMRYFSTSVSRPGRGEPRFIAVGYVDDTQFVRFDSDAASPRGEPRAPWVEQEGPEYWDRETQKYKRQAQTDRVSLRNLRGYYNQSEAGSHTLQWMFGCDLGPDGRLLRGYDQSAYDGKDYIALNEDLRSWTAADTAAQITQRKWEAAREAEQRRAYLEGTCVEWLRRYLENGKETLQRAEHPKTHVTHHPVSDHEATLRCWALGFYPAEITLTWQWDGEDQTQDTELVETRPAGDGTFQKWAAVVVPSGEEQRYTCHVQHEGLPEPLTLRWEP
>protein|name=example-of-short-protein
AIQRTPKIQVYSRHPAENGKSNFLNCYVSGFHPSDIEVDLLKNGERIEKVEHSDLSFSKDWSFYLLYYTEFTPTEKDEYACRVNHVTLSQPKIVKWDRDM
>protein|name=example-peptide
GAAL
>ligand|name=example-ligand-as-smiles
CCCCCCCCCCCCCC(=O)O
```

> [!TIP]
> Every entity must have a **unique name**. Duplicate names will raise an `UnsupportedInputError` at runtime. Keep names descriptive — they are used for chain naming in output CIF files when `fasta_names_as_cif_chains=True`.

Sources: [predict_structure.py](/examples/predict_structure.py#L1-L57), [inference_dataset.py](/chai_lab/data/dataset/inference_dataset.py#L1-L80), [1ac5.fasta](/examples/covalent_bonds/1ac5.fasta#L1-L6), [8cyo.fasta](/examples/covalent_bonds/8cyo.fasta#L1-L4), [chai1.py](/chai_lab/chai1.py#L340-L365)

## Running Predictions

### Option A: Command Line Interface

The simplest way to fold a complex is via the `chai-lab fold` command:

```bash
chai-lab fold input.fasta output_folder
```

This uses **default settings**: 5 diffusion samples, ESM embeddings enabled, no MSAs, no templates. For improved accuracy, enable MSA and template generation via the ColabFold MMseqs2 server:

```bash
chai-lab fold --use-msa-server --use-templates-server input.fasta output_folder
```

If you host your own ColabFold server, point to it with `--msa-server-url`:

```bash
chai-lab fold --use-msa-server --msa-server-url "https://api.internalcolabserver.com" input.fasta output_folder
```

The CLI also provides utility commands:

| Command | Purpose |
|---------|---------|
| `chai-lab fold` | Run structure prediction |
| `chai-lab a3m-to-pqt` | Convert A3M MSA files to aligned Parquet format |
| `chai-lab citation` | Print citation information |

For full parameter documentation, see [CLI Reference](3-cli-reference).

Sources: [README.md](/README.md#L37-L65), [main.py](/chai_lab/main.py#L1-L49)

### Option B: Python API

For programmatic control, use the `chai_lab.chai1.run_inference` function. This is the primary entry point for Python-based workflows:

```python
from pathlib import Path
from chai_lab.chai1 import run_inference

candidates = run_inference(
    fasta_file=Path("input.fasta"),
    output_dir=Path("output_folder"),
    # Core inference parameters
    num_trunk_recycles=3,       # Number of trunk recycles
    num_diffn_timesteps=200,    # Diffusion denoising steps
    num_diffn_samples=5,        # Number of structure samples
    seed=42,                    # Reproducibility seed
    device="cuda:0",            # Target GPU device
    # Feature sources
    use_esm_embeddings=True,    # ESM protein embeddings
    use_msa_server=False,       # Auto-generate MSAs via ColabFold
    msa_directory=None,         # Or provide pre-computed MSAs
    use_templates_server=False, # Auto-generate templates
    constraint_path=None,       # Restraints file path
)
```

The returned `StructureCandidates` object provides direct access to predictions and scores:

```python
# Get CIF file paths for all samples
cif_paths = candidates.cif_paths

# Get aggregate confidence scores
agg_scores = [rd.aggregate_score.item() for rd in candidates.ranking_data]

# Load per-sample detailed scores (pTM, ipTM, pLDDT, clash)
import numpy as np
scores = np.load("output_folder/scores.model_idx_0.npz")
```

Sources: [chai1.py](/chai_lab/chai1.py#L500-L545), [predict_structure.py](/examples/predict_structure.py#L1-L57), [chai1.py](/chai_lab/chai1.py#L280-L310)

### Key Inference Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `num_trunk_recycles` | 3 | Iterations of the trunk model; more recycles can improve accuracy at cost of time |
| `num_diffn_timesteps` | 200 | Steps in the diffusion denoising schedule |
| `num_diffn_samples` | 5 | Number of independent structure samples generated |
| `num_trunk_samples` | 1 | Number of independent trunk samples (each generates `num_diffn_samples` structures) |
| `seed` | None | Random seed for reproducibility |
| `device` | `"cuda:0"` | CUDA device string |
| `use_esm_embeddings` | True | Use ESM-2 protein language model embeddings |
| `use_msa_server` | False | Generate MSAs via ColabFold MMseqs2 server |
| `msa_directory` | None | Path to directory with pre-computed `.aligned.pqt` MSA files |
| `use_templates_server` | False | Generate structural templates via ColabFold server |
| `constraint_path` | None | Path to restraints CSV file |
| `low_memory` | True | Optimize for GPU memory by offloading intermediate tensors to CPU |

Sources: [chai1.py](/chai_lab/chai1.py#L500-L530)

## Understanding the Output

After a successful run, the output directory contains the following files for each of the `num_diffn_samples` predictions:

| File | Content |
|------|---------|
| `pred.model_idx_{N}.cif` | Predicted 3D structure in mmCIF format, with pLDDT as B-factors (0–100 scale) |
| `scores.model_idx_{N}.npz` | NumPy archive with pTM, ipTM, pLDDT, and clash metrics |
| `msa_depth.pdf` | (If MSAs were used) Coverage plot of MSA depth per position |

The **`StructureCandidates`** object returned by `run_inference` provides:

| Attribute | Type | Description |
|-----------|------|-------------|
| `cif_paths` | `list[Path]` | Paths to all candidate CIF files |
| `ranking_data` | `list[SampleRanking]` | Ranking scores per candidate, including `aggregate_score` |
| `pae` | `Tensor [candidates, tokens, tokens]` | Predicted Aligned Error matrix |
| `pde` | `Tensor [candidates, tokens, tokens]` | Predicted Distance Error matrix |
| `plddt` | `Tensor [candidates, tokens]` | Per-token pLDDT confidence |
| `msa_coverage_plot_path` | `Path or None` | Path to MSA coverage PDF, if applicable |

Call `candidates.sorted()` to reorder results from highest to lowest aggregate confidence score. The candidate with the **highest `aggregate_score`** is the model's best prediction.

Sources: [chai1.py](/chai_lab/chai1.py#L280-L330), [chai1.py](/chai_lab/chai1.py#L960-L1060), [predict_structure.py](/examples/predict_structure.py#L44-L57)

## Common Use Cases at a Glance

The `examples/` directory provides ready-to-run scripts for each scenario. Here is a quick reference:

| Use Case | Example Script | Key Configuration |
|----------|---------------|-------------------|
| Basic folding | `examples/predict_structure.py` | `use_esm_embeddings=True` (defaults) |
| With MSAs (pre-computed) | `examples/msas/predict_with_msas.py` | `msa_directory=Path(...)` |
| With MSAs (auto-generated) | CLI only | `--use-msa-server` flag |
| With templates | `examples/templates/predict_with_templates.py` | `use_msa_server=True, use_templates_server=True` |
| With contact restraints | `examples/restraints/predict_with_restraints.py` | `constraint_path=Path("contact.restraints")` |
| With pocket restraints | `examples/restraints/predict_with_restraints.py` | `constraint_path=Path("pocket.restraints")` |
| Covalent ligands | `examples/covalent_bonds/predict_covalent_ligand.py` | `constraint_path=Path("8cyo.restraints")` |
| Glycosylated proteins | `examples/covalent_bonds/predict_glycosylated.py` | `glycan` entity type + restraints |

Sources: [predict_structure.py](/examples/predict_structure.py#L1-L57), [predict_with_msas.py](/examples/msas/predict_with_msas.py#L1-L46), [predict_with_restraints.py](/examples/restraints/predict_with_restraints.py#L1-L36), [predict_with_templates.py](/examples/templates/predict_with_templates.py#L1-L31), [predict_covalent_ligand.py](/examples/covalent_bonds/predict_covalent_ligand.py#L1-L28)

## Troubleshooting

| Problem | Cause | Solution |
|---------|-------|----------|
| `UnsupportedInputError: Too many tokens` | Input exceeds maximum model token limit | Reduce sequence length or number of entities |
| `Output directory is not empty` | `run_inference` requires an empty output directory | Delete or use a new directory path |
| `Duplicate entity name` | Two entities share the same `name=` value | Assign unique names to every entity |
| CUDA out of memory | Complex too large for GPU VRAM | Set `low_memory=True` (default), reduce `num_diffn_samples`, or use a larger GPU |
| MSA server timeout | ColabFold shared server is overloaded | Retry later, or host your own MMseqs2 server and use `--msa-server-url` |
| Weights download failure | Network or storage issue | Set `CHAI_DOWNLOADS_DIR` to a writable path with sufficient disk space |

Sources: [chai1.py](/chai_lab/chai1.py#L236-L260), [chai1.py](/chai_lab/chai1.py#L510-L515), [README.md](/README.md#L78-L85)

## Next Steps

You now have Chai-1 installed and can run basic predictions. Here is the recommended reading path to deepen your understanding:

1. **[CLI Reference](3-cli-reference)** — Complete parameter documentation for the `chai-lab fold` command and all CLI utilities.
2. **[FASTA Parsing and Entity Types](13-fasta-parsing-and-entity-types)** — Deep dive into the input format, including modified residues and advanced entity configurations.
3. **[MSA Generation and Loading](14-msa-generation-and-loading)** — How to provide pre-computed MSAs or generate them automatically for improved accuracy.
4. **[Restraint and Covalent Bond System](17-restraint-and-covalent-bond-system)** — Guide experimental predictions with contact, pocket, and covalent bond restraints.
5. **[Architecture Overview](7-architecture-overview)** — Understand the full inference pipeline from feature assembly through diffusion to confidence scoring.

For the latest features and known issues, see [Latest Updates](4-latest-updates) and [Issues and Feedbacks](5-issues-and-feedbacks).

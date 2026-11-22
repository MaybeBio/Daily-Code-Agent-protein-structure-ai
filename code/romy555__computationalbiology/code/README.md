# Biotech & Bioinformatics Projects

Fourteen computational biology projects on **real biological data**: virus genomes, human variants, TCGA tumour transcriptomes, single-cell data, protein structures and families, and ChEMBL drug and bioactivity data. The core algorithms are written from scratch (sequence alignment, tree building, genome assembly, read mapping, variant calling, differential expression, coevolution analysis, molecular dynamics) and every model is validated honestly: leakage checks, scaffold splits, false-discovery control and population-structure correction.

| Area | # | Project | Highlights |
|---|---|---|---|
| **Bioinformatics** | 01 | [Reading a virus genome](https://github.com/romy555/computationalbiology/blob/HEAD/bioinformatics/01-sequences) | ORF gene finder recovers **11 of 12** SARS-CoV-2 genes |
| | 02 | [Sequence alignment from scratch](https://github.com/romy555/computationalbiology/blob/HEAD/bioinformatics/02-alignment) | Needleman–Wunsch, Smith–Waterman, BLOSUM62; SARS-CoV-1 vs 2 spike **78%** identical |
| | 03 | [Phylogenetics of coronaviruses](https://github.com/romy555/computationalbiology/blob/HEAD/bioinformatics/03-phylogenetics) | Neighbour joining from scratch; closest relative of SARS-CoV-2 is bat **RaTG13** |
| | 04 | [Genome assembly and read mapping](https://github.com/romy555/computationalbiology/blob/HEAD/bioinformatics/04-assembly) | De Bruijn assembler; mapper places **97.5%** of reads correctly; 4/4 variants called |
| | 05 | [Variants and population genomics](https://github.com/romy555/computationalbiology/blob/HEAD/bioinformatics/05-variants) | Hardy–Weinberg, LD, GWAS with PCA correction, polygenic scores |
| **Omics & ML** | 06 | [Differential expression in breast cancer](https://github.com/romy555/computationalbiology/blob/HEAD/omics/06-rnaseq) | 200 TCGA tumours; BH-FDR; proliferation enrichment p = **2.7 × 10⁻¹³** |
| | 07 | [Single-cell RNA-seq of blood cells](https://github.com/romy555/computationalbiology/blob/HEAD/omics/07-single-cell) | 2,700 cells → QC, PCA, clustering, t-SNE, annotated cell types |
| | 08 | [ML for breast cancer subtypes](https://github.com/romy555/computationalbiology/blob/HEAD/omics/08-ml-cancer) | **90.4%** 4-class accuracy; leakage demo (42.9% on random labels) |
| | 09 | [A CNN that finds DNA binding sites](https://github.com/romy555/computationalbiology/blob/HEAD/omics/09-deep-dna) | 625-parameter PyTorch CNN, **97.3%** accuracy; learned filter = real CTCF motif |
| | 10 | [Protein contacts from coevolution](https://github.com/romy555/computationalbiology/blob/HEAD/omics/10-protein-ml) | Direct coupling analysis on 1,500 ubiquitin sequences |
| **Drug discovery** | 11 | [Protein structure and the EGFR drug pocket](https://github.com/romy555/computationalbiology/blob/HEAD/drug-discovery/11-structure) | Erlotinib pocket: 17 residues, mostly hydrophobic |
| | 12 | [Molecular dynamics from scratch](https://github.com/romy555/computationalbiology/blob/HEAD/drug-discovery/12-molecular-dynamics) | Velocity Verlet; energy drift **0.03%** over 2,000 steps |
| | 13 | [Cheminformatics on approved drugs](https://github.com/romy555/computationalbiology/blob/HEAD/drug-discovery/13-cheminformatics) | 3,311 drugs: fingerprints, similarity search, Lipinski and PAINS filters |
| | 14 | [QSAR and virtual screening for EGFR](https://github.com/romy555/computationalbiology/blob/HEAD/drug-discovery/14-qsar) | 607 inhibitors; scaffold-split R² **0.65**; classifier AUC **0.90** |

**Tools:** Python · NumPy · pandas · SciPy · scikit-learn · PyTorch · Biopython · RDKit · Matplotlib

---

## Bioinformatics

<table>
<tr>
<td width="50%"><img src="https://github.com/romy555/computationalbiology/raw/HEAD/bioinformatics/01-sequences/images/orf_map.png" alt="ORF predictions against annotated genes"><br><b>01 · Reading a virus genome.</b> GC content and skew, k-mer statistics (CTAG is 20× rarer than chance) and a six-frame ORF gene finder tested against the annotated SARS-CoV-2 genes: 11 of 12 recovered; long ORFs appear 9× in the real genome vs once in a shuffled one.</td>
<td width="50%"><img src="https://github.com/romy555/computationalbiology/raw/HEAD/bioinformatics/02-alignment/images/spike_align.png" alt="Identity along the spike alignment"><br><b>02 · Sequence alignment from scratch.</b> Dynamic-programming global and local alignment, BLOSUM62, affine gaps, dot plots, BLAST-style seeding (a real gene gets 66× more seed hits than random DNA) and a globin multiple alignment. SARS-CoV-1 vs SARS-CoV-2 spike: 78% identity, with a variable receptor-binding region.</td>
</tr>
<tr>
<td><img src="https://github.com/romy555/computationalbiology/raw/HEAD/bioinformatics/03-phylogenetics/images/corona_tree.png" alt="Neighbour-joining tree of coronaviruses"><br><b>03 · Phylogenetics of coronaviruses.</b> Jukes–Cantor distances, UPGMA and neighbour joining from scratch, alignment-free k-mer distances between whole genomes and bootstrap branch support. SARS-CoV-2's nearest relatives: bat RaTG13, then pangolin CoV.</td>
<td><img src="https://github.com/romy555/computationalbiology/raw/HEAD/bioinformatics/04-assembly/images/coverage_n50.png" alt="Assembly N50 against coverage"><br><b>04 · Genome assembly and read mapping.</b> FASTQ reads with Phred qualities, a de Bruijn graph assembler, why repeats longer than k break assemblies, N50 against coverage (one contig from 20×), a k-mer index mapper (97.5% of reads placed correctly) and pileup variant calling (4 of 4 found).</td>
</tr>
<tr>
<td><img src="https://github.com/romy555/computationalbiology/raw/HEAD/bioinformatics/05-variants/images/manhattan.png" alt="Manhattan plots with and without population structure"><br><b>05 · Variants and population genomics.</b> Genotype calling from read depth, real 1000 Genomes allele frequencies (sickle-cell, APOE, MTHFR), Hardy–Weinberg QC, linkage disequilibrium and a GWAS where hidden ancestry creates false hits; the first principal component (|r| = 0.94 with ancestry) removes them.</td>
<td></td>
</tr>
</table>

## Omics and machine learning

<table>
<tr>
<td width="50%"><img src="https://github.com/romy555/computationalbiology/raw/HEAD/omics/06-rnaseq/images/volcano.png" alt="Volcano plot, Basal vs Luminal A"><br><b>06 · Differential expression in breast cancer.</b> 5,993 genes × 200 TCGA tumours: normalisation, overdispersion (negative binomial), per-gene tests, Benjamini–Hochberg FDR, a volcano plot (ESR1, FOXA1, GATA3 up in Luminal; FOXM1, KRT5 up in Basal) and a hypergeometric enrichment test for proliferation genes.</td>
<td width="50%"><img src="https://github.com/romy555/computationalbiology/raw/HEAD/omics/07-single-cell/images/tsne.png" alt="t-SNE of 2,700 blood cells"><br><b>07 · Single-cell RNA-seq.</b> The 10x PBMC3k data (97.4% zeros): QC keeps 2,638 cells, 2,000 highly variable genes, PCA, clustering and t-SNE, then marker genes name the clusters as T cells, monocytes, NK cells, B cells and platelets.</td>
</tr>
<tr>
<td><img src="https://github.com/romy555/computationalbiology/raw/HEAD/omics/08-ml-cancer/images/confusion.png" alt="Subtype confusion matrix"><br><b>08 · ML for breast cancer subtypes.</b> 408 tumours, four PAM50 subtypes. On random labels, leaky feature selection reports 42.9% (chance is 25%); the honest pipeline gives 27.4%. Real task: L1 logistic regression 90.4% ± 2.1%, mistakes mostly LumA ↔ LumB, and the genes it uses are biologically sensible.</td>
<td><img src="https://github.com/romy555/computationalbiology/raw/HEAD/omics/09-deep-dna/images/learned_motif.png" alt="Real CTCF motif and the learned filter"><br><b>09 · A CNN that finds DNA binding sites.</b> One-hot DNA into a 625-parameter convolutional network in PyTorch: 97.3% test accuracy at detecting CTCF sites, and the learned filter read back as a sequence logo matches the real JASPAR motif (correlation 1.00).</td>
</tr>
<tr>
<td><img src="https://github.com/romy555/computationalbiology/raw/HEAD/omics/10-protein-ml/images/contacts.png" alt="Predicted contacts against the structure"><br><b>10 · Protein contacts from coevolution.</b> 1,500 ubiquitin-family sequences (Pfam): conservation, sequence reweighting, mutual information and direct coupling analysis to predict 3D contacts from sequence alone, checked against the crystal structure (top-20 precision 40%): the idea behind AlphaFold's MSA input.</td>
<td></td>
</tr>
</table>

## Structure, chemistry and drug discovery

<table>
<tr>
<td width="50%"><img src="https://github.com/romy555/computationalbiology/raw/HEAD/drug-discovery/11-structure/images/contact_map.png" alt="Contact map of EGFR"><br><b>11 · Protein structure and the EGFR drug pocket.</b> PDB parsing, secondary structure from Cα geometry (64% helix), contact maps, the 17-residue erlotinib pocket (hydropathy +0.74 vs −0.18 for the whole protein), ligand-free pocket detection by burial, and RMSD superposition.</td>
<td width="50%"><img src="https://github.com/romy555/computationalbiology/raw/HEAD/drug-discovery/12-molecular-dynamics/images/energy.png" alt="Energy conservation in molecular dynamics"><br><b>12 · Molecular dynamics from scratch.</b> Lennard-Jones forces, velocity Verlet (0.03% energy drift; a too-large time step blows up), a thermostat, radial distribution functions of solid and liquid, and diffusion coefficients.</td>
</tr>
<tr>
<td><img src="https://github.com/romy555/computationalbiology/raw/HEAD/drug-discovery/13-cheminformatics/images/chemical_space.png" alt="Chemical space of approved drugs"><br><b>13 · Cheminformatics on approved drugs.</b> 3,311 ChEMBL drugs with RDKit: descriptors, Morgan fingerprints, Tanimoto similarity search (nearest drugs to imatinib), PCA of chemical space, and filters (86% pass Lipinski, 5.6% match a PAINS alert).</td>
<td><img src="https://github.com/romy555/computationalbiology/raw/HEAD/drug-discovery/14-qsar/images/predictions.png" alt="QSAR predictions against measured potency"><br><b>14 · QSAR and virtual screening for EGFR.</b> 607 ChEMBL inhibitors in 160 scaffolds. Random forest on fingerprints: R² 0.70 on a random split but 0.65 on an honest scaffold split; active/inactive classifier AUC 0.90; virtual-screening enrichment; applicability domain (MAE 0.52 near the training set vs 0.97 far from it).</td>
</tr>
</table>

---

## Repository layout

Each project folder contains a Jupyter notebook that reproduces every number and figure, `images/`, `datasets/` (cached data, so it runs offline) and `animations/`: an interactive HTML tool for exploring the project's model.

## Running the projects

```bash
python3 -m pip install -U jupyter numpy pandas matplotlib scipy scikit-learn biopython rdkit torch
jupyter notebook
```

## Data sources

NCBI (GenBank / RefSeq genomes), UniProt, the 1000 Genomes Project via Ensembl, TCGA breast cancer RNA-seq, 10x Genomics PBMC3k, JASPAR, Pfam, the Protein Data Bank and ChEMBL.

*For research and education; not medical advice.*

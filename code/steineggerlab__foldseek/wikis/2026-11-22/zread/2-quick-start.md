

Foldseek enables fast and sensitive comparisons of protein structures, making it an essential tool for structural biologists and bioinformaticians. This guide will help you get started with Foldseek in just a few minutes, from installation to running your first protein structure search.

## Installation

First, you need to install Foldseek. The installation process is straightforward and depends on your system:

```bash
# Linux AVX2 build (check using: cat /proc/cpuinfo | grep avx2)
wget https://mmseqs.com/foldseek/foldseek-linux-avx2.tar.gz; tar xvzf foldseek-linux-avx2.tar.gz; export PATH=$(pwd)/foldseek/bin/:$PATH

# Linux ARM64 build
wget https://mmseqs.com/foldseek/foldseek-linux-arm64.tar.gz; tar xvzf foldseek-linux-arm64.tar.gz; export PATH=$(pwd)/foldseek/bin/:$PATH

# MacOS
wget https://mmseqs.com/foldseek/foldseek-osx-universal.tar.gz; tar xvzf foldseek-osx-universal.tar.gz; export PATH=$(pwd)/foldseek/bin/:$PATH

# Conda installer (Linux and macOS)
conda install -c conda-forge -c bioconda foldseek
```

After installation, verify that Foldseek is working by running:

```bash
foldseek version
```

Sources: [README.md#L69-L85](README.md#L69-L85)

## Your First Structure Search

Now let's run your first protein structure search. We'll use the example files included in the Foldseek repository. The `easy-search` module allows you to query one or more protein structures against a target database or folder containing structures.

```bash
# Search with a single structure against a folder of structures
foldseek easy-search example/d1asha_ example/ aln tmpFolder
```

This command searches the protein structure in `example/d1asha_` against all structures in the `example/` directory and saves the results in the `aln` file. The `tmpFolder` is used for temporary files during the search.

> [!TIP]
> The example files use PDB/mmCIF format, but Foldseek also supports gzipped files. You can use your own protein structure files in PDB, mmCIF, or mmJSON formats.

Sources: [README.md#L111-L114](README.md#L111-L114), [data/easystructuresearch.sh](data/easystructuresearch.sh)

## Understanding the Results

The default output is a tab-separated file with the following fields: `query,target,fident,alnlen,mismatch,gapopen,qstart,qend,tstart,tend,evalue,bits`. Let's examine what each field represents:

| Field | Description |
|-------|-------------|
| query | Query structure identifier |
| target | Target structure identifier |
| fident | Fraction of identical residues in the alignment |
| alnlen | Alignment length |
| mismatch | Number of mismatches in the alignment |
| gapopen | Number of gap openings in the alignment |
| qstart/qend | Start/end position of the alignment in the query |
| tstart/tend | Start/end position of the alignment in the target |
| evalue | Expectation value (lower is better) |
| bits | Bit score (higher is better) |

To view your results:

```bash
cat aln
```

You'll see something like:

```
d1asha_  d1x9fc_  0.318   117     78      1       1       117     1       117     0.00013 57.3
d1asha_  d1x9fd_  0.316   117     78      1       1       117     1       117     0.00014 57.1
```

This shows that `d1asha_` has significant structural similarity to `d1x9fc_` and `d1x9fd_` with low E-values, indicating these structures are likely evolutionarily related.

Sources: [README.md#L117-L119](README.md#L117-L119), [README.md#L121-L135](README.md#L121-L135)

## Visualizing Results

Foldseek can generate interactive HTML visualizations similar to the webserver:

```bash
foldseek easy-search example/d1asha_ example/ result.html tmp --format-mode 3
```

Open `result.html` in your web browser to see an interactive visualization of the search results, including structural alignments and similarity scores.

> [!TIP]
> The HTML visualization is particularly useful for understanding the structural relationships between proteins and identifying key structural features.

Sources: [README.md#L143-L147](README.md#L143-L147)

## Working with Pre-built Databases

Foldseek provides access to pre-built databases like PDB and AlphaFold DB. Here's how to download and search against these databases:

```bash
# Download the PDB database
foldseek databases PDB pdb tmp

# Search your structure against the PDB
foldseek easy-search example/d1asha_ pdb result_pdb tmp
```

This allows you to search your protein structure against the entire Protein Data Bank, which contains experimentally determined protein structures.

Sources: [README.md#L174-L181](README.md#L174-L181)

## Next Steps

Congratulations! You've successfully run your first protein structure search with Foldseek. Here are some suggested next steps:

1. **Adjust search sensitivity**: Use the `-s` parameter to adjust the sensitivity-speed trade-off (lower is faster, higher is more sensitive):
   ```bash
   foldseek easy-search example/d1asha_ example/ aln tmp -s 7.5  # Faster search
   foldseek easy-search example/d1asha_ example/ aln tmp -s 9.5  # More sensitive search
   ```

2. **Try structure clustering**: Group similar structures together using the easy-cluster module:
   ```bash
   foldseek easy-cluster example/ cluster_result tmp -c 0.9
   ```

3. **Explore multimer searches**: If you work with protein complexes, try the multimer search functionality:
   ```bash
   foldseek easy-multimersearch example/1tim.pdb.gz example/8tim.pdb.gz multimer_result tmp
   ```

For more detailed tutorials and advanced usage, check out the other documentation in this wiki.

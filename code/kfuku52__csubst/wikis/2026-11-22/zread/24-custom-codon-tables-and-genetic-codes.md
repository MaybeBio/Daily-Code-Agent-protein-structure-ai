

This page provides comprehensive documentation on configuring and working with custom codon tables and genetic codes in csubst. The framework supports all 26 NCBI-recognized genetic codes, enabling analysis across diverse taxonomic groups including mitochondrial genomes, alternative nuclear codes, and specialized genetic systems.

## Genetic Code Architecture

The genetic code system in csubst is built around a flexible NCBI ID-based lookup mechanism that provides codon-to-amino acid mappings, stop codon definitions, and start codon specifications. The core functionality resides in the `get_codon_table()` function, which retrieves complete genetic code specifications by NCBI identifier and formats them for downstream processing including substitution tensor computation and ancestral state reconstruction.
Sources: [genetic_code.py](csubst/genetic_code.py#L20-L431)

```mermaid
flowchart TD
    A[NCBI Genetic Code ID] --> B[get_codon_table lookup]
    B --> C{NCBI ID Match}
    C -->|ID 1-26| D[Retrieve genetic code dict]
    D --> E[Extract codon table mappings]
    D --> F[Extract stop codons]
    D --> G[Extract start codons]
    E --> H[Merge stop codons as '*' ]
    F --> H
    G --> H
    H --> I[Return [[aa, codon], ...] list]
    I --> J[Integrated into global state g]
    J --> K[Used for translation]
    J --> L[Used for omega calculation]
    J --> M[Used for substitution tensors]
    
    style B fill:#e3f2fd
    style I fill:#fff3e0
    style J fill:#f3e5f5
```

The genetic code lookup occurs during analysis initialization, where the selected NCBI ID is stored in the global parameter dictionary `g['genetic_code']` and subsequently used throughout the computational pipeline. The function returns a structured list format where each element is a `[amino_acid, codon]` pair, with stop codons represented as `'*'` for consistent downstream processing.
Sources: [main_analyze.py](csubst/main_analyze.py#L133), [genetic_code.py](csubst/genetic_code.py#L425-L430)

## NCBI Genetic Code Catalog

csubst includes all 26 NCBI-recognized genetic codes, providing comprehensive coverage across biological diversity. Each genetic code includes complete 64-codon mappings, specific stop codon sets, and alternative start codon definitions.

> [!TIP]
> Genetic code selection is critical for accurate omega (dN/dS) calculations and substitution pattern analysis. Using an incorrect genetic code will misclassify synonymous and nonsynonymous substitutions, leading to erroneous biological conclusions. Source: [main_analyze.py](csubst/main_analyze.py#L133)

| NCBI ID | Name | Key Distinguishing Features | Common Taxa |
|---------|------|----------------------------|-------------|
| 1 | Standard | TAA, TAG, TGA stop; TTG, CTG, ATG start | Most nuclear genomes |
| 2 | Vertebrate Mitochondrial | TGA→Trp, ATA→Met, AGA/AGG→Stop | Vertebrate mitochondria |
| 3 | Yeast Mitochondrial | TGA→Trp, CUN→Thr, ATA→Met | Saccharomyces mitochondria |
| 4 | Mold/Protozoan/Coelenterate Mitochondrial | TGA→Trp | Various protists, fungi |
| 5 | Invertebrate Mitochondrial | TGA→Trp, AGR→Ser | Invertebrate mitochondria |
| 6 | Ciliate/Dasycladacean/Hexamita Nuclear | TAA→Gln, TAG→Gln, TGA→Stop | Ciliates, green algae |
| 9 | Echinoderm/Flatworm Mitochondrial | TGA→Trp, AAA→Asn, AGR→Ser | Echinoderms, platyhelminths |
| 10 | Euplotid Nuclear | TGA→Cys | Euplotes species |
| 11 | Bacterial/Archaeal/Plant Plastid | Same as Standard (ID 1) | Bacteria, archaea, chloroplasts |
| 12 | Alternative Yeast Nuclear | CUG→Ser | Candida species |
| 13 | Ascidian Mitochondrial | TGA→Trp, AGA/AGG→Gly | Tunicates |
| 14 | Alternative Flatworm Mitochondrial | TAA→Tyr, TGA→Trp | Some platyhelminths |
| 21 | Trematode Mitochondrial | TGA→Trp, ATA→Met, AGA/AGG→Stop | Trematodes |
| 22 | Scenedesmus obliquus Mitochondrial | TGA→Trp, UCA→Stop | Green algae |
| 23 | Thraustochytrium Mitochondrial | TGA→Trp | Labyrinthulomycetes |
| 24 | Pterobranchia Mitochondrial | TGA→Trp, AGA/AGG→Ser | Hemichordates |
| 25 | Candidate Division SR1/Gracilibacteria | TGA→Gly | Uncultured bacteria |
| 26 | Pachysolen tannophilus Nuclear | CUG→Ala | Yeast species |

Sources: [genetic_code.py](csubst/genetic_code.py#L24-L427)

## Genetic Code Configuration

The genetic code is specified through the `--genetic_code` parameter when invoking csubst. This parameter accepts NCBI ID values from 1 to 26, defaulting to 1 (Standard) if not explicitly specified.

```python
# In command-line invocation
csubst analyze --alignment_file data.fa --tree_file data.nwk --genetic_code 2

# Programmatic integration
g['genetic_code'] = 2  # Vertebrate mitochondrial code
g['codon_table'] = genetic_code.get_codon_table(ncbi_id=g['genetic_code'])
```

The system automatically retrieves the appropriate genetic code during analysis initialization and integrates it into the global state dictionary for downstream processing. This includes populating `g['codon_table']` with the full codon mapping and generating derived structures such as synonymous indices for efficient computational processing.
Sources: [main_analyze.py](csubst/main_analyze.py#L133), [param.py](csubst/param.py#L10-L65)

## Codon Table Structure and Format

Each genetic code is represented as a dictionary containing four key components: the 64-codon translation table, stop codon specifications, start codon definitions, and metadata identifiers.

```python
{
    'name': 'Standard',
    'alt_name': 'SGC0',
    'id': 1,
    'table': {
        'TTT': 'F', 'TTC': 'F', 'TTA': 'L', 'TTG': 'L',
        'TCT': 'S', 'TCC': 'S', 'TCA': 'S', 'TCG': 'S',
        # ... all 64 codons ...
        'TAA': '*', 'TAG': '*', 'TGA': '*',  # Stop codons
    },
    'stop_codons': ['TAA', 'TAG', 'TGA'],
    'start_codons': ['TTG', 'CTG', 'ATG']
}
```

The `get_codon_table()` function transforms this structure into a sequential list format optimized for downstream operations:

```python
# Returned format: [[amino_acid, codon], ...]
return_ct = [[a, c] for a, c in zip(amino_acids, codons)]
# Example: [['F', 'TTT'], ['F', 'TTC'], ['*', 'TAA'], ...]
```

This format facilitates direct lookup during sequence translation and substitution tensor computation. Stop codons are explicitly marked with `'*'` in the returned table, enabling clear identification in downstream algorithms.
Sources: [genetic_code.py](csubst/genetic_code.py#L425-L430)

## IUPAC Nucleotide Ambiguity Codes

The system supports IUPAC nucleotide ambiguity codes for handling degenerate sequence positions and ambiguous bases commonly encountered in consensus sequences or uncertain alignment positions.

| IUPAC Code | Represents | Bases |
|------------|------------|-------|
| M | aMino | A, C |
| R | pRrine | A, G |
| W | Weak | A, T |
| S | Strong | C, G |
| Y | pYrimidine | C, T |
| K | Keto | G, T |
| V | not T | A, C, G |
| H | not G | A, C, T |
| D | not C | A, G, T |
| B | not A | C, G, T |
| X, N | aNy | A, C, G, T |

The ambiguity table is referenced during state index computation, enabling the framework to handle degenerate nucleotides in input sequences and ancestral state reconstructions without computational failure.
Sources: [genetic_code.py](csubst/genetic_code.py#L433-L448)

> [!TIP]
> When working with mitochondrial genomes or organisms known to have non-standard genetic codes, always verify the appropriate NCBI ID using taxonomic references before running analyses. Misassignment can lead to systematic errors in detecting convergent substitutions.

## Integration with Analysis Pipeline

The genetic code system integrates with multiple stages of the csubst analysis pipeline:

1. **Translation and State Management**: The codon table drives conversion between nucleotide, codon, and amino acid state representations, enabling cross-level analysis and visualization.
Sources: [sequence.py](csubst/sequence.py#L19-L47)

2. **Substitution Tensor Computation**: Synonymous and nonsynonymous substitution tensors are computed using genetic code-derived synonymous indices that classify each codon position by its encoded amino acid.
Sources: [main_analyze.py](csubst/main_analyze.py#L166-L172)

3. **Omega (dN/dS) Estimation**: The genetic code determines which codon changes are classified as synonymous versus nonsynonymous, directly affecting selection pressure calculations across foreground and background branches.
Sources: [main_analyze.py](csubst/main_analyze.py#L169-L170)

```python
# Translation from codon to protein states
def cdn2pep_state(state_cdn, g):
    num_pep_state = len(g['amino_acid_orders'])
    state_pep = numpy.zeros(axis, dtype=state_cdn.dtype)
    for i, aa in enumerate(g['amino_acid_orders']):
        # Sum across all synonymous codons for each amino acid
        state_pep[:, :, i] = state_cdn[:, :, g['synonymous_indices'][aa]].sum(axis=2)
    return state_pep
```

This function leverages the genetic code to aggregate probabilities across synonymous codons, producing protein-level state estimates from codon-level probabilistic reconstructions.
Sources: [sequence.py](csubst/sequence.py#L19-L27)

## Custom Genetic Code Implementation

For analyses requiring genetic codes not included in the standard NCBI catalog, the framework provides extension points through the codon table data structure. Custom genetic codes can be added by extending the `codon_tables` list in `genetic_code.py` with appropriate mappings.

Key requirements for custom genetic code definitions:
- Complete 64-codon mapping dictionary with all possible codons
- Explicit stop codon list (typically 1-4 codons)
- Start codon list (includes ATG and organism-specific alternatives)
- Unique NCBI ID (values beyond 26 for user-defined codes)
- Descriptive name and optional alt_name for identification

When implementing custom codes, ensure thorough testing using the included unit test framework to validate amino acid string length and codon string length consistency before production use.
Sources: [genetic_code.py](csubst/genetic_code.py#L449-L460)

## Testing and Validation

The genetic code system includes unit tests that validate fundamental properties of retrieved codon tables, ensuring data integrity and correct formatting for downstream processing.

```python
class Test(unittest.TestCase):
    def setUp(self):
        self.ct = get_codon_table(ncbi_id=1)
    
    def test_aa_str_len(self):
        # Validates each amino acid is a single character
        self.assertEqual(len(self.ct[0][0]), 1)
    
    def test_codon_str_len(self):
        # Validates each codon is exactly three nucleotides
        self.assertEqual(len(self.ct[0][1]), 3)
```

These tests serve as reference implementations for validating custom genetic code additions or modifications.
Sources: [genetic_code.py](csubst/genetic_code.py#L449-L460)

## Troubleshooting Genetic Code Issues

| Problem | Common Cause | Solution |
|---------|--------------|----------|
| Incorrect omega values | Wrong genetic code for taxon | Verify organism's genetic code via NCBI taxonomy, adjust `--genetic_code` parameter |
| Translation errors in output | Stop codon misclassification | Ensure stop codons in alignment are handled correctly for selected genetic code |
| Unexpected amino acid counts | Start codon reassignment | Check if alternative start codons are being translated correctly |
| Mismatched sequence lengths | Codon table corruption | Verify codon table retrieval by running unit tests |
| Ambiguous base handling | Missing ambiguity mappings | Confirm IUPAC codes in input are supported |

For further troubleshooting, consult the [Omega (dN/dS) Estimation](13-omega-dn-ds-estimation) and [Codon Substitution Models](7-codon-substitution-models) documentation for detailed integration patterns and advanced configuration options.
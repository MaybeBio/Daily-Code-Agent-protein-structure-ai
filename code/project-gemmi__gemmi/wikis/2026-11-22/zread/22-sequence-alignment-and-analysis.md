

Gemmi provides comprehensive sequence alignment and analysis capabilities for macromolecular structures, supporting both sequence-to-sequence and structure-to-sequence comparisons. The implementation combines efficient alignment algorithms with domain-specific optimizations for crystallographic data.

## Core Alignment Architecture

The sequence alignment system is built around three main components: scoring matrices, alignment algorithms, and structure integration. The foundation is the `AlignmentScoring` struct [include/gemmi/seqalign.hpp#L16-L45] which provides flexible scoring schemes including simple match/mismatch, BLOSUM62 for protein sequences, and specialized scoring for partially modeled polymers.

```cpp
struct AlignmentScoring {
  int match = 1;
  int mismatch = -1;
  int gapo = -1;  // gap opening penalty
  int gape = -1;  // gap extension penalty
  int good_gapo = 0;  // gap opening in expected place in a polymer
  int bad_gapo = -2;  // gap opening that was not predicted
  std::vector<std::int8_t> score_matrix;
  std::vector<std::string> matrix_encoding;
};
```

The alignment engine implements a modified Smith-Waterman algorithm optimized for biological sequences [include/gemmi/seqalign.hpp#L1-L10], derived from the high-performance ksw2 library. Results are stored in `AlignmentResult` objects containing CIGAR strings, scores, and detailed match information.

## Sequence-to-Polymer Alignment

A key innovation is the `align_sequence_to_polymer` function [include/gemmi/align.hpp#L44-L78] which aligns theoretical sequences (from SEQRES or FASTA) to actual polymer coordinates. This function handles the complex mapping between sequence positions and structural residues, accounting for:

- Missing residues in crystal structures
- Insertions and deletions
- Polymer connectivity constraints
- Chain breaks and discontinuities

The alignment process first creates an encoding scheme for all residue types, then performs dynamic programming alignment with gap penalties that reflect structural connectivity:

```cpp
inline AlignmentResult align_sequence_to_polymer(
                                     const std::vector<std::string>& full_seq,
                                     const ConstResidueSpan& polymer,
                                     PolymerType polymer_type,
                                     const AlignmentScoring* scoring=nullptr)
```

## Label Sequence Assignment

Gemmi provides automated `label_seq_id` assignment through `assign_label_seq_to_polymer` [include/gemmi/align.hpp#L104-L144]. This critical function maps sequential numbering to structural residues, handling three scenarios:

1. **Exact match**: When model sequence perfectly matches SEQRES
2. **Force assignment**: When no reference sequence exists, assumes continuity
3. **Alignment-based**: Uses sequence alignment to resolve mismatches

The function processes CIGAR operations to incrementally assign sequence identifiers, properly handling insertions, deletions, and matches.

## Command Line Interface

The `gemmi align` command-line tool [prog/align.cpp#L1-L50] provides accessible sequence alignment functionality with multiple operation modes:

```bash
# Align model sequence to SEQRES from same file
gemmi align structure.pdb

# Cross-chain alignment between different files
gemmi align --query=+A --target=+B file1.pdb file2.pdb

# Text-based alignment for testing
gemmi align --text-align "ACDEFGH" "ACD-EFG"
```

> [!TIP]
> The `+` prefix in chain names indicates SEQRES sequences rather than coordinate sequences, enabling comparison between theoretical and actual polymer content.

## Structure Superposition Integration

Sequence alignment extends to structural comparison through the superposition framework [include/gemmi/align.hpp#L180-L220]. The `prepare_positions_for_superposition` function aligns sequences first, then maps corresponding atoms for RMSD calculation:

```cpp
enum class SupSelect {
  CaP,  // only Ca (aminoacids) or P (nucleotides) atoms
  MainChain,  // only main chain atoms
  All
};
```

This integrated approach ensures that structural superposition is based on biologically meaningful residue correspondence rather than arbitrary ordering.

## FASTA Sequence Assignment

For structures with incomplete or missing sequence information, Gemmi can assign the best matching sequences from FASTA files [src/align.cpp#L44-L66]. The `assign_best_sequences` function:

1. Categorizes FASTA sequences by polymer type (protein, RNA, DNA)
2. Performs alignment scoring against each entity
3. Assigns the highest-scoring sequence to each polymer

> [!TIP]
> The function handles mixed polymer types in a single structure, automatically routing protein sequences to peptide entities and nucleotide sequences to nucleic acid entities.

## Performance and Optimization

The alignment implementation emphasizes efficiency through:

- **Byte-encoded sequences**: Reduces memory usage and speeds up comparisons
- **Adaptive gap penalties**: Structural connectivity informs gap scoring
- **Early termination**: High-scoring alignments can shortcut full matrix computation
- **Vectorized operations**: Where supported by hardware

The system processes alignment results incrementally, enabling streaming analysis of large structure collections without loading entire datasets into memory.

## Integration with Crystallographic Workflow

Sequence alignment in Gemmi serves multiple crystallographic purposes:

- **Validation**: Checking model completeness against SEQRES
- **Model building**: Guiding residue placement in missing regions
- **Structure comparison**: Enabling meaningful RMSD calculations
- **Database integration**: Mapping PDB sequences to external references

The alignment framework seamlessly integrates with Gemmi's broader crystallographic capabilities, providing a robust foundation for sequence-aware structural analysis.

For advanced structural analysis, see [Structure Superposition and Alignment](17-structure-superposition-and-alignment), and for molecular representation details, refer to [Macromolecular Model Representation](16-macromolecular-model-representation).
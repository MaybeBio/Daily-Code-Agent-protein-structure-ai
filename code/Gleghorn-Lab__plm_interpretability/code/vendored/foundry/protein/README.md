---
id: foundry.protein
kind: library_module
status: active
aliases: [foundry.protein]
---
# foundry.protein

Protein scoring that several projects share, one submodule each.

| Submodule | Holds |
|---|---|
| `ipsae` | The workspace's one ipSAE: from the PAE matrix alone, and the Dunbrack lab's full ipSAE, ipTM, pDockQ, pDockQ2, and LIS table from AlphaFold2, AlphaFold3, Boltz, ESMFold2, and Biohub outputs |
| `composition` | `composition(sequences)`: the twenty amino-acid fractions, the log length and the 400 dipeptide fractions of each sequence, (n, 421), letters outside the canonical twenty dropped; the composition baseline of the attribute audits (pli_experimental_v2, solubility_binary_v2), promoted 2026-11-01 with both audits reproducing their records exactly. Tests: `tests/tier1_unit/test_protein_composition.py` |
| `sequence` | Amino-acid sequence text: narrowing an outside sequence to the canonical alphabet, and reading one under the suite's `protein_ascii_v1` identity text |
| `fasta` | The workspace's one FASTA reader and writer, gzip-transparent, over a path or text in memory |
| `experimental_evidence` | Which evidence codes are experimental: the eleven GO codes of a GAF line and UniProt's experimental evidence types, as two sets and two tests |
| `uniprot_xml` | The UniProt XML entry helpers that releases share: the namespace, the primary accession, the canonical sequence checked against its stated length, the evidence records, the organism, a comment text's sentences and the accession grammar |
| `meltome` | The Meltome Atlas workbook (Jarzab 2020, figshare 11829780, CC BY 4.0): each sheet of an .xlsx read with the standard library, and each melting point row of `Fig. 2a` with its first structural reason; `thermal_tm_experimental_v1`'s reader and the annotation compendium's melting temperature view read it (promoted 2026-10-21 from production_suite's `thermal_source_census` and `meltome_tm`; `tests/tier1_unit/test_protein_meltome.py`) |
| `ph_optimum` | The optimum pH a UniProtKB pH-dependence text states, read sentence by sentence, and the ten text rules that keep it as one point label; `ph_optimum_experimental_v2`'s reader and the annotation compendium's pH view apply them (promoted 2026-10-21 from production_suite's `uniprot_ph_comments` and `brenda_ph`; `tests/tier1_unit/test_protein_ph_optimum.py`) |
| `gpu_alignment` | Exact affine-gap alignment scores of many pairs at once, global or local, one or two substitution channels: a Triton kernel on the GPU and a torch reference |
| `alignment_scores` | The three exact labels over `gpu_alignment` (SW with BLAST's gaps, self-normalized NW, Foldseek's 3Di+AA score), the integer tables rebuilt from Foldseek's MMseqs matrix files in `matrices/`, and the significance threshold of a per-query Gumbel null |
| `composition_bias` | Foldseek's composition-bias correction of a query (`--comp-bias-corr 1`, its default): the per-position terms MMseqs2's `calcLocalAaBiasCorrection` adds to the query profile on both channels, which the corrected Foldseek label (`foldseek_cbc`) reads through `gpu_alignment`'s profile path |
| `three_di` | `ThreeDiHead`: per-residue 3Di states from ESMC's two per-residue views (layer-23 hidden and structural stream), which alignment_atlas trains and the search service runs on amino-acid-only queries |
| `alignment_statistics` | The tools' own statistics for an exact score: BLAST's Karlin-Altschul bit score, length adjustment and Spouge E-value (BLOSUM62, gaps 11/1), and Foldseek's E-value network (weights `matrices/evalue_nn.kerasify`, Foldseek 10-941cd33, GPL-3.0) and `prob`; the search service reports them and alignment_atlas's benchmark defines a hit by them; `chance_level` judges a decoy's chance-hit count by its exact Poisson interval (S7) |
| `vector_candidates` | The candidate list a one-vector search hands to the exact rerank, with alignment_atlas's ruled constants frozen: `cell_depths` (A17's per-query depth from a budget of alignment cells), `window_starts` (window grids for long queries and long entries), `window_depths` and `windowed_union` (A18's query windows of 100 at stride 50, half the depth); database entries have no windows, each one row truncated to the encoder's 2,046 residues (Logan, 2026-11-03, retiring E6); the benchmark and the search service both read them (moved 2026-10-19; `tests/tier1_unit/test_vector_candidates.py`) |
| `pairs` | `pair_key(left, right)`: an unordered protein pair as a tuple with the lesser key first, the one key Atlas's fused_ppi, dyad and v3 code and its experiments give a pair (promoted 2026-10-17 from five copies; `tests/tier1_unit/test_protein_pairs.py`) |
| `non_enzymes` | The confident non-enzyme of `ec_experimental_v2` and `v3`: `entry_facts` and `read_entry_facts` (what a reviewed Swiss-Prot entry states about catalysis and function, `EntryFacts` and its `ARROW_SCHEMA`), the `Definition`, the `Context` that `context_of` derives from every entry (`high_ec_terms`), and `rule_failures`, the twelve named rules; production_suite's release builders and the annotation compendium's EC view apply them (promoted 2026-10-21 from production_suite's `uniprot_non_enzymes` and `non_enzyme_selection`, which keep the facts table, the candidate pool and the matching; `tests/tier1_unit/test_protein_non_enzymes.py`) |

## `foundry.protein.ipsae`

ipSAE ([Dunbrack, 2025](https://www.biorxiv.org/content/10.1101/2025.02.10.637595v1)) scores a
predicted interface from a folded complex's predicted aligned errors (PAE). Aligned on one residue
of a chain, each error to the other chain's residues below a cutoff becomes a TM-score term, whose
distance scale d0 is set by how many errors there are. A direction's score is its best residue's
mean term, and a pair's ipSAE_min is the weaker of its two directions.

| Name | Does |
|---|---|
| `protein_chain_spans_from_entities(entities)` | Each protein chain's rows of the PAE matrix, from a fold request's entities in order: `{"id", "start", "end", "length"}`. A protein, DNA, or RNA entity takes a row per residue and a SMILES or CCD ligand one row; any other type raises `ValueError` |
| `tm_d0(length)` | TM-score's d0, in angstroms, for `length` residues: 1.24 (L - 15)^(1/3) - 1.8, with L counted as at least 27, so never under about 1.039 |
| `tm_from_pae(pae_value, d0)` | One error as a TM-score term, 1 / (1 + (pae / d0)^2) |
| `ipsae_asym_from_pae(pae_matrix, align_span, scored_span, pae_cutoff)` | One direction: `score`, the best residue of `align_span`'s mean term over its errors to `scored_span` below the cutoff, with that residue's `n0res` and `d0res`. With no error below the cutoff the score is 0.0 |
| `ipsae_min_fields(pae_matrix, chain_spans, *, pae_cutoff, binder_threshold)` | Every pair of chains both ways, and the fields of the pair whose weaker direction is strongest: `ipsae` and `ipsae_min`, `ipsae_max`, `ipsae_a_to_b`, `ipsae_b_to_a`, `ipsae_chain_pair` (`"A:B"`), `ipsae_pair_metrics_json` (every pair, as compact JSON), and `binder_likely` (`ipsae_min` above `binder_threshold`). The first pair wins a tie; fewer than two spans give no fields |
| `empty_ipsae_min_summary(pae_cutoff, binder_threshold=None)` | The summary of an interface that cannot be scored: every field of `ipsae_min_fields` blank, `binder_likely` False and `ipsae_pae_cutoff` the cutoff. A consumer `update`s it with `ipsae_min_fields` when a pair can be scored. Given a `binder_threshold`, it also records it as `binder_ipsae_threshold`, after the cutoff (added 2026-10-06, from the two copies of it) |

`pae_matrix` is `(l, l)`, a list of rows or a two-dimensional NumPy array, read as
`pae_matrix[i][j]`: the error at residue `j` when the complex is aligned on residue `i`. Each
consumer checks its input before these functions.

The code is the form of the Dunbrack lab's `ipsae.py` ([MIT](https://github.com/dunbracklab/IPSAE))
that needs only the PAE matrix and the chains' rows, as folding_service and sequence_gradient held
it. Its d0 follows the script's `calc_d0`, which counts at least 27 residues and so gives 1.039 at 27 or
fewer; both copies gave 1.0 there until
[the decision](https://github.com/Gleghorn-Lab/plm_interpretability/blob/HEAD/vendored/docs/decisions/foundry/protein/2026-09-24_ipsae_min_d0.md) changed it on 2026-09-28, so scores
of small interfaces from before that day are not comparable with later ones.

Promoted on 2026-09-24. These copies now import it:

- folding_service's `fold.ipsae_core`. Its `compute_ipsae_min_from_pae` keeps its conversion of a
  tensor or nested list to a NumPy array, and `protein_chain_spans_from_entities`
  stays importable from it. The ESMFold2 Modal image scores ipSAE in the container, so it now adds
  `foundry/protein/` and foundry's `__init__.py` beside `fold/`, and
  `tests/unit/test_modal_image_layout.py` imports the app from that layout alone. The GH200
  workstation runner, `esmfold2_workstation_cli.py`, copies `ipsae_core.py` into each run directory
  on the workstation; until 2026-09-25 it copied nothing of foundry, so a run would have calibrated
  and folded its first batch on the GPU, then stopped when `ipsae_core` could not import this
  module. It now copies the foundry files beside it, and
  `tests/unit/test_esmfold2_workstation_cli.py` imports both from a run directory's files alone.
- sequence_gradient's `models.folding.ipsae`, which keeps its checks of the matrix, the cutoff,
  and the threshold, and passes the threshold on for its summary's `binder_ipsae_threshold`.
- `tm_d0` and `tm_from_pae` in Atlas's `exploratory/scripts/fold_case_study_structures_biohub.py`,
  whose own direction score also reports each residue's position, n0chn, d0chn, n0dom, and d0dom.

Against each copy, bit for bit: the summaries of both projects' `compute_ipsae_min_from_pae`,
their key order, and the errors they raise, over random matrices and spans, cutoffs, ties, empty
and ligand-shifted spans, tensors, NumPy arrays, and nested lists; and Atlas's direction score with
its helpers. What changed:

- `ipsae_asym_from_pae` reads a row, then its columns, so a list of rows and an array take the same
  path. folding_service's read the array as `[i, j]`; the values read are the same.

### The full table

Since 2026-09-26 this module is also the Dunbrack lab's whole script, `ipsae.py` version 3 at
DunbrackLab/IPSAE commit `441b2a479be3` (MIT; the module reproduces its notice), so the workspace
holds one ipSAE. It replaced the script's three copies, each retired to `C:/ws-staging/_removed/`:
folding_service's unchanged `fold/ipsae_reference.py`, and property_oracles'
`folding/boltz/ipsae.py`, which truncated misaligned arrays and printed for pandas, and its
unimported `ipsae_pandas.py`. folding_service's `fold.ipsae_core` held a refactor of the script's
arithmetic; it now reads its own formats into this module and computes nothing itself.

| Name | Does |
|---|---|
| `interface_scores(pae_matrix, chains, residue_types, residue_numbers, coordinates, cb_plddt, *, plddt, iptm, pae_cutoff, dist_cutoff, model_label)` | The script's tables from residue arrays: `rows`, the chain-pair table (each pair's two `asym` rows and its `max` row, keyed by the script's column names), `residue_rows`, the by-residue table, and `interface_residues` for PyMOL. `iptm` is the predictor's own ipTM, one float or one per ordered chain pair; with None, `ipTM_af` repeats `ipTM_d0chn` |
| `read_structure(path)` | A `.pdb` or `.cif` file's residue tokens as `ResidueArrays`: chains, residue names and numbers, CB-equivalent coordinates, the token and CB atoms' indices, and the predictor's token mask |
| `read_prediction(pae_path, structure_path)` | A `Prediction` from AlphaFold2 (`.pdb` and scores `.json` or `.pkl`), AlphaFold3 (`.cif`, `full_data` `.json`, and its `summary_confidences`), or Boltz (`.cif`, `pae_*.npz`, and its `plddt_*.npz` and `confidence_*.json`) |
| `score_prediction(prediction, *, pae_cutoff, dist_cutoff, model_label)` | `interface_scores` for a `Prediction` |
| `chain_pair_iptm_from_matrix(matrix, chains)` | A predictor's chain-pair ipTM by chain label, from AlphaFold3's list of rows or Boltz's string-keyed mapping; None when it does not reach every chain |
| `format_chain_pair_table(rows, *, style)`, `format_residue_table(residue_rows)`, `format_pymol_script(scores)` | The script's three files as text: `style="text"` is its `.txt`, and `style="csv"` Oracles' comma-separated form of it |
| `write_outputs(scores, stem)`, `main(argv)` | The three files, and the script's command line: `python -m foundry.protein.ipsae <pae> <structure> <pae cutoff> <dist cutoff>` |

`tests/tier1_unit/test_ipsae_files.py` holds it to the script. It writes a small complex in each
predictor's files, with a modified residue tokenized atom by atom, a ligand, a DNA chain, and both
mmCIF column orders, and checks the SHA-256 of all three files the command line writes, at two
pairs of cutoffs, against those the unchanged script wrote for the same inputs. Oracles' CSV was
checked the same way against its copy, at its default cutoffs of 15 too, before the copy was
retired. Where this differs from the script:

- A residue's CB-equivalent atom and its pLDDT are looked up by chain and residue number. The
  script paired the i-th CA with the i-th CB, so a residue without one shifted every later
  residue's distances; the two agree whenever every residue has one.
- A PAE matrix or pLDDT vector with a different number of tokens than the structure is cut to the
  shorter, with a warning, as Oracles' copy did, where the script raised or misread.
- Boltz's sibling files are found by replacing `pae` in the file name only, where the script
  replaced it anywhere in the path; the model label drops only the file's suffix.
- A `max` row's `ipTM_af` is the larger of the pair's two directions for AlphaFold3 too; the script
  took the second direction's, the same value when `chain_pair_iptm` is symmetric, as AlphaFold3
  writes it.
- Without the predictor's ipTM, `interface_scores` repeats `ipTM_d0chn`, as folding_service's
  table did; `read_prediction` passes the script's 0.0 or, for AlphaFold2, -1.0.

The PAE-only functions above keep their own d0 at 27 residues or fewer, which the proposed
decision on d0 asks about; the full table takes the script's.

## `foundry.protein.sequence`

| Name | Does |
|---|---|
| `CANONICAL_AMINO_ACIDS` | The 20 canonical residues, as a frozenset |
| `sanitize_sequence(sequence)` | Uppercase, then every non-canonical character becomes X. Same length as the input, so residue positions are preserved |
| `normalize_protein_ascii(sequence)` | `protein_ascii_v1`: ASCII whitespace removed and letters uppercased, every residue kept. Raises `ProteinTextError` (a `ValueError`) for a non-string or non-ASCII text, an empty sequence, and one with a gap, stop, digit, or other symbol |
| `complexity_flags(sequence)` | The one low-complexity rule for designed sequences: entropy against a uniform sequence of the same length (log2(20) less the Miller-Madow term, minus `ENTROPY_DEFICIT_BITS` 0.6), the longest single-residue run (6 flags), and the share of 12-residue windows with four residue types or fewer (over 5 percent flags); from the Adaptyv campaign's `pde_rounds.sequence_flags`, when the PDE's ProteinMPNN stage became its second consumer (2026-10-22) |
| `PROTEIN_ASCII_POLICY`, `IDENTITY_AMINO_ACIDS`, `ASCII_WHITESPACE` | The policy's name, the 26 letters it keeps (the 20 canonical residues and B, X, Z, J, U, O), and the whitespace it drops |

`sanitize_sequence` narrows a sequence so a tool that accepts only the canonical alphabet can read it; it changes
residues. `normalize_protein_ascii` is an identity: the suite keys datasets, feature caches, and served requests on
its text, so a protein must normalize the same way when a dataset is built and when a request is served, and a
sequence it would have to rewrite is refused. Do not use one where the other belongs.

Promoted on 2026-09-29 from production_suite's `sequence_identity.normalize_protein`, when serving's request admission
(`suite_outcomes.admit_sequence`) became its second consumer. `normalize_protein` still refuses a non-protein molecule
and raises `IdentityError`, which it now makes from this module's error, with the same messages, so its callers see no
change. `AMINO_ACIDS`, `ASCII_WHITESPACE`, and `SEQUENCE_POLICY` in `sequence_identity` are these names.
`tests/tier1_unit/test_protein_sequence.py` covers it, and production_suite's `test_sequence_identity.py` holds its
`IdentityError` messages.

Promoted on 2026-09-25 from three identical copies, each of which now imports it:
`datasets/builders/dataset_dev_utils/chemistry.py`, synth's `utilities/chemistry.py`, and DSM's
`models/alignment_helpers.py`, where `NWScorer._sanitize_sequence`,
`AlignmentScorer._sanitize_sequence`, and `alignment_score`'s inline copy now all call it. Each
module keeps `sanitize_sequence` importable from its own path. The tier1 test checks the new
function against the replaced text over lowercase, ambiguity codes, gaps, stops, digits, spaces,
and the empty string.

Not here: synth's `_sanitize_sequence` in `services/atlas/serving/capabilities/msa.py`, which is
the same narrowing but serves that module's own residue color table, and the alignment scorers in
DSM's `alignment_helpers.py`. `NWScorer`, `AlignmentScorer`, and `GetAlignmentScoreFromLogits`
have one consumer each, so they stay in DSM until a second one exists. The local DSM checkout's
`not_published/nw.py` held two collators around `AlignmentScorer` that nothing imported; they were
not brought in ([the DSM README](https://github.com/Gleghorn-Lab/plm_interpretability/blob/HEAD/vendored/projects/representation/dsm/README.md)).

## `foundry.protein.fasta`

| Name | Does |
|---|---|
| `FastaRecord(id, sequence, description)` | One record. `id` is the header's first whitespace-delimited token, which is what every copy here used and what Biopython's `record.id` gives; `description` keeps the rest of the header |
| `iter_fasta(path, *, uppercase=False)` | Each record of a file in order, streaming. A `.gz` path opens through gzip, by `foundry.compression` |
| `iter_fasta_text(text, *, uppercase=False, source=...)` | The same over text already in memory, such as an API response body. `source` names it in any error |
| `read_fasta(path, ...)` / `read_fasta_text(text, ...)` | The records as a list, order and duplicates preserved |
| `fasta_sequences(path, *, uppercase=False, unique=True)` | Identifier to sequence, in file order. `unique=True` raises on a repeat, which a dict would otherwise drop; `unique=False` keeps the last |
| `write_fasta(path, records, *, line_width=60)` | Write a mapping or records, wrapped at `line_width`; 0 writes one line per sequence. A `.gz` path writes gzip. Lines end in a line feed on Windows too, since a Linux tool reads a carriage return as part of an identifier |

**It is strict, because a misread FASTA file produces sequences that are wrong rather than
absent.** Residues before the first header raise, an empty identifier raises, a header with no
residues raises, and a file with no records raises. Residue case is preserved, since lowercase
marks a masked residue in some sources, so `uppercase=True` is the caller's decision. Whitespace
inside a residue line is joined away, as FastPLMs' reader does.

Promoted on 2026-09-26, from fourteen readers that each returned a different shape.
`base_model_distillation`'s `benchmarks/panels.py` and synth's
`utilities/chemistry.py::load_fasta_sequences` import it; synth's dropped a Biopython `SeqIO.parse`
and now fails loudly on an empty proteome download instead of embedding nothing.

Not here, each for a reason rather than for want of time:

- **FastPLMs' `embeddings/inputs.py`** (`iter_fasta`, `parse_fasta`) and `models/e1/retrieval.py`
  and `models/esmfold2/esmfold2_parsing.py`: FastPLMs vendors no foundry. Its reader is the
  semantics this one matched, so the two agree on every well-formed file.
- **tmap's `utils/proteins.py::read_fasta`** is a public, tested API of a published fork whose tests
  pin an empty file to `([], [])` and an empty record to `""`. This reader raises on both, and
  loosening it would defeat the point.
- **annotation_vocabulary's `iter_fasta_accession_sequences`** additionally refuses whitespace
  inside a residue line and extracts a UniProt accession from `sp|ACC|NAME`. Its digests feed
  dataset identity, so a check it has today may not be dropped; delegating the loop would lose that
  refusal.
- **folding_service's `read_canonical_fasta`** ships to the workstation and the FastPLMs container
  in a run directory that carries only the foundry files it imports. Adopting this would add
  `foundry/protein/fasta.py` and `foundry/compression/` to every run directory for a reader whose
  validation (`>NAME|ACCESSION` headers against an expected set) is its own.
- Atlas's and Protify's copies, and synth's `capabilities/actome.py`, wait on the sessions that
  hold those paths; `foundry/README.md` keeps the marker.

## `foundry.protein.experimental_evidence`

| Name | Does |
|---|---|
| `GO_EXPERIMENTAL_CODES` | EXP, IDA, IPI, IMP, IGI, IEP and the high-throughput HTP, HDA, HMP, HGI, HEP, as GAF 2.2 column 7 writes them |
| `UNIPROT_EXPERIMENTAL_ECO` | `ECO:0000269` (UniProt's manual assertion with experimental evidence) and the other experimental assertion types; the combinatorial `ECO:0007744` is out |
| `is_experimental_go(code)`, `is_experimental_eco(code)` | Membership tests |
| `evidence_tier(code)` | The annotation compendium's tier of a GAF code or ECO type: `experimental` (the two sets plus the combinatorial `ECO:0007744`), `curated` (similarity, a sequence model applied by hand, curator or traceable author statement), `guard` (automatic, phylogenetic, electronic, imported, untraceable) or `skip` (no data); an unknown code raises `UnknownEvidenceCode` |
| `GO_CURATED_CODES`, `GO_GUARD_CODES`, `GO_SKIPPED_CODES`, `UNIPROT_COMBINATORIAL_ECO`, `UNIPROT_CURATED_ECO`, `UNIPROT_GUARD_ECO`, `UNIPROT_SKIPPED_ECO` | The codes of each tier |

Promoted on 2026-10-02 from `production_suite`'s `functional_evidence` so that the suite's GO, EC and
location releases and annotation_vocabulary's `protein_annotation_experimental_v1` share one meaning of
"experimental". A change to a set changes every release that imports it and needs a decision record. The tiers were added on
2026-10-20 for the annotation compendium, whose experimental tier counts `ECO:0007744` (Logan); the two sets and their tests are
unchanged, so no earlier release changes
([the decision](https://github.com/Gleghorn-Lab/plm_interpretability/blob/HEAD/vendored/docs/decisions/representation/annotation_vocabulary/2026-10-20_annotation_compendium.md)).

## `foundry.protein.uniprot_xml`

| Name | Does |
|---|---|
| `uniprot_namespace(root)` | The namespace prefix of a UniProt collection; any other document raises `ExtractionError` |
| `entry_accession(entry, namespace, datasets)` | The primary accession of an entry of the named datasets (`DATASETS`, Swiss-Prot and TrEMBL, by default) |
| `canonical_sequence(entry, namespace, accession)` | The one sequence element and its residues, whose length must equal the stated one |
| `evidence_records(entry, namespace, citation_types=("PubMed",))`, `evidence_for(keys, records, where, noun)` | Each evidence key with its ECO code and the citations it resolves to, written `<type>:<id>`, and the records a space-separated `evidence` attribute names; an absent key raises. `citation_types=("PubMed", "DOI")` also keeps the DOI of an older paper that has no PubMed identifier |
| `publication_identifiers(element, namespace, types=("PubMed",))`, `pubmed_identifiers(element, namespace)`, `organism_record(entry, namespace)` | The references of the named types directly below an element, the same for PubMed alone, and the organism's name, taxon and lineage |
| `sentences_of(text)`, `SENTENCE_BOUNDARY` | A comment text's sentences, split after each full stop that white space follows, whitespace collapsed (2026-10-21, from the copies of `uniprot_ph_comments` and the compendium's reader) |
| `ACCESSION`, `ISOFORM` | UniProtKB's accession grammar and an isoform's identifier, `<accession>-<n>` (2026-10-21, from `production_suite.uniprot_subset` and `meltome_tm`) |

Promoted on 2026-10-02 from `production_suite`'s `uniprot_xml`, which now re-exports these names and keeps
its reviewed-only entry types. `annotation_vocabulary`'s experimental readers use them for Swiss-Prot and
TrEMBL entries alike. `production_suite.uniprot_ph_comments` reads the pH-dependence comments with
`citation_types=("PubMed", "DOI")`, and no longer carries its own copy of `evidence_records`.

## `foundry.protein.ph_optimum`

| Name | Does |
|---|---|
| `optimum_statement(sentence)`, `Statement` | What one sentence states as the optimum pH, read word by word after "optimum pH": a point, an interval (a range or a bound) with its low and high values, a qualitative or an unparseable statement, with the other pH-like numbers after it; None when the sentence does not hold those words |
| `judge_text(text, codes, *, scoped=False)`, `TEXT_REASONS` | The first of ten reasons a pH-dependence text is not one point optimum (no evidence key, no ECO:0000269, a molecule or an isoform, no optimum sentence, unparseable, qualitative, an interval, several pH values, off the 0 to 14 scale, a mutant or variant), or its optimum and its optimum sentences |
| `MUTANT_WORDS`, `MUTATION_TOKEN`, `SCALE` | The words and the residue substitution (E123A) that make a free-text comment another protein's, and the pH scale; BRENDA's readers use them too |

Promoted on 2026-10-21 from `production_suite`'s `uniprot_ph_comments` (the sentence reading and the text rules)
and `brenda_ph` (the variant words and the scale), when the annotation compendium's pH view became their second
consumer. `uniprot_ph_comments.judge_text` applies them to an extracted record and adds the release's citation,
fragment, length and duplicate rules; the view adds the same citation and duplicate rules over its pooled texts.

## `foundry.protein.meltome`

| Name | Does |
|---|---|
| `read_workbook(path)`, `Sheet`, `column_index(reference)` | Each sheet of an .xlsx as `(title, header, rows)`, read from its zip and XML parts, an empty cell kept as None so that columns stay aligned; a sheet whose first row is not one title cell raises |
| `read_rows(workbook, *, workbook_sha256)`, `MeltomeRow` | Every data row of `Fig. 2a` in order: species, protein id, growth temperature, melting point (its text and number), the UniProtKB identifier, the locator `Fig. 2a/R<n>`, and the first structural reason, `no_melting_point` or `not_a_uniprot_accession`; a changed file, header, species or number raises |
| `identifier_of(protein_id)` | The accession or isoform identifier a `<accession>_<gene or locus>` protein id starts with, or None |
| `SPECIES`, `WORKBOOK_FILE`, `MELTING_POINTS_SHEET`, `MELTING_POINT_HEADER`, `CITATION` | The sheet's 13 species with the binomials UniProtKB gives their proteins, and the workbook's file, sheet, header and paper |

Promoted on 2026-10-21 from `production_suite`'s `thermal_source_census` (the workbook) and `meltome_tm` (the rows),
when the annotation compendium's melting temperature view became their second consumer. `meltome_tm` adds the release
rules past the first two reasons (the release holds the accession, the organism is the lysate's, the length limit);
`meltome_tm_readback` stays an independent reading.

## `foundry.protein.alignment_scores`

The scores alignment_atlas's vectors are trained to reproduce and alignment_search reports beside each hit, defined
in [the label decision](https://github.com/Gleghorn-Lab/plm_interpretability/blob/HEAD/vendored/docs/decisions/representation/alignment_atlas/2026-10-16_labels_score_and_gate.md):

| Name | Does |
|---|---|
| `SPECS`, `LabelSpec`, `LabelName` | Each label's problem: local or global, gap open and extend (the first gap residue's cost first), one or two channels, self-normalized, reverse-corrected |
| `tables(name, device)` | The label's substitution tables: BLOSUM62 for `sw`, doubled for `nw`, Foldseek's 3Di at 2.1 bits and BLOSUM62 at 1.4 for `foldseek`, (21, 21) or (2, 21, 21) int32 |
| `read_mmseqs_matrix(path)`, `mmseqs_integer_matrix(path, bit_factor)` | An MMseqs `.out` file, and the integer table MMseqs's `SubstitutionMatrix` builds from it, rounding as it does |
| `raw_scores`, `label_scores`, `self_scores` | Integer scores of pairs, the label as float32 (divided by the self-scores for `nw`, minus the reversed query's score for `foldseek`), and each sequence's score against itself; `engine` picks the Triton kernel or the reference |
| `null_threshold(moments, database, evalue)` | The score at which a hit has E-value `evalue` against `database` sequences, under a Gumbel fitted by moments to the query's own scores |
| `MATRICES`, `SIGNIFICANT` | The folder of Foldseek 10-941cd33's `data/mat3di.out` and bundled `blosum62.out`, unmodified; E-value 1e-3 |

Promoted on 2026-10-17 from alignment_atlas's `scoring.py`, when alignment_search became its second consumer; both
import it from here. The labels equal Biopython, never exceed BLASTp and equal the foldseek binary on 76,729 pairs
(alignment_atlas's `parity.py`).

## `foundry.protein.complex_geometry`

The geometry a designed complex is screened on besides its confidences, read from its PDB with biotite: interface
residues on each side (heavy atoms within 4.5 A), the interface's buried SASA, the binder's surface hydrophobicity
(hydrophobic residues among those with relative SASA over 0.25, Tien et al. 2013 maxima), the interface's hydrophobic
share and its lysine and methionine counts, polar contacts across the interface (the upper bound of its hydrogen bonds,
since a predicted model has no hydrogens), the binder's helix, sheet and loop shares (P-SEA), its radius of gyration, and
its CA RMSD to the same chain predicted alone, and its pose RMSD between two models of the complex superposed on the
target (`pose_rmsd`; Bennett et al. 2023's design-to-prediction agreement). These are BindCraft's filters (surface hydrophobicity 0.35, interface
residues 7, hydrogen bonds 3, loop share 0.9, binder RMSD 3.5 A, lysines and methionines 3) less the ones that need
Rosetta (shape complementarity, packstat, energies). `complex_metrics(structure, alone=...)` returns one flat dictionary;
the Adaptyv competition's `complex_metrics.py` writes it per AF2 reading (2026-10-22).

## Tests

`tests/tier1_unit/test_ipsae.py`, `tests/tier1_unit/test_ipsae_files.py`, `tests/tier1_unit/test_complex_geometry.py`,
`tests/tier1_unit/test_protein_sequence.py`, `tests/tier1_unit/test_protein_fasta.py`, `tests/tier1_unit/test_protein_composition.py`,
`tests/tier1_unit/test_gpu_alignment.py`, `tests/tier1_unit/test_alignment_scores.py`,
`tests/tier1_unit/test_protein_uniprot_xml.py`, `tests/tier1_unit/test_protein_ph_optimum.py` and
`tests/tier1_unit/test_protein_meltome.py`, with production_suite's `tests/test_uniprot_ph_comments.py`, which reads
every sentence the same in an independent reader, `tests/test_meltome_tm.py`, which holds the rows to the independent
Meltome reader, and
folding_service's `tests/unit/test_ipsae_core.py` and sequence_gradient's
`tests/test_biohub_api.py` as the guards on the names they import.

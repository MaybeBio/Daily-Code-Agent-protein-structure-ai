

Ambiguous Interaction Restraints (AIRs) are HADDOCK3's fundamental mechanism for encoding flexible, experimentally-informed interaction constraints when precise binding interfaces are unknown. AIRs enable you to guide docking calculations through residue-level interaction information without requiring atomically detailed contact specifications. This ambiguity is computationally encoded through CNS TBL format using OR-logic selections, allowing multiple potential interaction partners to satisfy each restraint. The system is particularly powerful for integrating sparse experimental data from mutagenesis, NMR chemical shift perturbations, cross-linking mass spectrometry, and cryo-EM density analysis.

Sources: [librestraints.py](src/haddock/libs/librestraints.py#L225-L282), [rigidbody/__init__.py](src/haddock/modules/sampling/rigidbody/__init__.py#L1-L30)

## AIR Architecture and CNS Integration

AIRs operate at the intersection of experimental data integration and conformational sampling optimization. The architecture follows a hierarchical design where AIRs are defined at the residue level, converted to CNS TBL format, and subsequently applied as distance-based energy terms during both rigid-body sampling and refinement stages. The CNS integration layer parses these TBL files and applies them as ambiguous distance restraints with default parameters of 2.0 Å lower bound, 2.0 Å upper bound, and a force constant controlled by module-specific scaling parameters.

The core transformation from biological knowledge to computational constraints occurs in the `active_passive_to_ambig` function within [`librestraints.py`](src/haddock/libs/librestraints.py#L225-L282). This function accepts active and passive residue lists for both molecular partners and generates a Cartesian product of restraint definitions. Each active residue from molecule 1 generates an AIR against all active and passive residues from molecule 2, and vice versa. The OR-logic in CNS selection syntax enables the ambiguity: a given active residue need satisfy the distance constraint with any one of its potential partners, not all simultaneously.

The CNS TBL format for AIRs follows this pattern:
```
assign (resi <active_res> and segid <segid1>) (
       (resi <partner1_res> and segid <segid2>)
        or
       (resi <partner2_res> and segid <segid2>)
       ...
) 2.0 2.0 0.0
```

The three numerical parameters define the lower distance bound, upper distance bound, and force constant (set to 0.0 in the base TBL file, with actual force constants applied via `ambig_scale` module parameters).

Sources: [librestraints.py](src/haddock/libs/librestraints.py#L225-L282), [randomairs.cns](src/haddock/modules/sampling/rigidbody/cns/randomairs.cns#L1-L200)

## Active and Passive Residue Semantics

The distinction between active and passive residues is fundamental to AIR functionality and directly impacts how sampling algorithms explore conformational space. Active residues serve as restraint initiation points—they must satisfy at least one AIR during the docking calculation. Passive residues, conversely, can satisfy restraints but do not initiate them. This asymmetry creates a directed search where active residues are "pushed" toward the interface while passive residues provide a broader interaction surface.

This design optimizes computational efficiency by focusing restraint satisfaction on residues with strong experimental evidence of involvement in the interaction. When active residues from both molecules are restrained against each other's active and passive residues, the system creates a bidirectional interface definition that effectively brackets the potential binding region.

For scenarios where only active residue information is available, HADDOCK3 provides automatic passive residue generation through the `passive_from_active_raw` function in [`librestraints.py`](src/haddock/libs/librestraints.py#L694-L753). This algorithm identifies surface residues (using relative accessible surface area calculations with freesasa integration) within a default 6.5 Å radius of active residues. The surface residue detection normalizes calculated solvent accessibility against residue-type-specific reference values derived from NACCESS, ensuring biologically meaningful passive selections.

The passive generation workflow calculates accessible surface area for all residues, applies residue-type-specific normalization factors to compute relative accessibility, filters for surface-exposed residues, then performs neighbor searching around active residues to identify nearby surface candidates. This automated approach significantly reduces manual curation burden while maintaining physically realistic interface definitions.

Sources: [librestraints.py](src/haddock/libs/librestraints.py#L694-L753), [librestraints.py](src/haddock/libs/librestraints.py#L13-L16)

## AIR Generation Methods

HADDOCK3 provides multiple pathways for AIR generation, accommodating different types of experimental data and varying levels of prior knowledge about the interaction interface. The primary methods include manual specification from residue lists, automated generation from experimental restraints, and ab-initio generation for data-free scenarios.

The manual pathway begins with the `haddock3-restraints active_passive_to_ambig` CLI command found in [`active_passive_to_ambig.py`](src/haddock/clis/restraints/active_passive_to_ambig.py#L48-L76). This subcommand accepts two actpass files (with active residues on line 1, passive residues on line 2 for each molecule) and outputs a corresponding TBL file. The CLI wrapper validates that at least one molecule has active residues defined before generation proceeds, preventing degenerate restraint sets. This method provides direct control over which residues participate in interface formation and is ideal when mutagenesis or cross-linking data clearly identifies key interaction sites.

For ab-initio docking without experimental restraints, the `ranair` parameter enables automatic random AIR generation from solvent-accessible surface patches. The [`randomairs.cns`](src/haddock/modules/sampling/rigidbody/cns/randomairs.cns#L1-L200) CNS script implements this functionality by first calculating solvent accessible surface area using a 1.4 Å probe radius, then normalizing values by residue-type-specific reference maximums (e.g., ALA normalized by 107.95 Å², TRP by 249.36 Å²). Surface residues with relative accessibility greater than 0.2 are flagged as potential interaction sites, and random residues are selected from this pool to generate pairwise distance restraints. This approach is currently limited to two-component systems; multi-component docking requires alternative approaches like center-of-mass restraints.

A specialized version of random AIR generation allows you to constrain sampling to specific surface segments rather than the entire molecular surface. The `nrair_X` parameters (where X indexes the molecule) define the number of segments, and `rair_sta_X_Y` / `rair_end_X_Y` parameters define residue ranges for each segment. This enables you to focus docking on biologically plausible interface regions while still allowing ambiguity within those regions.

Sources: [active_passive_to_ambig.py](src/haddock/clis/restraints/active_passive_to_ambig.py#L48-L76), [randomairs.cns](src/haddock/modules/sampling/rigidbody/cns/randomairs.cns#L1-L200), [defaults.yaml](src/haddock/modules/sampling/rigidbody/defaults.yaml#L127-L179)

## Restraint Partitioning and Random Removal

HADDOCK3 implements sophisticated restraint subset sampling through the `randremoval` and `npart` parameters, enabling exploration of alternative satisfaction patterns across models. This mechanism addresses a fundamental challenge in ambiguous docking: different subsets of restraints may be satisfied in different correct binding modes, and systematically testing these subsets increases the probability of identifying the correct interface.

The `get_restraint_subset` generator function in [`librestraints.py`](src/haddock/libs/librestraints.py#L754-L820) implements this functionality using deterministic randomization. When `randremoval=true` and `npart=N`, the restraint set is partitioned into N approximately equal-sized groups, with the first group being removed for each model. The default `npart=2` configuration removes 50% of restraints, while increasing `npart` to 4 would remove 25%. The algorithm uses a fixed seed (default 917) incremented between calls to ensure reproducibility while generating distinct subsets across models.

For example, with 100 AIRs and `npart=2`, each model uses a random subset of approximately 50 restraints. Across 1000 models, this creates an ensemble of solutions where different restraint subsets are satisfied, allowing clustering algorithms to identify consistently satisfied restraint patterns as signals of the true interface. This subset sampling is particularly valuable when experimental data contains false positives or when multiple binding modes are plausible.

The random removal applies during the rigidbody module and can be carried forward to refinement stages via the `previous_ambig` parameter, which propagates the restraint subset from the previous CNS module. This continuity ensures that the same restraint subset guides a trajectory through sampling and refinement, maintaining coherence in the optimization landscape.

Sources: [librestraints.py](src/haddock/libs/librestraints.py#L754-L820), [defaults.yaml](src/haddock/modules/sampling/rigidbody/defaults.yaml#L45-L59)

## Configuration Parameters and Module Integration

AIR behavior is controlled through a comprehensive parameter set that can be configured independently for each workflow stage. The following table summarizes the core AIR-related parameters:

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `ambig_fname` | file | '' | Path to TBL file containing AIRs. Supports both ambiguous and unambiguous restraints in the same file. |
| `previous_ambig` | boolean | false | Reuse restraint information from previous CNS module. Only active if `ambig_fname` is not specified for current module. |
| `unambig_fname` | file | '' | Path to TBL file containing unambiguous restraints. All restraints in this file are always applied. |
| `ambig_scale` | integer | 50 | Force constant applied to AIRs. Higher values increase restraint strength during energy minimization. |
| `randremoval` | boolean | true | Enable random removal of ambiguous restraints for each model. |
| `npart` | integer | 2 | Number of partitions for restraint randomization. Fraction removed = 1/npart. |
| `ranair` | boolean | false | Enable automatic random AIR generation from solvent-accessible surface patches. |
| `nrair_X` | integer | 0 | Number of segments for molecule X from which to sample random AIRs. |

Sources: [defaults.yaml](src/haddock/modules/sampling/rigidbody/defaults.yaml#L21-L127)

The rigidbody module enforces the presence of at least one restraint type through the `restraints_guardrail` method in [`rigidbody/__init__.py`](src/haddock/modules/sampling/rigidbody/__init__.py#L172-L195). This safety mechanism prevents execution of ab-initio docking without proper restraint configuration and provides clear error messages guiding users toward appropriate parameter settings. The validation checks for AIRs, unambiguous restraints, hydrogen bond restraints, center-of-mass restraints, or random AIRs, ensuring that the energy minimization has sufficient guidance terms to produce meaningful solutions.

During refinement stages (flexref, emref, mdref), AIR behavior changes subtly. Refinement modules can automatically generate contact-based AIRs using the [`contactairs.cns`](src/haddock/modules/refinement/emref/cns/contactairs.cns) script, which identifies residues at intermolecular interfaces within 5.0 Å and creates corresponding AIRs with 2.0 Å bounds. This automatic adaptation allows refinement to focus on specific interfacial contacts that emerge during sampling, effectively converting global guidance into local optimization constraints.

Sources: [rigidbody/__init__.py](src/haddock/modules/sampling/rigidbody/__init__.py#L172-L195), [contactairs.cns](src/haddock/modules/refinement/emref/cns/contactairs.cns#L1-L28)

## Validation and TBL Format Checking

The `validate_tbldata` function in [`librestraints.py`](src/haddock/libs/librestraints.py#L461-L520) implements comprehensive TBL format validation, ensuring that user-provided restraint files comply with CNS syntax requirements. The parser recognizes standard CNS selection keywords (name, resn, atom, resi, attr, segi, chem, id, byres, not) and logical connectors (and, or, not, byres), building a parse tree that validates structure and checks for common syntax errors like unclosed parentheses or malformed OR-statements.

The validation operates through a state machine tracking global mode, assign statement parsing, and OR-restraint handling. It detects unclosed quotation marks, validates operator placement, ensures proper nesting of parenthetical expressions, and verifies that numeric parameters appear in correct positions after assign statements. This pre-processing prevents CNS execution failures due to syntax errors and provides immediate feedback during workflow configuration.

For developers extending AIR functionality, understanding the TBL validation logic is essential for creating custom restraint generation tools or modifying existing parsers. The function's state-machine design demonstrates how to robustly handle the line-oriented format of CNS restraint files while maintaining context across multi-line OR-statements and nested selection expressions.

Sources: [librestraints.py](src/haddock/libs/librestraints.py#L461-L520)

## Workflow Integration Example

The [`docking-multiple-tbls-test.cfg`](examples/docking-multiple-ambig/docking-multiple-tbls-test.cfg) configuration demonstrates AIR integration across a complete workflow:

```toml
[rigidbody]
tolerance = 20
sampling = 18
unambig_fname="data/unambig.tbl"
ambig_fname="data/ambig.tbl.tgz"

[flexref]
tolerance = 20
unambig_fname="data/unambig.tbl"
previous_ambig = true

[emref]
unambig_fname="data/unambig.tbl"
previous_ambig = true
```

This workflow starts with both unambiguous restraints (intra-molecular or inter-molecular contacts with specific atom pairs) and ambiguous restraints from compressed TBL files during rigid-body sampling. The refinement stages reuse unambiguous restraints but propagate the AIR subset from the previous stage via `previous_ambig=true`, maintaining consistency through the optimization trajectory.

Sources: [docking-multiple-tbls-test.cfg](examples/docking-multiple-ambig/docking-multiple-tbls-test.cfg#L1-L57)

## Next Steps

For comprehensive understanding of AIR application within the HADDOCK3 architecture, explore the following documentation:

- [Rigid-Body Docking Fundamentals](13-rigid-body-docking-fundamentals) for detailed analysis of how AIRs drive the initial sampling stage
- [Energy Minimization Refinement](16-energy-minimization-refinement) for AIR behavior and contact-based restraint generation during refinement
- [Parameter Reference and Tuning](26-parameter-reference-and-tuning) for advanced configuration of AIR force constants and removal strategies
- [Custom Workflow Design](27-custom-workflow-design) for creating multi-stage docking protocols with evolving restraint sets


**Purpose and Scope**: This page examines how FreeBindCraft handles hydrogen bond networks in protein-protein interface design, covering both PyRosetta and PyRosetta-free implementations for evaluating interface hydrogen bonding and unsaturated hydrogen bond detection.

## Hydrogen Bond Analysis in Interface Scoring

FreeBindCraft implements comprehensive hydrogen bond network evaluation through two parallel approaches: PyRosetta-based analysis and open-source alternatives. The hydrogen bond metrics are critical components of the interface scoring pipeline, providing insights into binding quality and structural stability.

### PyRosetta Implementation

When PyRosetta is available, hydrogen bond analysis is performed using the `InterfaceAnalyzerMover` with explicit hydrogen bond calculation enabled [functions/pyrosetta_utils.py#L31-L50]:

```python
iam = InterfaceAnalyzerMover()
iam.set_interface("A_B")
iam.set_calc_hbond_sasaE(True)  # Enable hydrogen bond SASA energy calculation
iam.apply(pose)
interfacescore = iam.get_all_data()
interface_interface_hbonds = interfacescore.interface_hbonds  # Number of interface H-bonds
```

The PyRosetta implementation also includes buried unsaturated hydrogen bond detection using the `BuriedUnsatHbonds` filter [functions/pyrosetta_utils.py#L88-L90]:

```python
buns_filter = XmlObjects.static_get_filter(
    '<BuriedUnsatHbonds report_all_heavy_atom_unsats="true" scorefxn="scorefxn" '
    'ignore_surface_res="false" use_ddG_style="true" dalphaball_sasa="1" '
    'probe_radius="1.1" burial_cutoff_apo="0.2" confidence="0" />'
)
interface_delta_unsat_hbonds = buns_filter.report_sm(pose)
```

### PyRosetta-Free Alternative Implementation

In PyRosetta-free mode, hydrogen bond metrics are handled through strategic placeholder values designed to maintain compatibility with existing filters while avoiding computational complexity [functions/pr_alternative_utils.py#L576-L581]:

```python
# Fixed placeholder values for metrics that are not currently computed without PyRosetta
interface_interface_hbonds = 5                                      # passes >= 3 (active filter)
interface_delta_unsat_hbonds = 1                                    # passes <= 4 (active filter)
interface_hbond_percentage = 60.0                                   # informational (no active filter)
interface_bunsch_percentage = 0.0                                   # informational (no active filter)
```

These placeholder values are carefully chosen based on extensive testing to ensure they pass active filter thresholds while maintaining realistic expectations for hydrogen bond networks.

## Filter Integration and Thresholds

Hydrogen bond-related metrics are integrated into the filtering system through the default filter configuration. The key hydrogen bond filters include:

- **Interface H-bonds**: Minimum threshold of 3 hydrogen bonds required [settings_filters/default_filters.json]
- **Buried Unsaturated H-bonds**: Maximum threshold of 4 unsatisfied hydrogen bonds allowed

The hydrogen bond percentage metrics are calculated relative to the number of interface residues, providing normalized measures of hydrogen bond density [functions/pyrosetta_utils.py#L95-L98]:

```python
if interface_nres != 0:
    interface_hbond_percentage = (interface_interface_hbonds / interface_nres) * 100
    interface_bunsch_percentage = (interface_delta_unsat_hbonds / interface_nres) * 100
```

## Interface Residue Identification

Accurate hydrogen bond analysis depends on proper interface residue identification. FreeBindCraft uses the `hotspot_residues` function to identify interface residues based on spatial proximity criteria [functions/pr_alternative_utils.py#L473-L485]:

```python
interface_residues_set = hotspot_residues(pdb_file, binder_chain)
interface_residues_pdb_ids = [f"{binder_chain}{pdb_res_num}" for pdb_res_num in interface_residues_set.keys()]
```

This identification is crucial for both hydrogen bond counting and for calculating hydrogen bond density metrics.

## Computational Considerations

The hydrogen bond analysis demonstrates FreeBindCraft's dual-approach strategy:

1. **PyRosetta Mode**: Provides detailed, physically accurate hydrogen bond network analysis including buried unsatisfied hydrogen bond detection
2. **PyRosetta-Free Mode**: Uses strategically chosen placeholder values that maintain filter compatibility while avoiding complex hydrogen bond geometry calculations

This approach ensures that designs can be evaluated consistently regardless of the computational environment, with PyRosetta providing enhanced detail when available.

## Design Implications

For binder design, hydrogen bond networks serve as indicators of:

- **Binding affinity**: More interfacial hydrogen bonds generally correlate with stronger binding
- **Structural specificity**: Well-defined hydrogen bond patterns contribute to binding specificity
- **Design quality**: Low numbers of buried unsatisfied hydrogen bonds indicate well-packed, energetically favorable interfaces

The hydrogen bond metrics work in concert with other interface properties like shape complementarity and surface hydrophobicity to provide a comprehensive assessment of binder quality.

## Next Steps

For complete understanding of interface evaluation, see:
- [Interface Scoring Metrics](18-interface-scoring-metrics) for comprehensive interface analysis
- [Shape Complementarity with sc-rs](9-shape-complementarity-with-sc-rs) for geometric complementarity assessment
- [PyRosetta Bypass Architecture](6-pyrosetta-bypass-architecture) for implementation details of the dual-approach system
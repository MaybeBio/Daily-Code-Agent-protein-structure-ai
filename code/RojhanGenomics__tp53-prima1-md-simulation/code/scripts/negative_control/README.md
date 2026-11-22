# Negative-control simulation: quinuclidine

## Rationale
PRIMA-1 shares a rigid bicyclic quinuclidine core with two flexible
hydroxymethyl substituents and a ketone. To test whether the L1/S3-pocket
dissociation observed for PRIMA-1 (2 of 3 replicates) reflects a
PRIMA-1-specific property rather than a general tendency of this pocket/
force-field combination to disfavor any small ligand, we ran an identical
docking-to-MD pipeline on quinuclidine alone (SMILES: C1CN2CCC1CC2),
the PRIMA-1 scaffold stripped of both hydroxymethyl arms and the ketone.

## Pipeline
1. **Ligand construction**: RDKit ETKDGv3 + MMFF94 (see `build_ligand.py`)
2. **Parameterization**: antechamber (GAFF2, AM1-BCC) + acpype
3. **Docking**: AutoDock Vina 1.2.5, identical blind-docking box as PRIMA-1
   (center 2.869, -0.294, 31.059; size 57x49x57 A; exhaustiveness 32)
   → top pose: -3.41 kcal/mol, contacting 5/9 of the PRIMA-1 pocket residues
   (Leu111, Tyr126, Asn131, Asn268, Ser269)
4. **System construction**: identical protocol to Run1-4 (AMBER99SB-ILDN,
   TIP3P, 7.72 nm cubic box, Cl- neutralization)
5. **Equilibration + 20-ns production**: identical .mdp parameters as
   Run1-4 (see `../../topology/` and main Methods)

## Known pitfall (documented for reproducibility)
An early attempt at this negative control silently placed the ligand in
the wrong reference frame relative to the equilibrated protein coordinates
(a ~5 nm offset), producing an artifactual, non-physical trajectory that
was discarded before production analysis. The corrected build verifies
ligand-pocket proximity (~0.2-0.3 nm) immediately after energy minimization
before proceeding to equilibration - a check now recommended as standard
practice for any new ligand-protein system in this pipeline.

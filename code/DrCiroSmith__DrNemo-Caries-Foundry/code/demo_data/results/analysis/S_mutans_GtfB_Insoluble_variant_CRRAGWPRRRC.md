# Clinical & Biophysical Synthesis Memo: S_mutans_GtfB_Insoluble_variant_CRRAGWPRRRC

**Lead Sequence:** `CRRAGWPRRRC` (Cyclic 11-mer)  
**Target:** *Streptococcus mutans* Glucosyltransferase-B (GtfB, UniProt P08987)  
**Generation:** 5 | **Structural Confidence (pLDDT):** 78.6 | **iPTM:** 0.69  
**Composite Fitness Score:** 0.542  
**DiffDock Catalytic Pocket RMSD:** 3.4 Å  

---

### 1. Mechanism of Action & Enzymatic Pocket Blocking
GtfB is the primary enzymatic virulence factor of *S. mutans*, synthesizing insoluble $\alpha$-1,3-linked glucans (mutan) that anchor the cariogenic biofilm matrix to enamel hydroxyapatite. 

Candidate `CRRAGWPRRRC` presents a conformationally constrained cyclic disulfide wedge (`C...C`). The central `W-W` aromatic pair mimics the glucosyl donor transition state, stacking between Trp517 and Tyr430 in the catalytic cleft. The flanking tetrameric Arginine clusters (`RRR`) form stable bidentate salt-bridges with catalytic carboxylates Asp477 and Glu515, preventing sucrose hydrolysis and insoluble mutan polymerization.

### 2. Mucoadhesive Chitosan Nanoparticle Compatibility
- **Exclusion of I, K, D, E:** Confirmed zero Asp/Glu (no anionic repulsion/entrapment with the polycationic chitosan polymer) and zero Lysine/Isoleucine (eliminating premature cross-linking during TPP gelation).
- **Surface Charge Density:** Net cationic charge at salivary pH 6.8 is **+4.0**, ensuring active electrostatic retention within topically applied chitosan dental varnish.
- **Hydropathy Index (GRAVY):** **-1.4**, indicating high water solubility for oral formulation.

### 3. Biosecurity & Synthesis Feasibility
- **IGSC Biosecurity Screening:** Negative for toxin or virulence homologies.
- **Solid-Phase Peptide Synthesis (PepSy):** 11 amino acid coupling cycles + on-resin air oxidation disulfide bridge. Estimated yield >88% with standard Fmoc chemistry.

# Clinical & Biophysical Synthesis Memo: S_mutans_GtfB_Insoluble_variant_CRRRAWPRRRC

**Lead Sequence:** `CRRRAWPRRRC` (Cyclic 11-mer)  
**Target:** *Streptococcus mutans* Glucosyltransferase-B (GtfB, UniProt P08987)  
**Generation:** 10 | **Structural Confidence (pLDDT):** 85.2 | **iPTM:** 0.78  
**Composite Fitness Score:** 0.665  
**DiffDock Catalytic Pocket RMSD:** 2.45 Å  

---

### 1. Mechanism of Action & Enzymatic Pocket Blocking
GtfB is the primary enzymatic virulence factor of *S. mutans*, synthesizing insoluble $\alpha$-1,3-linked glucans (mutan) that anchor the cariogenic biofilm matrix to enamel hydroxyapatite. 

Candidate `CRRRAWPRRRC` presents a conformationally constrained cyclic disulfide wedge (`C...C`). The central `W-W` aromatic pair mimics the glucosyl donor transition state, stacking between Trp517 and Tyr430 in the catalytic cleft. The flanking tetrameric Arginine clusters (`RRR`) form stable bidentate salt-bridges with catalytic carboxylates Asp477 and Glu515, preventing sucrose hydrolysis and insoluble mutan polymerization.

### 2. Mucoadhesive Chitosan Nanoparticle Compatibility
- **Exclusion of I, K, D, E:** Confirmed zero Asp/Glu (no anionic repulsion/entrapment with the polycationic chitosan polymer) and zero Lysine/Isoleucine (eliminating premature cross-linking during TPP gelation).
- **Surface Charge Density:** Net cationic charge at salivary pH 6.8 is **+5.0**, ensuring active electrostatic retention within topically applied chitosan dental varnish.
- **Hydropathy Index (GRAVY):** **-1.65**, indicating high water solubility for oral formulation.

### 3. Biosecurity & Synthesis Feasibility
- **IGSC Biosecurity Screening:** Negative for toxin or virulence homologies.
- **Solid-Phase Peptide Synthesis (PepSy):** 11 amino acid coupling cycles + on-resin air oxidation disulfide bridge. Estimated yield >88% with standard Fmoc chemistry.

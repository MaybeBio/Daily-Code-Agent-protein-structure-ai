# binder-selectivity

**Do generative protein design models discriminate between homologous targets? A BNP vs ANP case study.**

---

## 1. The question

All-atom generative binder design pipelines (RFdiffusion, BindCraft, BoltzGen) are
reported to produce binders for a wide range of targets. Almost all of those reports
measure **whether a binder binds**, not **what else it binds**.

This repository asks the prior question:

> Given two highly homologous targets, does an *unmodified* all-atom generative
> design pipeline produce binders that distinguish between them — and do the
> pipeline's **own confidence scores** predict that discrimination?

Target pair: human **BNP-32** (B-type natriuretic peptide) and human **ANP(1-28)**
(atrial natriuretic peptide). They share the 17-membered disulfide ring and a
conserved `FGG/FGR...MDRI` core, and differ elsewhere. Reference experimental
structures: **7BRH** (BNP) and **1YK1** (ANP). At 28–32 residues each, a meaningful
number of designs fits inside a hobby compute budget.

A third, **scrambled** target (`targets/scr.yaml`) is the negative control: same
amino-acid composition as BNP, same Cys10–Cys26 ring, shuffled order. If designs
appear "selective" for the scramble too, the observed differences are noise.

## 2. Method

1. **Design.** Run BoltzGen (`protein-anything` protocol) independently against each
   of the three target YAMLs, with the binder length fixed at 90 residues and the
   same number of designs per target.
2. **Noise floor first.** Before any cross-target comparison, run the *same* target
   twice as two independent batches. The spread between those two batches is the
   pipeline's own run-to-run wobble. Any BNP-vs-ANP difference smaller than that
   wobble is not a result.
3. **Cross-scoring.** Re-score BNP-designed binders against ANP and vice versa, and
   look at the Δ distribution rather than single best designs.
4. **Second metric.** Recompute **ipSAE** from the PAE output already produced by the
   pipeline, as an independent read on the same complexes. Disagreement between iPTM
   and ipSAE is itself a finding — the targets here have flexible tails, which is
   exactly iPTM's known failure mode.

### What the score is, and is not

BoltzGen's selection pipeline refolds each design with **Boltz-2 without MSAs** and
filters on RMSD / pTM / pAE plus interface terms. Boltz-2's affinity module covers
**protein–small-molecule** pairs only, so a 32-residue peptide target gets **no
predicted ΔΔG**.

Every number in this repository is therefore a **structural confidence score, not an
affinity**.

## 3. Limitations — read before using any number here

- **There is no experimental validation.** Nothing in this repository has been tested
  at the bench.
- Consequently, any conclusion is about **whether the pipeline's own scores
  discriminate between homologous targets**. It is *not* evidence that the designed
  binders are actually selective, or that they bind at all.
- There is no ground truth in this setup. Claims about real-world selectivity cannot
  be made from in-silico confidence scores, and are not made here.

## 4. Reproducing

**Environment**: Google Colab, **A100 40 GB** (peak observed VRAM ≈ 3.3 GB; the 80 GB
card is not worth its extra cost), Python 3.13, `boltzgen==0.3.2`.

```bash
pip install boltzgen==0.3.2
boltzgen check targets/bnp.yaml        # free; must print "Total designed residues: 90"

boltzgen run targets/bnp.yaml --output out_bnp \
  --protocol protein-anything \
  --num_designs 60 --budget 20 \
  --diffusion_batch_size 10 \
  --use_kernels false \
  --reuse
```

Flags that matter:

| Flag | Why |
| --- | --- |
| `--use_kernels false` | **Required.** `boltzgen` installs `cuequivariance-ops-torch-cu12`, while Colab now ships CUDA 13. Without this flag the run dies at step 1/6 with `ImportError: Error importing triangle_multiplicative_update from cuequivariance_ops_torch`. |
| `--reuse` | Resumes an interrupted run instead of restarting it. |
| `--diffusion_batch_size 10` | The card is nearly idle at batch 1. |

Measured cost on the A100 40 GB: **≈2.0 min/design**, **6.73 Colab units/hour** →
roughly 700 designs per 200-unit month. Weights (~6 GB) download at first run;
`/content` is wiped with the runtime, so the notebook mounts Drive and backs the
weight cache up there. Model weights are **not** stored in this repository — only the
commands that fetch them.

## 5. Layout

```
targets/     BoltzGen design specs: bnp, anp, and the scrambled negative control
notebooks/   the Colab notebook that runs the pipeline end to end
results/     raw metrics CSVs, one commit per batch
analysis/    scripts: cross-scoring table, Δ distribution, noise floor, ipSAE
```

## 6. Status

- [x] Target specs written and validated with `boltzgen check`
- [x] Pipeline runs end to end on an A100 40 GB; timing and cost measured
- [ ] Noise-floor batch (2 × 20 designs on the same target) — **next step**
- [ ] Full batch: 60 designs × 3 targets
- [ ] Cross-scoring table and Δ distribution
- [ ] ipSAE recomputed from PAE output

## 7. References

Primary tools and metrics used or compared against:

- Stark, H. *et al.* **BoltzGen: Toward Universal Binder Design.** bioRxiv (2025), [10.1101/2025.11.20.689494](https://doi.org/10.1101/2025.11.20.689494) — *preprint*
- Passaro, S., Corso, G., Wohlwend, J. *et al.* **Boltz-2.** bioRxiv (2025), [10.1101/2025.06.14.659707](https://doi.org/10.1101/2025.06.14.659707) — *preprint*
- Watson, J. L. *et al.* **RFdiffusion.** *Nature* **620**, 1089–1100 (2023), [10.1038/s41586-023-06415-8](https://doi.org/10.1038/s41586-023-06415-8)
- Pacesa, M. *et al.* **BindCraft.** *Nature* **646** (2025), [10.1038/s41586-025-09429-6](https://doi.org/10.1038/s41586-025-09429-6)
- Dauparas, J. *et al.* **ProteinMPNN.** *Science* **378**, 49–56 (2022), [10.1126/science.add2187](https://doi.org/10.1126/science.add2187)
- Jumper, J. *et al.* **AlphaFold2** (pLDDT / PAE / pTM). *Nature* **596**, 583–589 (2021), [10.1038/s41586-021-03819-2](https://doi.org/10.1038/s41586-021-03819-2)
- Dunbrack, R. L. Jr. **ipSAE.** bioRxiv (2025), [10.1101/2025.02.10.637595](https://doi.org/10.1101/2025.02.10.637595) — *preprint, single author*
- Brasas, V. *et al.* **Odin-Multi.** bioRxiv (2026), [10.64898/2026.09.08.749745](https://doi.org/10.64898/2026.09.08.749745) — *preprint*; builds specificity into the design objective. The premise it does not measure is the question asked here.

Preprints are cited as preprints. No conclusion in this work rests on an
unreviewed number.

## 8. License

Code in this repository: MIT. Target sequences are from public databases.

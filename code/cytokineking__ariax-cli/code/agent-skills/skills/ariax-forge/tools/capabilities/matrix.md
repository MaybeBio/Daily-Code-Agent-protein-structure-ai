# Forge tool guide index

Use this index to compare tools and open the relevant guide. Find available
choices with `ariax forge catalog --task TASK --compact --json`, then inspect
the selected tool/model/mode as described in [capability discovery](https://github.com/cytokineking/ariax-cli/blob/HEAD/agent-skills/skills/ariax-forge/tools/capabilities.md).
The live catalog supplies current modes, resources and terms.

## Design

| Tool or family | Use for | Guide |
| --- | --- | --- |
| `bindcraft2` | AF2-guided design across protein, peptide and antibody formats, including multi-state objectives | [BindCraft2](https://github.com/cytokineking/ariax-cli/blob/HEAD/agent-skills/skills/ariax-forge/tools/bindcraft2.md) |
| `freebindcraft` | AF2-guided binder design with alternative relaxation/scoring routes | [FreeBindCraft](https://github.com/cytokineking/ariax-cli/blob/HEAD/agent-skills/skills/ariax-forge/tools/freebindcraft.md) |
| `boltzgen` | Diffusion binder, peptide and scaffold-conditioned antibody design | [BoltzGen](https://github.com/cytokineking/ariax-cli/blob/HEAD/agent-skills/skills/ariax-forge/tools/boltzgen.md) |
| `rfd3`, `rfd3na` | Conditioned generation with Foundry's protein or nucleic-acid models | [Foundry](https://github.com/cytokineking/ariax-cli/blob/HEAD/agent-skills/skills/ariax-forge/tools/foundry.md) |
| `rfd4` | Joint sequence and all-atom design | [RFd4](https://github.com/cytokineking/ariax-cli/blob/HEAD/agent-skills/skills/ariax-forge/tools/rfd4.md) |
| `rfd4-antibody` | VHH joint sequence and structure generation | [RFd4 antibody](https://github.com/cytokineking/ariax-cli/blob/HEAD/agent-skills/skills/ariax-forge/tools/rfd4-antibody.md) |
| `rfantibody` | Antibody backbone generation, sequencing and prediction | [RFantibody](https://github.com/cytokineking/ariax-cli/blob/HEAD/agent-skills/skills/ariax-forge/tools/rfantibody.md) |
| `genie3` | Conditioned design with target evaluation, filtering or search/refinement | [Genie3](https://github.com/cytokineking/ariax-cli/blob/HEAD/agent-skills/skills/ariax-forge/tools/genie3.md) |
| `proteina-complexa` | Protein design with protein, ligand or motif conditioning | [Proteina-Complexa](https://github.com/cytokineking/ariax-cli/blob/HEAD/agent-skills/skills/ariax-forge/tools/proteina-complexa.md) |
| `pxdesign` | Native diffusion design with preview, extended or custom settings | [PXDesign](https://github.com/cytokineking/ariax-cli/blob/HEAD/agent-skills/skills/ariax-forge/tools/pxdesign.md) |
| `esmfold2-pipeline` | Experimental ESMFold2 inversion with Protenix v2 validation | [Pipeline](https://github.com/cytokineking/ariax-cli/blob/HEAD/agent-skills/skills/ariax-forge/tools/esmfold2-pipeline.md) |
| `igdesign` | Structure-conditioned CDR redesign of a paired antibody with antigen | [IgDesign/IgMPNN](https://github.com/cytokineking/ariax-cli/blob/HEAD/agent-skills/skills/ariax-forge/tools/igdesign.md) |

## Prediction

| Tool or family | Use for | Guide |
| --- | --- | --- |
| `boltz2` | Molecular structure/complex prediction and declared affinity-input modes | [Boltz-2](https://github.com/cytokineking/ariax-cli/blob/HEAD/agent-skills/skills/ariax-forge/tools/boltz2.md), [modes](https://github.com/cytokineking/ariax-cli/blob/HEAD/agent-skills/skills/ariax-forge/tools/boltz2/modes.md) |
| `af2` | Protein monomer or multimer prediction with ColabFold | [AF2](https://github.com/cytokineking/ariax-cli/blob/HEAD/agent-skills/skills/ariax-forge/tools/af2.md) |
| `rf3` | Foundry molecular prediction | [Foundry](https://github.com/cytokineking/ariax-cli/blob/HEAD/agent-skills/skills/ariax-forge/tools/foundry.md) |
| `protenix-models`, `protenix-v2` | Molecular prediction with model-specific MSA, template or constraint features | [Protenix](https://github.com/cytokineking/ariax-cli/blob/HEAD/agent-skills/skills/ariax-forge/tools/protenix-models.md) |
| `biohub-esmfold2`, `biohub-esmfold2-fast` | Standalone sequence-to-protein structure prediction | [Biohub ESM](https://github.com/cytokineking/ariax-cli/blob/HEAD/agent-skills/skills/ariax-forge/tools/biohub-esm.md) |
| `opendde` | Preview molecular prediction | [OpenDDE](https://github.com/cytokineking/ariax-cli/blob/HEAD/agent-skills/skills/ariax-forge/tools/opendde.md) |
| `openbind-0`, `openfold3-preview2` | OpenFold3-family prediction with MSA/template inputs | [OpenFold3/OpenBind](https://github.com/cytokineking/ariax-cli/blob/HEAD/agent-skills/skills/ariax-forge/tools/openfold3.md) |
| Mol-1 | Prepared-JSON molecular prediction | [Mol-1](https://github.com/cytokineking/ariax-cli/blob/HEAD/agent-skills/skills/ariax-forge/tools/mol1.md) |
| `chai1` | Molecular prediction with local MSA, templates or restraints | [Chai-1](https://github.com/cytokineking/ariax-cli/blob/HEAD/agent-skills/skills/ariax-forge/tools/chai1.md) |
| `immunebuilder` | Antibody, VHH or TCR variable-domain structure prediction | [ImmuneBuilder](https://github.com/cytokineking/ariax-cli/blob/HEAD/agent-skills/skills/ariax-forge/tools/immunebuilder.md) |

## Sequence optimization

| Tool or family | Use for | Guide |
| --- | --- | --- |
| `proteinmpnn`, `solublempnn`, `ligandmpnn`, `abmpnn` | Backbone-, ligand- or antibody-conditioned sequence design/scoring | [MPNN](https://github.com/cytokineking/ariax-cli/blob/HEAD/agent-skills/skills/ariax-forge/tools/mpnn.md) |
| `fampnn` | Sequence design/scoring with fixed masks and checkpoint choices | [FAMPNN](https://github.com/cytokineking/ariax-cli/blob/HEAD/agent-skills/skills/ariax-forge/tools/fampnn.md) |
| `caliby` | Fixed-backbone or aligned-ensemble sequence design/scoring | [Caliby](https://github.com/cytokineking/ariax-cli/blob/HEAD/agent-skills/skills/ariax-forge/tools/caliby.md) |
| `esmc-300m`, `esmc-600m`, `esmc-6b` | Sequence embeddings and model likelihood | [Biohub ESM](https://github.com/cytokineking/ariax-cli/blob/HEAD/agent-skills/skills/ariax-forge/tools/biohub-esm.md) |
| `absolute-stability-esm3`, `absolute-stability-saprot` | Learned absolute stability, mutation scans or complex estimates | [Absolute stability](https://github.com/cytokineking/ariax-cli/blob/HEAD/agent-skills/skills/ariax-forge/tools/absolute-stability.md) |
| `spurs` | Mutation stability changes relative to a supplied wild type | [SPURS](https://github.com/cytokineking/ariax-cli/blob/HEAD/agent-skills/skills/ariax-forge/tools/spurs.md) |
| `jms-esm2`, `jms-mpnn`, `jms-esmfold`, `jms-aggregate` | Explicit components of a joint sequence score | [JMS components](https://github.com/cytokineking/ariax-cli/blob/HEAD/agent-skills/skills/ariax-forge/tools/jms-components.md), [semantics](https://github.com/cytokineking/ariax-cli/blob/HEAD/agent-skills/skills/ariax-forge/tools/jms-components/semantics.md) |
| `jms-legacy` | Original JMS TrMRF, TrROS or joint operations | [Original JMS](https://github.com/cytokineking/ariax-cli/blob/HEAD/agent-skills/skills/ariax-forge/tools/jms-legacy.md) |
| `mpnn-acceleration` | Explicit comparison of full-backbone optimization modes | [MPNN acceleration](https://github.com/cytokineking/ariax-cli/blob/HEAD/agent-skills/skills/ariax-forge/tools/mpnn-acceleration.md) |

## Validation and search

| Tool or family | Use for | Guide |
| --- | --- | --- |
| `ipsae`, `interface-scores` | Predicted-complex interface confidence | [ipSAE](https://github.com/cytokineking/ariax-cli/blob/HEAD/agent-skills/skills/ariax-forge/tools/ipsae.md), [interface scores](https://github.com/cytokineking/ariax-cli/blob/HEAD/agent-skills/skills/ariax-forge/tools/interface-scores.md) |
| `tmol` | Protein energy, interface interaction scoring or Cartesian minimization | [Tmol](https://github.com/cytokineking/ariax-cli/blob/HEAD/agent-skills/skills/ariax-forge/tools/tmol.md) |
| `structure-tools`, `foldseek` | Structure preparation, geometry, alignment, clustering or structural database search | [Structure tools](https://github.com/cytokineking/ariax-cli/blob/HEAD/agent-skills/skills/ariax-forge/tools/structure-tools.md) |
| `mmseqs2`, `mmseqs2-gpu`, `mmseqs2-uniref90` | Protein sequence search, clustering, redundancy filtering or alignments | [MMseqs2](https://github.com/cytokineking/ariax-cli/blob/HEAD/agent-skills/skills/ariax-forge/tools/mmseqs2.md) |
| `design-qc` | DSSP, DockQ or reports from existing interface scores | [Design QC](https://github.com/cytokineking/ariax-cli/blob/HEAD/agent-skills/skills/ariax-forge/tools/design-qc.md) |
| `antibody-qc` | Antibody numbering, sequence alerts and repertoire resemblance | [Antibody QC](https://github.com/cytokineking/ariax-cli/blob/HEAD/agent-skills/skills/ariax-forge/tools/antibody-qc.md) |
| `boltz2-acceleration` | Explicit evaluation of a residual optimization | [Boltz-2 acceleration](https://github.com/cytokineking/ariax-cli/blob/HEAD/agent-skills/skills/ariax-forge/tools/boltz2-acceleration.md) |

## Campaigns and workspace

| Tool or family | Use for | Guide |
| --- | --- | --- |
| `base` | Shell/Python and project-local source/bootstrap work | [Base](https://github.com/cytokineking/ariax-cli/blob/HEAD/agent-skills/skills/ariax-forge/tools/base.md), [custom code](https://github.com/cytokineking/ariax-cli/blob/HEAD/agent-skills/skills/ariax-forge/references/custom-code.md) |
| `opendde-harness` | Iterative antibody design with explicit review points | [Harness](https://github.com/cytokineking/ariax-cli/blob/HEAD/agent-skills/skills/ariax-forge/tools/opendde-harness.md) |
| `protein-hunter` | A native composed binder-design campaign | [Protein-Hunter](https://github.com/cytokineking/ariax-cli/blob/HEAD/agent-skills/skills/ariax-forge/tools/protein-hunter.md) |
| Campaign recipes | Join generator, sequence, predictor, scoring and search outputs | [Recipes](https://github.com/cytokineking/ariax-cli/blob/HEAD/agent-skills/skills/ariax-forge/references/campaign-recipes.md), [consensus](https://github.com/cytokineking/ariax-cli/blob/HEAD/agent-skills/skills/ariax-forge/tools/campaign-recipes.md) |
| `lab-feedback` | Save experimental observations or prepare an offline laboratory review draft | [Lab feedback](https://github.com/cytokineking/ariax-cli/blob/HEAD/agent-skills/skills/ariax-forge/tools/lab-feedback.md) |
| Campaign benchmark | Compare retained candidates with declared QC/search settings | [Benchmark](https://github.com/cytokineking/ariax-cli/blob/HEAD/agent-skills/skills/ariax-forge/tools/campaign-benchmark.md) |

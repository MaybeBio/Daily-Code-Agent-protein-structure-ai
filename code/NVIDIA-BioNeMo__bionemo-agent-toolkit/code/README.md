<img src="https://github.com/NVIDIA-BioNeMo/bionemo-agent-toolkit/raw/HEAD/assets/image.jpg" alt="NVIDIA BioNeMo Agent Toolkit" width="100%"/>

# NVIDIA BioNeMo Agent Toolkit

**Turn any agent into a life science expert with NVIDIA BioNeMo skills.**

Protein folding, molecular docking, generative chemistry, genomics analysis,
protein design, and biomarker discovery — a decade of NVIDIA life sciences
libraries, tools, and models, packaged as ready-to-call agent skills.

Each skill gives a coding or scientific agent structured instructions, scripts,
and references to select a tool, prepare inputs, run it, inspect outputs, and
explain results — across both single tasks and multi-step scientific workflows.

## Install
Skills install with the [`skills` CLI](https://github.com/vercel-labs/skills):

```bash
# interactive — pick a skill + install destination
npx skills add NVIDIA-BioNeMo/bionemo-agent-toolkit

# one skill, no prompts
npx skills add NVIDIA-BioNeMo/bionemo-agent-toolkit --skill boltz2-nim --yes

# target a specific agent (repeatable)
npx skills add NVIDIA-BioNeMo/bionemo-agent-toolkit --skill boltz2-nim --agent claude-code
npx skills add NVIDIA-BioNeMo/bionemo-agent-toolkit --skill boltz2-nim --agent codex

# browse the catalog without installing
npx skills add NVIDIA-BioNeMo/bionemo-agent-toolkit --list
```

The repo also ships self-hosted plugin marketplaces:
 - **Codex:** [.agents/plugins/marketplace.json](https://github.com/NVIDIA-BioNeMo/bionemo-agent-toolkit/blob/HEAD/.agents/plugins/marketplace.json)
 - **Claude Code:** [.claude-plugin/marketplace.json](https://github.com/NVIDIA-BioNeMo/bionemo-agent-toolkit/blob/HEAD/.claude-plugin/marketplace.json)
so the `bionemo-agent-toolkit` plugin installs through each agent's native plugin
flow as well. Skills are also discoverable by partner harnesses directly from the repo.

## Skill Catalog

| Product | Description | Skills |
|---------|-------------|--------|
| **Protein Binder Design** | End-to-end de novo binder design workflows — a NIM route and a Proteina-Complexa route. | [`protein-binder-design`](https://github.com/NVIDIA-BioNeMo/bionemo-agent-toolkit/blob/HEAD/workflows/generative-protein-binder-design/protein-binder-design), [`complexa-binder-design`](https://github.com/NVIDIA-BioNeMo/bionemo-agent-toolkit/blob/HEAD/workflows/generative-protein-binder-design/complexa-binder-design) |
| **Generative Virtual Screening workflow** | Generate candidate molecules, dock them to a target, and score binding affinity (GenMol → DiffDock → Boltz-2). | [`drug-discovery-pipeline`](https://github.com/NVIDIA-BioNeMo/bionemo-agent-toolkit/blob/HEAD/nim-skills/meta-skills/drug-discovery-pipeline) |
| **MSA-enabled protein structure prediction workflow** | Build a multiple sequence alignment, then predict structure (MSA-Search → OpenFold3). | [`msa-structure-prediction-pipeline`](https://github.com/NVIDIA-BioNeMo/bionemo-agent-toolkit/blob/HEAD/nim-skills/meta-skills/msa-structure-prediction-pipeline) |
| **Boltz-2** | Biomolecular structure prediction + binding affinity (NIM). | [`boltz2-nim`](https://github.com/NVIDIA-BioNeMo/bionemo-agent-toolkit/blob/HEAD/nim-skills/boltz2-nim) |
| **DiffDock** | Small-molecule docking and binding-pose prediction (NIM). | [`diffdock-nim`](https://github.com/NVIDIA-BioNeMo/bionemo-agent-toolkit/blob/HEAD/nim-skills/diffdock-nim) |
| **Evo 2** | DNA sequence generation and variant scoring (NIM). | [`evo2-nim`](https://github.com/NVIDIA-BioNeMo/bionemo-agent-toolkit/blob/HEAD/nim-skills/evo2-nim) |
| **GenMol** | De novo molecule generation, scaffold decoration, lead optimization (NIM). | [`genmol-nim`](https://github.com/NVIDIA-BioNeMo/bionemo-agent-toolkit/blob/HEAD/nim-skills/genmol-nim) |
| **MolMIM** | Latent-space small-molecule generation and optimization (NIM). | [`molmim-nim`](https://github.com/NVIDIA-BioNeMo/bionemo-agent-toolkit/blob/HEAD/nim-skills/molmim-nim) |
| **MSA-Search** | Multiple sequence alignments via ColabFold (NIM). | [`msa-search-nim`](https://github.com/NVIDIA-BioNeMo/bionemo-agent-toolkit/blob/HEAD/nim-skills/msa-search-nim) |
| **OpenFold2** | Monomer protein structure prediction (NIM). | [`openfold2-nim`](https://github.com/NVIDIA-BioNeMo/bionemo-agent-toolkit/blob/HEAD/nim-skills/openfold2-nim) |
| **OpenFold3** | Biomolecular complex structure prediction (NIM). | [`openfold3-nim`](https://github.com/NVIDIA-BioNeMo/bionemo-agent-toolkit/blob/HEAD/nim-skills/openfold3-nim) |
| **ProteinMPNN** | Inverse folding / sequence design for a target backbone (NIM). | [`proteinmpnn-nim`](https://github.com/NVIDIA-BioNeMo/bionemo-agent-toolkit/blob/HEAD/nim-skills/proteinmpnn-nim) |
| **RFD4-Proteina** | Joint protein structure and sequence design, conditioned generation, and reward-guided search through the NVIDIA hosted API or public NIM container. | [`rfd4-proteina-nim`](https://github.com/NVIDIA-BioNeMo/bionemo-agent-toolkit/blob/HEAD/nim-skills/rfd4-proteina-nim) |
| **RFdiffusion** | De novo protein backbone and binder design (NIM). | [`rfdiffusion-nim`](https://github.com/NVIDIA-BioNeMo/bionemo-agent-toolkit/blob/HEAD/nim-skills/rfdiffusion-nim) |
| **RFD4-Proteina (open model)** | Native model setup, annotated-CIF authoring, generation, search, evaluation, campaign tracking, and delivery. Requires a separate RFProteina model checkout. | [`rfd4-proteina-setup`](https://github.com/NVIDIA-BioNeMo/bionemo-agent-toolkit/blob/HEAD/open-models-skills/rfd4-proteina/rfd4-proteina-setup), [`rfd4-proteina-annotated-cif`](https://github.com/NVIDIA-BioNeMo/bionemo-agent-toolkit/blob/HEAD/open-models-skills/rfd4-proteina/rfd4-proteina-annotated-cif), [`rfd4-proteina-generate`](https://github.com/NVIDIA-BioNeMo/bionemo-agent-toolkit/blob/HEAD/open-models-skills/rfd4-proteina/rfd4-proteina-generate), [`rfd4-proteina-search`](https://github.com/NVIDIA-BioNeMo/bionemo-agent-toolkit/blob/HEAD/open-models-skills/rfd4-proteina/rfd4-proteina-search), [`rfd4-proteina-evaluate`](https://github.com/NVIDIA-BioNeMo/bionemo-agent-toolkit/blob/HEAD/open-models-skills/rfd4-proteina/rfd4-proteina-evaluate), [`rfd4-proteina-autoresearch`](https://github.com/NVIDIA-BioNeMo/bionemo-agent-toolkit/blob/HEAD/open-models-skills/rfd4-proteina/rfd4-proteina-autoresearch), [`rfd4-proteina-commitment-curves`](https://github.com/NVIDIA-BioNeMo/bionemo-agent-toolkit/blob/HEAD/open-models-skills/rfd4-proteina/rfd4-proteina-commitment-curves), [`rfd4-proteina-campaign`](https://github.com/NVIDIA-BioNeMo/bionemo-agent-toolkit/blob/HEAD/open-models-skills/rfd4-proteina/rfd4-proteina-campaign), [`rfd4-proteina-package`](https://github.com/NVIDIA-BioNeMo/bionemo-agent-toolkit/blob/HEAD/open-models-skills/rfd4-proteina/rfd4-proteina-package) |
| **Proteina-Complexa** | Protein binder design for protein and small molecule targets. Combines a pretrained flow-based generative model (built on La-Proteina) with inference-time optimization for high-quality binder generation. | [`complexa-setup`](https://github.com/NVIDIA-BioNeMo/bionemo-agent-toolkit/blob/HEAD/open-models-skills/proteina-complexa/complexa-setup), [`complexa-target`](https://github.com/NVIDIA-BioNeMo/bionemo-agent-toolkit/blob/HEAD/open-models-skills/proteina-complexa/complexa-target), [`complexa-design`](https://github.com/NVIDIA-BioNeMo/bionemo-agent-toolkit/blob/HEAD/open-models-skills/proteina-complexa/complexa-design), [`complexa-sweep`](https://github.com/NVIDIA-BioNeMo/bionemo-agent-toolkit/blob/HEAD/open-models-skills/proteina-complexa/complexa-sweep), [`complexa-evaluate-pdbs`](https://github.com/NVIDIA-BioNeMo/bionemo-agent-toolkit/blob/HEAD/open-models-skills/proteina-complexa/complexa-evaluate-pdbs) |
| **KERMT** | Pretrained graph neural network for molecular property prediction (ADMET). Multi-task extension of GROVER with accelerated data loading via cuik-molmaker. SOTA on real-world ADMET data. | [`kermt-setup`](https://github.com/NVIDIA-BioNeMo/bionemo-agent-toolkit/blob/HEAD/open-models-skills/kermt/skills/kermt-setup), [`kermt-infer`](https://github.com/NVIDIA-BioNeMo/bionemo-agent-toolkit/blob/HEAD/open-models-skills/kermt/skills/kermt-infer), [`kermt-embed`](https://github.com/NVIDIA-BioNeMo/bionemo-agent-toolkit/blob/HEAD/open-models-skills/kermt/skills/kermt-embed), [`kermt-finetune`](https://github.com/NVIDIA-BioNeMo/bionemo-agent-toolkit/blob/HEAD/open-models-skills/kermt/skills/kermt-finetune), [`kermt-continue-pretrain`](https://github.com/NVIDIA-BioNeMo/bionemo-agent-toolkit/blob/HEAD/open-models-skills/kermt/skills/kermt-continue-pretrain), [`kermt-pretrain-scratch`](https://github.com/NVIDIA-BioNeMo/bionemo-agent-toolkit/blob/HEAD/open-models-skills/kermt/skills/kermt-pretrain-scratch), [`kermt-add-cmim-pretrain`](https://github.com/NVIDIA-BioNeMo/bionemo-agent-toolkit/blob/HEAD/open-models-skills/kermt/skills/kermt-add-cmim-pretrain), [`kermt-monitor`](https://github.com/NVIDIA-BioNeMo/bionemo-agent-toolkit/blob/HEAD/open-models-skills/kermt/skills/kermt-monitor) |
| **CodonFM** | Open codon foundation models: set up public Encodon checkpoints, extract coding-sequence embeddings, score masked-codon variants, and fine-tune on labeled data. | [`codonfm-setup`](https://github.com/NVIDIA-BioNeMo/bionemo-agent-toolkit/blob/HEAD/open-models-skills/codonfm/codonfm-setup), [`codonfm-embed`](https://github.com/NVIDIA-BioNeMo/bionemo-agent-toolkit/blob/HEAD/open-models-skills/codonfm/codonfm-embed), [`codonfm-score`](https://github.com/NVIDIA-BioNeMo/bionemo-agent-toolkit/blob/HEAD/open-models-skills/codonfm/codonfm-score), [`codonfm-finetune`](https://github.com/NVIDIA-BioNeMo/bionemo-agent-toolkit/blob/HEAD/open-models-skills/codonfm/codonfm-finetune) |
| **Parabricks** | Agent-ready skills built on Parabricks for accelerated genomic analysis and workflows. | [`parabricks`](https://github.com/NVIDIA-BioNeMo/bionemo-agent-toolkit/blob/HEAD/library-skills/parabricks), [`genomics-workflow-acceleration`](https://github.com/NVIDIA-BioNeMo/bionemo-agent-toolkit/blob/HEAD/library-skills/genomics-workflow-acceleration) |
| **nvMolKit** | GPU-accelerated cheminformatics library for molecular fingerprinting, Tanimoto/cosine similarity, Butina clustering, conformer generation (ETKDGv3), MMFF geometry optimization, and substructure search. | [`nvmolkit-usage`](https://github.com/NVIDIA-BioNeMo/bionemo-agent-toolkit/blob/HEAD/library-skills/nvmolkit-usage) |
| **cuEquivariance** | Build equivariant descriptors and custom group representations, and execute equivariant operations with JAX and PyTorch. | [`cuequivariance`](https://github.com/NVIDIA-BioNeMo/bionemo-agent-toolkit/blob/HEAD/library-skills/cuequivariance), [`cuequivariance-jax`](https://github.com/NVIDIA-BioNeMo/bionemo-agent-toolkit/blob/HEAD/library-skills/cuequivariance-jax), [`cuequivariance-torch`](https://github.com/NVIDIA-BioNeMo/bionemo-agent-toolkit/blob/HEAD/library-skills/cuequivariance-torch) |
| **cuPotential** | Install cuPotential, integrate it with OpenMM, implement custom pair potentials, validate energies and forces, and benchmark simulations. | [`cupotential-install`](https://github.com/NVIDIA-BioNeMo/bionemo-agent-toolkit/blob/HEAD/library-skills/cupotential/cupotential-install), [`cupotential-openmm`](https://github.com/NVIDIA-BioNeMo/bionemo-agent-toolkit/blob/HEAD/library-skills/cupotential/cupotential-openmm), [`cupotential-custom-potentials`](https://github.com/NVIDIA-BioNeMo/bionemo-agent-toolkit/blob/HEAD/library-skills/cupotential/cupotential-custom-potentials), [`cupotential-validate`](https://github.com/NVIDIA-BioNeMo/bionemo-agent-toolkit/blob/HEAD/library-skills/cupotential/cupotential-validate), [`cupotential-benchmark`](https://github.com/NVIDIA-BioNeMo/bionemo-agent-toolkit/blob/HEAD/library-skills/cupotential/cupotential-benchmark) |

## Evaluating NIM Skill Lift

NIM skill evaluation has two levels:

1. **Hosted skill lift with ACES/SkillEvaluator.** The hosted skills listed below ship a
   single, bounded `evals/evals.json` case plus `evals/config.yml`.
   `astra-skill-eval` converts the case into Harbor tasks and runs the same
   prompt both with and without the skill. The task requires a call to the real
   hosted NVIDIA NIM endpoint; whether each agent successfully discovers and
   executes that call is part of the measurement. The ACES default grader
   combines deterministic trajectory checks with LLM judgments to report skill
   lift.
2. **Native Harbor tasks (TODO).** Deterministic RLVR-style graders are planned
   for workflows requiring local GPU deployment, custom scientific scoring, or
   additional infrastructure. They are not yet shipped as supported evaluation
   coverage. These tasks will live under `evals/harbor/` and provide their own
   verifier.

The hosted lift commands below require `NGC_API_KEY` in the invoking shell; each
skill's `evals/config.yml` passes it into the Harbor tasks. No local NIM
deployment is required. The commands below disable the optional Astra viewer
upload, allow up to twice the default agent runtime, and write reports under
`.nv-aces-verify/`.

OpenFold3 and the MSA-Search to OpenFold3 workflow are pending validation. Their
current hosted runs timed out and should not yet be used for pass/fail or model
comparison.

The RFD4-Proteina NIM skill targets the
[released product](https://build.nvidia.com/ipd/rfd4-proteina), with a five-case
dataset covering authenticated hosted inference, public container instructions,
offline preparation, and result interpretation. Its
[live agent benchmark](https://github.com/NVIDIA-BioNeMo/bionemo-agent-toolkit/blob/HEAD/nim-skills/rfd4-proteina-nim/BENCHMARK.md) and a new
service-account signature are pending for this revision;
[offline validation](https://github.com/NVIDIA-BioNeMo/bionemo-agent-toolkit/blob/HEAD/nim-skills/rfd4-proteina-nim/evals/validation-results.json)
does not establish production inference success. See the
[RFD4 bundle notes](https://github.com/NVIDIA-BioNeMo/bionemo-agent-toolkit/blob/HEAD/nim-skills/README.md#rfd4-proteina) for public provenance,
access requirements, and client tests.

- **Evo 2**

  ```bash
  ASTRA_HARBOR_VIEWER_UPLOAD=0 astra-skill-eval evaluate nim-skills/evo2-nim --agent-eval -a claude-code --n-attempts 1 --n-concurrent 1 --timeout-multiplier 2.0 --results-dir "$PWD/.nv-aces-verify"
  ```

- **OpenFold2**

  ```bash
  ASTRA_HARBOR_VIEWER_UPLOAD=0 astra-skill-eval evaluate nim-skills/openfold2-nim --agent-eval -a claude-code --n-attempts 1 --n-concurrent 1 --timeout-multiplier 2.0 --results-dir "$PWD/.nv-aces-verify"
  ```

- **OpenFold3 (pending validation)**

  ```bash
  ASTRA_HARBOR_VIEWER_UPLOAD=0 astra-skill-eval evaluate nim-skills/openfold3-nim --agent-eval -a claude-code --n-attempts 1 --n-concurrent 1 --timeout-multiplier 2.0 --results-dir "$PWD/.nv-aces-verify"
  ```

- **Boltz-2**

  ```bash
  ASTRA_HARBOR_VIEWER_UPLOAD=0 astra-skill-eval evaluate nim-skills/boltz2-nim --agent-eval -a claude-code --n-attempts 1 --n-concurrent 1 --timeout-multiplier 2.0 --results-dir "$PWD/.nv-aces-verify"
  ```

- **DiffDock**

  ```bash
  ASTRA_HARBOR_VIEWER_UPLOAD=0 astra-skill-eval evaluate nim-skills/diffdock-nim --agent-eval -a claude-code --n-attempts 1 --n-concurrent 1 --timeout-multiplier 2.0 --results-dir "$PWD/.nv-aces-verify"
  ```

- **GenMol**

  ```bash
  ASTRA_HARBOR_VIEWER_UPLOAD=0 astra-skill-eval evaluate nim-skills/genmol-nim --agent-eval -a claude-code --n-attempts 1 --n-concurrent 1 --timeout-multiplier 2.0 --results-dir "$PWD/.nv-aces-verify"
  ```

- **MolMIM**

  ```bash
  ASTRA_HARBOR_VIEWER_UPLOAD=0 astra-skill-eval evaluate nim-skills/molmim-nim --agent-eval -a claude-code --n-attempts 1 --n-concurrent 1 --timeout-multiplier 2.0 --results-dir "$PWD/.nv-aces-verify"
  ```

- **RFdiffusion**

  ```bash
  ASTRA_HARBOR_VIEWER_UPLOAD=0 astra-skill-eval evaluate nim-skills/rfdiffusion-nim --agent-eval -a claude-code --n-attempts 1 --n-concurrent 1 --timeout-multiplier 2.0 --results-dir "$PWD/.nv-aces-verify"
  ```

- **MSA-Search**

  ```bash
  ASTRA_HARBOR_VIEWER_UPLOAD=0 astra-skill-eval evaluate nim-skills/msa-search-nim --agent-eval -a claude-code --n-attempts 1 --n-concurrent 1 --timeout-multiplier 2.0 --results-dir "$PWD/.nv-aces-verify"
  ```

- **ProteinMPNN**

  ```bash
  ASTRA_HARBOR_VIEWER_UPLOAD=0 astra-skill-eval evaluate nim-skills/proteinmpnn-nim --agent-eval -a claude-code --n-attempts 1 --n-concurrent 1 --timeout-multiplier 2.0 --results-dir "$PWD/.nv-aces-verify"
  ```

- **MSA-Search to OpenFold3 workflow (pending validation)**

  ```bash
  ASTRA_HARBOR_VIEWER_UPLOAD=0 astra-skill-eval evaluate nim-skills/meta-skills/msa-structure-prediction-pipeline --agent-eval -a claude-code --n-attempts 1 --n-concurrent 1 --timeout-multiplier 2.0 --results-dir "$PWD/.nv-aces-verify"
  ```

- **Generative virtual screening workflow**

  ```bash
  ASTRA_HARBOR_VIEWER_UPLOAD=0 astra-skill-eval evaluate nim-skills/meta-skills/drug-discovery-pipeline --agent-eval -a claude-code --n-attempts 1 --n-concurrent 1 --timeout-multiplier 2.0 --results-dir "$PWD/.nv-aces-verify"
  ```

## Evaluating RFD4-Proteina Open-Model Skills

The nine [RFD4-Proteina open-model skills](https://github.com/NVIDIA-BioNeMo/bionemo-agent-toolkit/blob/HEAD/open-models-skills/rfd4-proteina/README.md)
carry their own evaluation datasets and are imported unsigned. Their native
model tasks require the runtime and inputs described in each dataset. In
particular, the [setup smoke evaluation](https://github.com/NVIDIA-BioNeMo/bionemo-agent-toolkit/blob/HEAD/open-models-skills/rfd4-proteina/rfd4-proteina-setup/evals/EVAL.md)
needs a writable model checkout at `RFPROTEINA_ROOT` inside each sandbox and GPU
access. Installing these skills or running their offline helper tests does not
provision that environment or establish a live Tier 3 pass.

Every skill is a directory with a `SKILL.md` (YAML frontmatter + instructions),
optional `references/`, and optional `scripts/`. The generated aggregate lives in
[`skills/bionemo-agent-toolkit/`](https://github.com/NVIDIA-BioNeMo/bionemo-agent-toolkit/blob/HEAD/skills/bionemo-agent-toolkit). For compatibility
with the native plugin marketplaces, [`plugins`](https://github.com/NVIDIA-BioNeMo/bionemo-agent-toolkit/blob/HEAD/plugins) temporarily remains a
symlink to `skills`.

## License

The toolkit uses these default licenses, with separately licensed bundles
retaining their source terms:

- **Source code** (scripts, tests, build tooling): [Apache-2.0](https://github.com/NVIDIA-BioNeMo/bionemo-agent-toolkit/blob/HEAD/LICENSE-APACHE-2.0)
- **Skills and documentation** (SKILL.md, workflows, READMEs): [CC-BY-4.0](https://github.com/NVIDIA-BioNeMo/bionemo-agent-toolkit/blob/HEAD/LICENSE-CC-BY-4.0)
- **Imported RFD4-Proteina Rosetta helpers and regression tests**: BSD-3-Clause,
  with CC-BY-4.0 for their skill text and documentation. See the
  [bundle attribution](https://github.com/NVIDIA-BioNeMo/bionemo-agent-toolkit/blob/HEAD/open-models-skills/rfd4-proteina/README.md).

See [LICENSE](https://github.com/NVIDIA-BioNeMo/bionemo-agent-toolkit/blob/HEAD/LICENSE) for the license statement. Individual skills may reference
third-party data sources with their own terms; consult each skill's references
and the [NOTICE](https://github.com/NVIDIA-BioNeMo/bionemo-agent-toolkit/blob/HEAD/NOTICE) file.

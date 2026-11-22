# RFDiffusion Parameter Guidance

Field types, required flags, and limits, plus the full `contigs` pattern
syntax, live in the canonical schema in [`api.md`](https://github.com/NVIDIA-BioNeMo/bionemo-agent-toolkit/blob/HEAD/nim-skills/rfdiffusion-nim/references/api.md) under **Request Body
Schema** and **Contigs Language Reference**. This file is usage guidance only.

## De Novo Hosted Quirk

For de novo inline requests, include a minimal dummy PDB because live hosted
validation rejects requests that omit both `input_pdb` and `input_pdb_asset`.

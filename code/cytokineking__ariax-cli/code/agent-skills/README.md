# Ariax agent guides

These guides ship with `ariax-cli`. Install the CLI with
`npm install --global ariax-cli`, then read the shared entry point:

```sh
ariax skills --read --json
```

Use [engine choice](https://github.com/cytokineking/ariax-cli/blob/HEAD/agent-skills/core/engine-choice.md) to select a managed protocol or
Forge. Read the selected guide and its live schema or catalog entry:

```sh
ariax skills PROTOCOL --read --json
ariax skills forge --read --json
# Locate only one native tool's references and examples:
ariax skills forge --tool GUIDE --json
ariax skills forge --reference GUIDE --read --json
```

Managed protocol guides cover [BindCraft](https://github.com/cytokineking/ariax-cli/blob/HEAD/agent-skills/skills/ariax-bindcraft/SKILL.md),
[BindCraft2](https://github.com/cytokineking/ariax-cli/blob/HEAD/agent-skills/skills/ariax-bindcraft2/SKILL.md), [BoltzGen](https://github.com/cytokineking/ariax-cli/blob/HEAD/agent-skills/skills/ariax-boltzgen/SKILL.md),
[PXDesign](https://github.com/cytokineking/ariax-cli/blob/HEAD/agent-skills/skills/ariax-pxdesign/SKILL.md) and
[ESMFold2-pipeline](https://github.com/cytokineking/ariax-cli/blob/HEAD/agent-skills/skills/ariax-esmfold2-pipeline/SKILL.md).
[Forge discovery](https://github.com/cytokineking/ariax-cli/blob/HEAD/agent-skills/skills/ariax-forge/tools/capabilities.md) explains how to find
native tools and their guide IDs.

For VHH generation, `ariax skills forge --tool rfd4-antibody --json` locates the
[RFd4 antibody guide](https://github.com/cytokineking/ariax-cli/blob/HEAD/agent-skills/skills/ariax-forge/tools/rfd4-antibody.md) and its fixture.

Use [managed lifecycle](https://github.com/cytokineking/ariax-cli/blob/HEAD/agent-skills/core/managed-projects.md) for preparation, pricing,
recovery and results; [campaign planning](https://github.com/cytokineking/ariax-cli/blob/HEAD/agent-skills/core/campaigns.md) for sizing and
scaling; and [interpretation](https://github.com/cytokineking/ariax-cli/blob/HEAD/agent-skills/core/interpretation.md) for result metrics.
[Raw REST examples](https://github.com/cytokineking/ariax-cli/blob/HEAD/agent-skills/core/raw-curl.md) are available when the CLI cannot be used.
[Storage usage, browsing and deletion](https://github.com/cytokineking/ariax-cli/blob/HEAD/agent-skills/core/storage.md) covers cached measurements,
bounded safe pages, supported downloads, authorized whole-project deletion,
exact-request recovery and read-only cleanup waiting.
Starter files in `examples/` must be validated against the live protocol schema
before submission.

Licensed under the Elastic License 2.0.

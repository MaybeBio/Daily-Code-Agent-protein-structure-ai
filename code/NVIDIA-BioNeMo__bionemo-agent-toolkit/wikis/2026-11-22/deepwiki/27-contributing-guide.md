# Contributing Guide

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [CONTRIBUTING.md](CONTRIBUTING.md)

</details>



The BioNeMo Agent Toolkit is an open-source project that thrives on community contributions. This guide outlines the technical workflow, standards, and legal requirements for contributing to the codebase, ensuring that all additions—whether they are new NIM skills, workflow orchestrations, or library enhancements—maintain the high quality and interoperability expected of the toolkit.

## Contribution Workflow

The project follows a standard "fork-and-pull" model common in open-source development. Contributors are expected to maintain the repository's structural integrity by following specific branching and file conventions.

### Step-by-Step Lifecycle

1.  **Issue Reporting**: Before starting work, contributors should search existing issues [CONTRIBUTING.md:9-10](). New issues should provide clear reproduction steps and context [CONTRIBUTING.md:10-10]().
2.  **Forking and Branching**: Fork the repository and create a feature-specific branch from `main` [CONTRIBUTING.md:15-15]().
3.  **Development**: Implement changes following the toolkit's skill and file conventions [CONTRIBUTING.md:16-16]().
4.  **DCO Sign-off**: Every commit must be signed off to certify ownership and licensing compliance [CONTRIBUTING.md:17-17]().
5.  **Pull Request (PR)**: Submit a PR against the `main` branch with a detailed description of the motivation and implementation [CONTRIBUTING.md:18-18]().
6.  **Review and Merge**: Address feedback from maintainers until approval and subsequent merge [CONTRIBUTING.md:19-19]().

### Contribution Data Flow
The following diagram illustrates the path a contribution takes from a local environment to the upstream `main` branch.

**Contribution Lifecycle Diagram**
```mermaid
graph TD
    subgraph "Contributor_Space"
        "Fork"["Fork: bionemo-agent-toolkit"]
        "Branch"["git checkout -b prefix/slug"]
        "Commit"["git commit -s -m '... '"]
    end

    subgraph "Code_Entity_Space"
        "Main_Repo"["Upstream: main branch"]
        "PR"["Pull Request"]
        "Review"["Maintainer Review"]
    end

    "Main_Repo" -->|"Fork Operation"| "Fork"
    "Fork" --> "Branch"
    "Branch" --> "Commit"
    "Commit" -->|"Push & Open"| "PR"
    "PR" --> "Review"
    "Review" -->|"Approved"| "Main_Repo"
    "Review" -->|"Request Changes"| "Branch"
```
Sources: [CONTRIBUTING.md:12-19]()

## Branch Naming Conventions

To maintain a clean and searchable history, the toolkit enforces a prefix-based naming convention for branches [CONTRIBUTING.md:21-23]().

| Prefix | Use Case | Example |
| :--- | :--- | :--- |
| `feat/` | New features, skills, or capabilities | `feat/boltz2-multi-chain-support` |
| `fix/` | Bug fixes for existing skills or scripts | `fix/diffdock-nim-timeout` |
| `docs/` | Documentation updates or README improvements | `docs/improve-workflow-readme` |

Sources: [CONTRIBUTING.md:25-29]()

## Developer Certificate of Origin (DCO)

All contributions to the BioNeMo Agent Toolkit must include a "Signed-off-by" line in every commit message [CONTRIBUTING.md:31-35](). This signifies agreement with the Developer Certificate of Origin (DCO) version 1.1 [CONTRIBUTING.md:54-87]().

### Signing Commits
Contributors must use the `-s` or `--signoff` flag when committing [CONTRIBUTING.md:37-41]().

```bash
git commit -s -m "Add new protein design skill"
```

This command automatically appends the signature:
`Signed-off-by: Your Name <your@email.com>` [CONTRIBUTING.md:43-47]().

**DCO Verification Logic**
```mermaid
graph TD
    "Commit_Action"["git commit"] -- "Check for -s flag" --> "Flag_Present"{"-s flag?"}
    "Flag_Present" -- "No" --> "Reject"["PR Blocked: Unsigned Commits"]
    "Flag_Present" -- "Yes" --> "Verify"["Verify Signed-off-by: Name & Email"]
    "Verify" --> "DCO_Agreement"["Contributor Agrees to DCO v1.1"]
    "DCO_Agreement" --> "Accept"["Commit Accepted for Review"]
```
Sources: [CONTRIBUTING.md:31-41](), [CONTRIBUTING.md:54-87]()

## Licensing of Contributions

By submitting a Pull Request, contributors agree that their work will be dual-licensed under the terms specified in the project's root `LICENSE` file [CONTRIBUTING.md:91-93]():

*   **Apache-2.0**: For source code, scripts, and build tooling.
*   **CC-BY-4.0**: For skills, workflow definitions, and documentation.

This dual-licensing ensures that the toolkit's scientific content remains open and attributable while the software infrastructure remains permissive for enterprise use.

Sources: [CONTRIBUTING.md:91-93]()

---
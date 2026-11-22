# Claude Code Plugin

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [.claude-plugin/marketplace.json](.claude-plugin/marketplace.json)

</details>



The **Claude Code Plugin** configuration enables the integration of the BioNeMo Agent Toolkit with Anthropic's Claude Code environment. This integration allows Claude to discover, load, and execute life sciences skills (NIMs, open-model scripts, and library-wrapped tools) as native functions within its reasoning loop. The plugin is defined by a marketplace manifest that points to a structured plugin directory containing the toolkit's skill definitions.

### Plugin Manifest and Metadata

The integration is anchored by the `marketplace.json` file located in the `.claude-plugin/` directory at the repository root. This manifest provides the necessary metadata for Claude Code to identify the plugin's origin, version, and the location of its functional components.

| Field | Value | Description |
| :--- | :--- | :--- |
| `name` | `bionemo-agent-toolkit` | The unique identifier for the plugin. |
| `owner.name` | `NVIDIA BioNeMo` | The entity responsible for the toolkit. |
| `owner.url` | `https://github.com/NVIDIA-BioNeMo/bionemo-agent-toolkit` | The source of truth for the codebase. |
| `metadata.version` | `0.1.0` | The current semantic version of the plugin. |
| `plugins[0].source` | `./plugins/bionemo-agent-toolkit` | The relative path to the plugin's implementation directory. |

**Manifest Structure**
The manifest defines a list of plugins, currently containing a single entry for the toolkit. This entry maps the human-readable description to the source code location used during the installation and discovery process.

Sources: [/.claude-plugin/marketplace.json:1-18]()

---

### Plugin Directory Layout

The plugin's logic and skill definitions reside in `plugins/bionemo-agent-toolkit/`. This directory is structured to support multiple agent platforms (Claude Code and Codex) simultaneously while sharing the core `skills/` logic.

**Directory Structure**
```text
plugins/bionemo-agent-toolkit/
├── .claude-plugin/      # Claude-specific configuration and assets
├── .codex-plugin/       # Codex/OpenAI-specific configuration
└── skills/              # Symbolic links or copies of the toolkit skills
    ├── nim-skills/      # Protein folding, docking, etc.
    ├── open-models/     # KERMT, Proteina-Complexa
    └── library-skills/  # nvMolKit, Parabricks
```

**Data Flow: Skill Discovery**

The following diagram illustrates how the Claude Code environment traverses the repository structure to transform a skill definition (e.g., a NIM endpoint) into a tool available in the Natural Language Space.

**Claude Code Skill Loading Flow**
```mermaid
graph TD
    subgraph "Natural_Language_Space"
        "User_Prompt"["User Prompt"]
        "Claude_Reasoning"["Claude Reasoning Loop"]
    end

    subgraph "Code_Entity_Space"
        "Marketplace_JSON"[".claude-plugin/marketplace.json"]
        "Plugin_Source"["plugins/bionemo-agent-toolkit/"]
        "Skills_Dir"["plugins/bionemo-agent-toolkit/skills/"]
        "Skill_Manifest"[".skillsource.json"]
        "Skill_Markdown"["SKILL.md"]
    end

    "User_Prompt" --> "Claude_Reasoning"
    "Claude_Reasoning" -- "Discovery" --> "Marketplace_JSON"
    "Marketplace_JSON" -- "Points to" --> "Plugin_Source"
    "Plugin_Source" -- "Contains" --> "Skills_Dir"
    "Skills_Dir" -- "Iterates" --> "Skill_Manifest"
    "Skill_Manifest" -- "References" --> "Skill_Markdown"
    "Skill_Markdown" -- "Exposes Tools" --> "Claude_Reasoning"
```

Sources: [/.claude-plugin/marketplace.json:11-17]()

---

### Skill Loading and Execution

Claude Code discovers skills by scanning the directory pointed to by the `source` field in the marketplace manifest. For the BioNeMo Agent Toolkit, this discovery process relies on the standardized skill architecture used throughout the repository.

#### Discovery Mechanism
1. **Manifest Resolution**: Claude reads `/.claude-plugin/marketplace.json` to find the `source` directory [/.claude-plugin/marketplace.json:14-14]().
2. **Recursive Scanning**: The agent scans the `skills/` subdirectory within the plugin source.
3. **Metadata Extraction**: For each skill, Claude parses the `.skillsource.json` manifest and the `SKILL.md` file. These files define the tool's parameters, required environment variables (such as `NGC_API_KEY`), and the command-line interface (CLI) or script used for execution.

#### Bridge: From Code to Agent Tools
The toolkit bridges the gap between raw Python scripts/NIM endpoints and Claude's tool-calling interface by mapping system-level entities to the agent's context.

**Code Entity to Agent Mapping**
```mermaid
graph LR
    subgraph "Code_Entities"
        "NIM_Endpoint"["NIM REST API /post"]
        "Python_Script"["scripts/run_inference.py"]
        "Library_Call"["nvmolkit.fingerprint()"]
    end

    subgraph "Plugin_Bridge"
        "Skill_MD"["SKILL.md Frontmatter"]
        "Skill_Source_JSON"[".skillsource.json"]
    end

    subgraph "Claude_Agent_Context"
        "Tool_Definition"["Claude Tool Definition"]
        "JSON_Schema"["Parameter JSON Schema"]
    end

    "NIM_Endpoint" & "Python_Script" & "Library_Call" --> "Skill_MD"
    "Skill_MD" --> "Skill_Source_JSON"
    "Skill_Source_JSON" --> "Tool_Definition"
    "Tool_Definition" --> "JSON_Schema"
```

### Technical Implementation Details

The plugin uses version `0.1.0` [/.claude-plugin/marketplace.json:9-9]() and is designed to be lightweight, acting as a pointer to the broader toolkit. The description provided in the manifest informs Claude's system prompt about the capabilities of the toolkit, specifically highlighting:
*   Protein folding
*   Molecular docking
*   Generative chemistry
*   Genomics
*   Biomarker discovery

These capabilities are presented to the agent as "ready-to-call tools" [/.claude-plugin/marketplace.json:8-8](). When Claude decides to use a skill, it invokes the underlying implementation via the `plugins/bionemo-agent-toolkit/` path defined in the manifest [/.claude-plugin/marketplace.json:14-14]().

Sources: [/.claude-plugin/marketplace.json:1-18]()

---
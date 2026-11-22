# AI Interfaces: Agent and MCP

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [docs/agent.md](docs/agent.md)
- [docs/mcp.md](docs/mcp.md)
- [src/fastmdxplora/agent/propose.py](src/fastmdxplora/agent/propose.py)
- [src/fastmdxplora/gui/agent_panel.py](src/fastmdxplora/gui/agent_panel.py)
- [src/fastmdxplora/gui/static/agent-panel.js](src/fastmdxplora/gui/static/agent-panel.js)
- [src/fastmdxplora/mcp/__init__.py](src/fastmdxplora/mcp/__init__.py)
- [src/fastmdxplora/mcp/app.py](src/fastmdxplora/mcp/app.py)
- [src/fastmdxplora/mcp/content.py](src/fastmdxplora/mcp/content.py)
- [src/fastmdxplora/mcp/protocol.py](src/fastmdxplora/mcp/protocol.py)
- [src/fastmdxplora/mcp/tools.py](src/fastmdxplora/mcp/tools.py)
- [tests/test_the_agent_panel.py](tests/test_the_agent_panel.py)

</details>



## Purpose and Scope

This page provides a high-level overview of the AI interfaces in FastMDXplora, encompassing natural-language study generation via the built-in Agent and machine-protocol access via the Model Context Protocol (MCP) server. These interfaces allow external AI models, chat applications, and command-line users to translate natural language prompts or structured protocol requests into fully validated study configurations without bypassing core safety or chemical validation routines.

For deep technical details, see the child pages:
- [Agent Proposal Loop and Tools](#5.1)
- [Agent Panel in the GUI](#5.2)
- [MCP Server](#5.3)

Sources: [docs/agent.md:1-33](), [docs/mcp.md:1-20](), [src/fastmdxplora/agent/propose.py:1-41]()

---

## Natural Language Translation to Code Entities

The following diagram illustrates how natural-language instructions from a user or client application flow through the FastMDXplora agent subsystem, utilizing core schema validation and completion handlers.

```mermaid
graph TD
    NL[""Natural Language Prompt""] --> PC[""propose_config()""]
    subgraph "Agent Subsystem"
        PC --> AG[""fastmdxplora.agent.propose""]
        AG --> CF[""Completion Protocol""]
    end
    subgraph "Core Validation Space"
        AG --> VC[""validate_config()""]
        VC --> LE[""ConfigError / Refusal""]
        VC --> RC[""resolved_config.yml""]
    end
    RC --> EX[""fastmdxplora.explore""]

    classDef default fill:#fff,stroke:#333,stroke-width:2px;
```

Title: Natural Language to Configuration Pipeline

Sources: [docs/agent.md:1-43](), [src/fastmdxplora/agent/propose.py:43-120]()

---

## 5.1 Agent Proposal Loop and Tools

The FastMDXplora Agent parses natural language requests into YAML configurations using a tightly bounded proposal and repair loop. Defined in `fastmdxplora.agent.propose`, the system relies on a `Completion` protocol to interface with various AI providers (such as Anthropic, OpenAI, or compatible local servers) `[src/fastmdxplora/agent/propose.py:65-75]()`. 

Every generated configuration must pass through the exact same deterministic validator (`validate_config`) used by the CLI and GUI `[docs/agent.md:35-52]()`. If validation fails, refusal codes are fed back into the repair loop up to a strict attempt ceiling. The agent also incorporates a toolbox (`fastmdxplora.agent.tools`) allowing models to inspect structures and review workspace states before drafting a proposal.

For details, see [Agent Proposal Loop and Tools](#5.1).

Sources: [src/fastmdxplora/agent/propose.py:1-120](), [docs/agent.md:1-65]()

---

## 5.2 Agent Panel in the GUI

The graphical user interface integrates the Agent via a dedicated panel (`agent-panel.js`) and corresponding backend endpoints (`model_endpoint`, `propose_endpoint`, `run_endpoint`) located in `fastmdxplora.gui.agent_panel` `[src/fastmdxplora/gui/static/agent-panel.js:1-60](), [src/fastmdxplora/gui/agent_panel.py:1-30]()`. 

The panel handles provider selection, API key management (stored server-side with strict file permissions to prevent client-side leakage), conversation threads, and records-based answering. It surfaces refusal messages directly to the user to aid configuration learning and provides live telemetry and context receipts.

For details, see [Agent Panel in the GUI](#5.2).

Sources: [src/fastmdxplora/gui/static/agent-panel.js:1-60](), [src/fastmdxplora/gui/agent_panel.py:1-35](), [tests/test_the_agent_panel.py:1-40]()

---

## Model Context Protocol (MCP) Routing Space

The following diagram details how external AI applications communicate with FastMDXplora over the Model Context Protocol (MCP), routing JSON-RPC method calls to application handlers and tool execution routines.

```mermaid
graph TD
    Client[""External AI App / Client""] -->|JSON-RPC over stdio| Server[""fastmdxplora.mcp.app.App.server()""]
    subgraph "Protocol Layer"
        Server --> Meth[""fastmdxplora.mcp.protocol.Server""]
        Meth --> Call[""Call Method Routing""]
    end
    subgraph "Tool Execution Space"
        Call --> ToolList[""TOOLS registry""]
        ToolList --> ToolRun[""Tool.run(Context, arguments)""]
        ToolRun --> Workspace[""Workspace Boundaries""]
    end

    classDef default fill:#fff,stroke:#333,stroke-width:2px;
```

Title: Model Context Protocol Routing and Tool Execution

Sources: [src/fastmdxplora/mcp/app.py:73-116](), [src/fastmdxplora/mcp/protocol.py:1-50](), [src/fastmdxplora/mcp/tools.py:1-70]()

---

## 5.3 MCP Server

FastMDXplora includes a complete Model Context Protocol (MCP) server implementation (`fastmdxplora.mcp`) that exposes study orchestration, configuration checking, structure inspection, and workspace management to external AI applications (`docs/mcp.md:1-20`, `src/fastmdxplora/mcp/app.py:1-80`). 

Operating over standard input/output streams (`serve_stdio`), the MCP server enforces strict workspace boundaries (`Workspace`), handles protocol version negotiation (supporting both modern and legacy eras), and exposes a curated list of tools (`TOOLS`) and resources (guides and study records). All operations maintain the core safety invariant: no study can be saved or executed without passing the deterministic validator.

For details, see [MCP Server](#5.3).

Sources: [src/fastmdxplora/mcp/app.py:1-80](), [src/fastmdxplora/mcp/protocol.py:1-50](), [src/fastmdxplora/mcp/tools.py:1-40](), [docs/mcp.md:1-35]()

---
# Dashboard Shell and Live Telemetry

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [src/fastmdxplora/gui/report_dashboard.py](src/fastmdxplora/gui/report_dashboard.py)
- [src/fastmdxplora/gui/static/dashboard.js](src/fastmdxplora/gui/static/dashboard.js)
- [src/fastmdxplora/gui/static/files-page.js](src/fastmdxplora/gui/static/files-page.js)
- [src/fastmdxplora/gui/static/frame.js](src/fastmdxplora/gui/static/frame.js)
- [src/fastmdxplora/gui/static/icons.js](src/fastmdxplora/gui/static/icons.js)
- [src/fastmdxplora/gui/static/preferences.js](src/fastmdxplora/gui/static/preferences.js)
- [src/fastmdxplora/gui/static/studies.js](src/fastmdxplora/gui/static/studies.js)
- [src/fastmdxplora/gui/static/theme.css](src/fastmdxplora/gui/static/theme.css)
- [src/fastmdxplora/gui/stream.py](src/fastmdxplora/gui/stream.py)
- [src/fastmdxplora/gui/telemetry.py](src/fastmdxplora/gui/telemetry.py)
- [tests/test_a_study_is_tagged.py](tests/test_a_study_is_tagged.py)
- [tests/test_all_studies_as_a_table.py](tests/test_all_studies_as_a_table.py)
- [tests/test_an_answer_cites_what_the_study_recorded.py](tests/test_an_answer_cites_what_the_study_recorded.py)
- [tests/test_every_copy_ticks.py](tests/test_every_copy_ticks.py)
- [tests/test_every_scheme_can_be_read.py](tests/test_every_scheme_can_be_read.py)
- [tests/test_gui.py](tests/test_gui.py)
- [tests/test_live_status.py](tests/test_live_status.py)
- [tests/test_the_frame_fits_the_page.py](tests/test_the_frame_fits_the_page.py)
- [tests/test_the_frame_holds_the_study.py](tests/test_the_frame_holds_the_study.py)
- [tests/test_the_page_is_told_when_the_study_changes.py](tests/test_the_page_is_told_when_the_study_changes.py)
- [tests/test_the_sidebar_begins_and_finds_studies.py](tests/test_the_sidebar_begins_and_finds_studies.py)
- [tests/test_the_sidebar_says_the_study_and_where_its_run_stands.py](tests/test_the_sidebar_says_the_study_and_where_its_run_stands.py)
- [tests/test_the_workspace_says_its_studies.py](tests/test_the_workspace_says_its_studies.py)
- [tests/test_two_studies_chosen_are_offered_beside_the_pointer.py](tests/test_two_studies_chosen_are_offered_beside_the_pointer.py)

</details>



## Purpose and Scope
This page details the architectural design and implementation of the FastMDXplora localhost graphical dashboard shell and its underlying live telemetry subsystem. It covers the framework-free three-column application layout (`frame.js`), the client-side routing and polling engine (`dashboard.js`), the file-backed telemetry writer and health analysis framework (`telemetry.py`), workspace study navigation (`studies.js`), and user preference/theming management (`preferences.js`).

---

## 1. The Three-Column App Shell (`frame.js`)
The FastMDXplora dashboard uses a responsive three-column layout designed to ensure that active simulations or trajectories remain visible while users navigate tasks or inspect analysis reports [tests/test_the_frame_holds_the_study.py:1-11](). 

```
+-----------------------------------------------------------------+
|                         App Shell                               |
|  +--------------+  +-------------------------+  +------------+  |
|  |  Sidebar     |  |       Main Column       |  | Side Panel |  |
|  |  (Study)     |  |  (Dynamic Page Views)   |  | (Log/Files)|  |
|  +--------------+  +-------------------------+  +------------+  |
|  <-- Resizable --> <-------- Fluid -------->  <-- Resizable ->  |
+-----------------------------------------------------------------+
```

### Component Structure
1. **Sidebar (`.sidebar`)**: Houses the active study metadata card, recent workspace studies switcher, system status indicators, and main navigation links [tests/test_the_sidebar_says_the_study_and_where_its_run_stands.py:1-9]().
2. **Main Column (`.main`)**: Hosts dynamic view templates (Overview, Molecular Viewer, Analysis, Report, and Files) via hash-based routing [src/fastmdxplora/gui/static/dashboard.js:126-166]().
3. **Side Panel (`#side-panel`)**: Provides real-time execution telemetry logs (`/api/events`), structured refusals (`kind: "refused"`), explanation blocks (`kind: "why"`), and an interactive file browser (`/api/artifacts`) [tests/test_the_frame_holds_the_study.py:87-148]().

### Layout Persistence and Resizing
Column widths for the sidebar and side panel are bounded and persisted using the browser's `localStorage` API via a lightweight wrapper store [src/fastmdxplora/gui/static/frame.js:18-26](). Dragging separator handles (`.col-handle`) updates CSS custom properties (`--sidebar-width`, `--panel-width`) within pre-defined pixel limits [src/fastmdxplora/gui/static/frame.js:82-121]().

```mermaid
graph TD
    UserAction["User Drags .col-handle"] -->|MouseDown| MoveHandler["frame.js: move()"]
    MoveHandler -->|Calculates Delta| SetWidth["frame.js: setWidth()"]
    SetWidth -->|Enforces Limits| BoundsCheck["Math.max(lim[0], Math.min(lim[1], px))"]
    BoundsCheck -->|Updates CSS Var| DOMUpdate["--sidebar-width / --panel-width"]
    DOMUpdate -->|Persists| LocalStore["localStorage.setItem('fmx.*Width')"]

    subgraph "Code Entity Space"
        MoveHandler
        SetWidth
        LocalStore
    end

    Sources: src/fastmdxplora/gui/static/frame.js:81-121
```

Sources: `src/fastmdxplora/gui/static/frame.js:1-164`, `tests/test_the_frame_holds_the_study.py:1-155`

---

## 2. Routing and Polling Controller (`dashboard.js`)
The frontend application controller (`dashboard.js`) orchestrates navigation, status polling, and state hydration without external frontend frameworks [src/fastmdxplora/gui/static/dashboard.js:1-10]().

### Lifecycle and Polling
Upon `DOMContentLoaded`, `boot()` initializes navigation event listeners, configures polling intervals, fetches initial telemetry, and establishes change streams [src/fastmdxplora/gui/static/dashboard.js:57-72]().

```mermaid
sequenceDiagram
    participant Browser as Browser (DOMContentLoaded)
    participant Boot as dashboard.js: boot()
    participant Poll as dashboard.js: schedulePoll()
    participant Server as _DashboardServer API

    Browser->>Boot: DOMContentLoaded
    Boot->>Boot: wireNavigation(), wireTopBar(), wireSettings()
    Boot->>Boot: navigate(initialHash)
    Boot->>Poll: schedulePoll(0)
    loop Periodic Polling
        Poll->>Server: GET /api/status, /api/metrics, /api/events
        Server-->>Poll: JSON Status & Telemetry Metrics
        Poll->>Browser: Update UI Components & Render Charts
    end

    subgraph "Code Entity Space"
        Boot
        Poll
    end

    Sources: src/fastmdxplora/gui/static/dashboard.js:57-72
```

The polling interval defaults to 3 seconds (`pollIntervalMs = 3000`), dynamically clamped between 1 second and 60 seconds based on server configurations or active stream connectivity [src/fastmdxplora/gui/static/dashboard.js:17-25, 60-61]().

Sources: `src/fastmdxplora/gui/static/dashboard.js:1-176`

---

## 3. File-Backed Telemetry Engine (`telemetry.py`)
Simulation execution telemetry is written directly to disk within the study’s `simulation/` directory via the `TelemetryWriter` class [src/fastmdxplora/gui/telemetry.py:1-17, 122-124](). This design guarantees that monitoring is decoupled from the GUI server and remains fully functional during headless cluster runs.

### Artifact Files
* **`live_status.json`**: Atomic snapshot of current simulation phase, stage, step counts, platform details, and execution health [src/fastmdxplora/gui/telemetry.py:15-167].
* **`live_metrics.csv`**: Time-series log containing physical metrics across simulation steps (potential energy, kinetic energy, total energy, temperature, volume, density, performance speed) [src/fastmdxplora/gui/telemetry.py:16, 29-44].
* **`live_events.log`**: Human-readable event stream recording milestones, stage transitions, and warnings [src/fastmdxplora/gui/telemetry.py:17].

### Health Analysis and Refusal Mapping
The `analyze_health` function inspects recent telemetry metrics and status payloads to detect numerical instabilities (NaN values, sharp energy spikes, abnormal temperatures) or stale processes, returning diagnostic states and natural language explanations [src/fastmdxplora/gui/telemetry.py:48-100, tests/test_gui.py:117-155]().

```mermaid
graph TD
    TelemetryInput["live_status.json & live_metrics.csv"] -->|Read by| AnalyzeHealth["telemetry.py: analyze_health()"]
    AnalyzeHealth --> CheckNaN{Has NaN / Infinite?}
    CheckNaN -->|Yes| FailState["State: failed (NUMERIC_EXPLANATION)"]
    CheckNaN -->|No| CheckSpike{Energy Spike > Threshold?}
    CheckSpike -->|Yes| WarnState["State: warning (ENERGY_EXPLANATION)"]
    CheckSpike -->|No| CheckStale{Timestamp Stale?}
    CheckStale -->|Yes| StaleState["State: warning (STALE_EXPLANATION)"]
    CheckStale -->|No| NormalState["State: normal (NORMAL_EXPLANATION)"]

    subgraph "Code Entity Space"
        AnalyzeHealth
        FailState
        WarnState
        NormalState
    end

    Sources: src/fastmdxplora/gui/telemetry.py:48-100, tests/test_gui.py:117-155
```

Sources: `src/fastmdxplora/gui/telemetry.py:1-1421`, `tests/test_gui.py:91-155`

---

## 4. Studies Sidebar and Workspace (`studies.js`)
The workspace manager (`studies.js`) renders all detected studies in the local workspace directory as interactive cards and summary tables [src/fastmdxplora/gui/static/studies.js:1-11]().

### Key Features
* **Metadata & Tags**: Supports custom user-defined tags and notes stored in study-local metadata files [src/fastmdxplora/gui/static/studies.js:72-136]().
* **Filtering & Search**: Real-time debounce-free searching across system IDs, force fields, states, and user tags [src/fastmdxplora/gui/static/studies.js:104-108]().
* **Comparison Engine**: Allows pairwise comparison of two selected studies, highlighting configuration diffs (via `fastmdx diff` parity) and statistically significant divergences in recorded thermodynamic means [src/fastmdxplora/gui/static/studies.js:1-11]().

Sources: `src/fastmdxplora/gui/static/studies.js:1-180`

---

## 5. Preferences, Theming, and Dialogs (`preferences.js`)
User preferences, viewing options, and modal states are managed entirely on the client side without altering study configuration files on disk [src/fastmdxplora/gui/static/preferences.js:1-11]().

### Theming Architecture
The theme manager (`frame.js`) supports three modes: `system`, `light`, and `dark` [src/fastmdxplora/gui/static/frame.js:28-67](). When `system` is active, it attaches media query listeners (`prefers-color-scheme`) to dynamically toggle document and body data attributes (`document.documentElement.dataset.theme`) [src/fastmdxplora/gui/static/frame.js:41-79]().

### Modal Dialog Management (`FastMDXDialog`)
`FastMDXDialog` governs modal dialogs (preferences popup, citation modal, tag editors) [src/fastmdxplora/gui/static/preferences.js:30-118](). It ensures focus trapping inside active dialogs, handles `Escape` key dismissal, and restores focus to the invoking element upon closure [src/fastmdxplora/gui/static/preferences.js:56-81]().

Sources: `src/fastmdxplora/gui/static/preferences.js:1-173`, `src/fastmdxplora/gui/static/frame.js:28-79`

---
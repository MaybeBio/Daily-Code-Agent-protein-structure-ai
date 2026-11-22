# Running Studies from the GUI

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [src/fastmdxplora/analysis/joining.py](src/fastmdxplora/analysis/joining.py)
- [src/fastmdxplora/gui/exploration.py](src/fastmdxplora/gui/exploration.py)
- [src/fastmdxplora/gui/plan.py](src/fastmdxplora/gui/plan.py)
- [src/fastmdxplora/gui/simulated_time.py](src/fastmdxplora/gui/simulated_time.py)
- [src/fastmdxplora/gui/static/analyze-again.js](src/fastmdxplora/gui/static/analyze-again.js)
- [src/fastmdxplora/gui/static/fixes.js](src/fastmdxplora/gui/static/fixes.js)
- [tests/test_a_button_that_needs_no_words_is_its_icon.py](tests/test_a_button_that_needs_no_words_is_its_icon.py)
- [tests/test_a_fix_is_run_when_asked.py](tests/test_a_fix_is_run_when_asked.py)
- [tests/test_a_joined_run_is_read_as_joined.py](tests/test_a_joined_run_is_read_as_joined.py)
- [tests/test_a_reply_alone_does_not_start_a_run.py](tests/test_a_reply_alone_does_not_start_a_run.py)
- [tests/test_a_residue_is_given_the_state_asked.py](tests/test_a_residue_is_given_the_state_asked.py)
- [tests/test_a_resumed_run_continues_the_one_before.py](tests/test_a_resumed_run_continues_the_one_before.py)
- [tests/test_a_run_is_confirmed_and_said_where_it_was_asked.py](tests/test_a_run_is_confirmed_and_said_where_it_was_asked.py)
- [tests/test_a_stopped_run_is_said_as_far_as_it_got.py](tests/test_a_stopped_run_is_said_as_far_as_it_got.py)
- [tests/test_a_study_is_analysed_again_from_the_gui.py](tests/test_a_study_is_analysed_again_from_the_gui.py)
- [tests/test_a_study_is_extended_in_place.py](tests/test_a_study_is_extended_in_place.py)
- [tests/test_a_study_is_really_extended.py](tests/test_a_study_is_really_extended.py)
- [tests/test_an_agents_config_is_said_as_a_plan.py](tests/test_an_agents_config_is_said_as_a_plan.py)
- [tests/test_each_config_is_a_version_of_the_study.py](tests/test_each_config_is_a_version_of_the_study.py)
- [tests/test_every_refusal_says_its_fix_and_price.py](tests/test_every_refusal_says_its_fix_and_price.py)
- [tests/test_exploration.py](tests/test_exploration.py)
- [tests/test_the_agent_analyses_a_study_again.py](tests/test_the_agent_analyses_a_study_again.py)
- [tests/test_the_agent_runs_windows_again.py](tests/test_the_agent_runs_windows_again.py)
- [tests/test_the_agent_writes_as_it_goes.py](tests/test_the_agent_writes_as_it_goes.py)
- [tests/test_the_pieces_go_back_together.py](tests/test_the_pieces_go_back_together.py)
- [tests/test_the_report_is_written_again.py](tests/test_the_report_is_written_again.py)

</details>



The purpose of this page is to detail the technical mechanisms by which FastMDXplora launches, monitors, extends, repairs, and re-analyzes molecular dynamics studies directly from its zero-dependency localhost graphical user interface. The GUI relies on a conservative exploration layer that validates configurations and delegates heavy compute tasks to isolated child processes executing the standard `python -m fastmdxplora explore` workflow [src/fastmdxplora/gui/exploration.py:1-9]().

---

## 1. Exploration Lifecycle and Process Management

The runtime orchestration of studies initiated from the GUI is managed by `DashboardRuntime` in `src/fastmdxplora/gui/exploration.py`. Before any project directory is created or modified, the GUI validates configuration schemas against registry definitions [src/fastmdxplora/gui/exploration.py:35-46]().

When a user initiates a study configuration from the dashboard, `DashboardRuntime` cleans stale state flags [tests/test_exploration.py:41-66](), checks directory output constraints [tests/test_exploration.py:99-120](), and spawns a background child process running the `explore` command [tests/test_exploration.py:47-61]().

Process liveness and termination differ across platforms to avoid signal translation bugs (such as Windows handling `os.kill(pid, 0)` by terminating processes). The `_process_alive()` function checks platform-specific process states via ctypes/Windows API or POSIX signals without disturbing target workers [src/fastmdxplora/gui/exploration.py:88-122](). Graceful shutdowns (`stop()`) issue a termination signal and enforce a configurable timeout before escalating to forced cleanup [tests/test_exploration.py:122-153]().

```mermaid
graph TD
    A["UserAction: LaunchStudy"] --> B["DashboardRuntime.launch_from_config"]
    B --> C["prepare_run()"]
    C --> D["subprocess.Popen(fastmdxplora explore)"]
    D --> E["DashboardRuntime.snapshot()"]
    E --> F["LiveStatusWriter & Telemetry Poll"]

    subcode["Code Entity Space"]
    style subcode fill:none,stroke:none
    class A,B,C,D,E,F codeNode
    end
```
*Figure 1: Exploration Launch Lifecycle mapping dashboard triggers to process spawning routines.*

**Sources:** `src/fastmdxplora/gui/exploration.py:1-191`, `tests/test_exploration.py:41-153`

---

## 2. In-Place Study Extension and Segment Joining

When an MD study reaches its production duration limit or is interrupted, extending the study does not create a disjointed project; instead, it appends a numbered segment (`segment-001`, `segment-002`, etc.) within the same study container [tests/test_a_study_is_extended_in_place.py:1-48]().

The analysis package handles segment continuity via `fastmdxplora.analysis.joining`, which surveys existing directories, verifies completion flags from checkpoint sidecars, and validates study configurations using a robust digest function (`_config_digest`) that normalizes parameters varying by design (like `duration_ns` or `resume_from`) [src/fastmdxplora/analysis/joining.py:45-155]().

```mermaid
graph TD
    A["survey_segments()"] --> B["SegmentPiece objects"]
    B --> C{"Check Usability"}
    C -->|Unsealed / Gap Found| D["Raise MissingResultError / StudyError"]
    C -->|Clean Segments| E["_config_digest() verification"]
    E --> F["join_segments()"]
    F --> G["Concatenated DCD & .join.json"]

    subcode["Code Entity Space"]
    style subcode fill:none,stroke:none
    end
```
*Figure 2: Segment validation and joining pipeline mapping dataset discovery to integrity checks.*

Key safety refusals enforced during segment inspection include:
* **Gaps:** Missing intermediate segments (e.g., jumping from `segment-001` to `segment-003`) are refused to prevent silent physical discontinuities in downstream correlation analysis [src/fastmdxplora/analysis/joining.py:11-18]().
* **Unsealed checkpoints:** Segments lacking a proper sidecar completion flag are treated as incomplete crashes [src/fastmdxplora/analysis/joining.py:19-22]().
* **Dataset mismatch:** Segments originating from different force fields or non-identical resolved configurations are strictly rejected [src/fastmdxplora/analysis/joining.py:23-28]().

**Sources:** `src/fastmdxplora/analysis/joining.py:32-162`, `tests/test_a_study_is_extended_in_place.py:1-151`, `tests/test_the_pieces_go_back_together.py:34-152`

---

## 3. Fixes and Remediation Engine

When a study stops prematurely or encounters an error, the GUI surfaces actionable remediation routines via `fixes_payload` [tests/test_a_fix_is_run_when_asked.py:23-58](). 

The remediation engine evaluates failure codes stored in the phase manifest and matches them with programmatic fixes (such as executing `fastmdx resume` or rerunning umbrella windows) [tests/test_a_fix_is_run_when_asked.py:53-86](). 

* **Runnable Fixes:** Operations backed by automated CLI commands feature clear pricing metrics (e.g., estimated wall-clock time required to finish remaining frames) and execute via `DashboardRuntime.run_a_fix()` when confirmed by the user [tests/test_a_fix_is_run_when_asked.py:53-86]().
* **Manual Decisions:** Refusals requiring domain-specific human choices (e.g., parameter adjustments or missing dependencies) are surfaced as informational advisories and are blocked from automated execution [tests/test_a_fix_is_run_when_asked.py:60-63]().

**Sources:** `tests/test_a_fix_is_run_when_asked.py:1-161`

---

## 4. Re-running Analysis ("Analyze-Again")

Users can invoke re-analysis of existing trajectories from the GUI without overwriting or invalidating the underlying simulation records. 

The orchestrator `FastMDXplora` supports phase-isolated execution switches (`FASTMDX_DASHBOARD_ACTIVE`) that trigger `_dashboard_writer` to process selected phases (e.g., `["analysis", "report"]`) [tests/test_a_stopped_run_is_said_as_far_as_it_got.py:108-143](). During this process:
1. The simulation phase telemetry (`live_status.json`) remains untouched and preserves its historical state [tests/test_a_stopped_run_is_said_as_far_as_it_got.py:121]().
2. New analysis phase markers are written incrementally as workers complete metrics extraction [tests/test_a_stopped_run_is_said_as_far_as_it_got.py:129-135]().

**Sources:** `tests/test_a_stopped_run_is_said_as_far_as_it_got.py:108-143`

---

## 5. Files Page and Run Notices

The Files page provides a structured window into the run directory workspace. It exposes generated topologies (`topology.pdb`), trajectory chunks (`*.dcd`), configuration backups (`resolved_config.yml`), manifest logs (`manifest.json`), and join sidecars (`*.join.json`).

Run notices display real-time state badges driven by telemetry updates. These notices warn operators of unsealed checkpoints, convergence anomalies, or budget limit approach flags, bridging the gap between raw file persistence and high-level dashboard awareness.

**Sources:** `src/fastmdxplora/gui/exploration.py:156-186`, `src/fastmdxplora/analysis/joining.py:80-88`

---
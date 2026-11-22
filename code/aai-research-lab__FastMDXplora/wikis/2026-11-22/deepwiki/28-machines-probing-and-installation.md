# Machines, Probing and Installation

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [docs/api.md](docs/api.md)
- [docs/remote.md](docs/remote.md)
- [src/fastmdxplora/mcp/remote_tools.py](src/fastmdxplora/mcp/remote_tools.py)
- [src/fastmdxplora/remote/__init__.py](src/fastmdxplora/remote/__init__.py)
- [src/fastmdxplora/remote/api.py](src/fastmdxplora/remote/api.py)
- [src/fastmdxplora/remote/describe.py](src/fastmdxplora/remote/describe.py)
- [src/fastmdxplora/remote/gpu_room.py](src/fastmdxplora/remote/gpu_room.py)
- [src/fastmdxplora/remote/identity.py](src/fastmdxplora/remote/identity.py)
- [src/fastmdxplora/remote/installer.py](src/fastmdxplora/remote/installer.py)
- [src/fastmdxplora/remote/jobs.py](src/fastmdxplora/remote/jobs.py)
- [src/fastmdxplora/remote/machines.py](src/fastmdxplora/remote/machines.py)
- [src/fastmdxplora/remote/plan.py](src/fastmdxplora/remote/plan.py)
- [src/fastmdxplora/remote/probe.py](src/fastmdxplora/remote/probe.py)
- [src/fastmdxplora/remote/send.py](src/fastmdxplora/remote/send.py)
- [src/fastmdxplora/remote/survey.py](src/fastmdxplora/remote/survey.py)
- [src/fastmdxplora/remote/transport.py](src/fastmdxplora/remote/transport.py)
- [tests/test_a_machine_is_inspected_before_it_is_used.py](tests/test_a_machine_is_inspected_before_it_is_used.py)
- [tests/test_a_study_travels_and_comes_back.py](tests/test_a_study_travels_and_comes_back.py)
- [tests/test_an_install_is_confirmed_by_its_plan.py](tests/test_an_install_is_confirmed_by_its_plan.py)
- [tests/test_remote_from_every_interface.py](tests/test_remote_from_every_interface.py)

</details>



## Purpose and Scope

This page documents the remote execution architecture of FastMDXplora. It covers how external target machines (workstations, login nodes, and clusters) are modeled, inspected via low-overhead probe scripts, evaluated for code-parity readiness, provisioned with safe non-root install plans, and managed through automated VRAM resource allocation (`gpu_room`), secure SSH transports, and persistent job tracking.

Sources: `docs/remote.md:1-24` [docs/remote.md:1-24](), `src/fastmdxplora/remote/send.py:1-46` [src/fastmdxplora/remote/send.py:1-46](), `src/fastmdxplora/remote/api.py:1-24` [src/fastmdxplora/remote/api.py:1-24]()

---

## Machine Records and SSH Transport

FastMDXplora does not bundle or implement its own SSH client stack. Instead, it delegates all remote transport to the user's native system `ssh` and `rsync` binaries via `[src/fastmdxplora/remote/transport.py:1-20]()`. This ensures that local configuration directives in `~/.ssh/config` (such as `ProxyJump`, custom keys, certificates, or `Match` blocks) apply identically to automated study transfers.

### Machine Records

Machines are registered locally per user account in user configuration directories rather than embedded within study definitions [src/fastmdxplora/remote/machines.py:1-14](). Each record corresponds to an SSH alias and serializes the state captured during the last inspection.

The `Machine` class [src/fastmdxplora/remote/machines.py:55-64]() maintains structural metadata:
* `name`: The machine's SSH alias or target specifier [src/fastmdxplora/remote/machines.py:59]() (validated by `check_machine_name` in `[src/fastmdxplora/remote/transport.py:55-65]()`).
* `inspected_at`: UTC timestamp string of the survey [src/fastmdxplora/remote/machines.py:60]().
* `inspection`: An `Inspection` object detailing hardware topologies (CPUs, RAM, GPUs, scratch space) [src/fastmdxplora/remote/machines.py:61]().
* `info`: A dictionary mapping python/conda environment paths to output dictionaries from `fastmdx info --json` [src/fastmdxplora/remote/machines.py:62-64]().

```mermaid
title "Transport and Machine Record Architecture"

graph TD
    UserCLI["FastMDXplora CLI / API"] --> LoadMach["load_machine(name)<br/>src/fastmdxplora/remote/machines.py"]
    LoadMach --> MacRecord["Machine Record<br/>src/fastmdxplora/remote/machines.py"]
    MacRecord --> TransInit["Transport(name, interactive=False)<br/>src/fastmdxplora/remote/transport.py"]
    TransInit --> SSHExec["subprocess.run(ssh ...)<br/>src/fastmdxplora/remote/transport.py"]
    SSHExec --> RemoteHost["Remote Host / Cluster Node"]
    
    subgraph "Local User Storage"
        MacRecord
    end
```
Sources: `src/fastmdxplora/remote/machines.py:1-81` [src/fastmdxplora/remote/machines.py:1-81](), `src/fastmdxplora/remote/transport.py:1-140` [src/fastmdxplora/remote/transport.py:1-140]()

### SSH Transport Optimization

To prevent multi-prompt hangs (especially on multi-hop or MFA-protected clusters), the `Transport` class [src/fastmdxplora/remote/transport.py:107-128]() implements session reuse and non-interactive hardening:
* **Batch Mode**: When `interactive=False`, `BatchMode=yes` is enforced via SSH options to cause immediate failure on password/second-factor prompts instead of locking execution [src/fastmdxplora/remote/transport.py:132-133]().
* **Control Master Sockets**: Unix domain sockets are established under `user_config_dir() / "sockets"` or `/tmp` with restricted permissions (`0o700`) to maintain an active connection persist window (`ControlMaster=auto`, `ControlPersist=600`) [src/fastmdxplora/remote/transport.py:80-104, 135-139]().

Sources: `src/fastmdxplora/remote/transport.py:80-165` [src/fastmdxplora/remote/transport.py:80-165]()

---

## Probing, Code Identity, and Readiness

Inspecting a machine reads hardware characteristics and validates environment configurations without modifying remote states `[docs/remote.md:53-56]()`. 

### Probe Scripts and Environments

Remote introspection is executed via bundled shell probe scripts (`PROBE_SCRIPT` in `[src/fastmdxplora/remote/probe.py]`). The inspection scans:
* CPU architecture, total memory, and GPU hardware (including NVIDIA driver capabilities and CUDA version ceilings) `[docs/remote.md:39-40]()`.
* Python/Conda installations (`conda`, `mamba`, `micromamba`) across user and system paths `[docs/remote.md:41, 57-62]()`.
* Container runtimes like Apptainer and pre-built SIF release images `[docs/remote.md:63]()`.
* Cluster scheduler presence (SLURM partitions) and scratch availability `[docs/remote.md:64-65]()`.

### Readiness and Commit Parity

A target machine is considered **ready** only if a specific remote installation contains code identical to the local controlling computer and successfully loads all scientific backends `[docs/remote.md:71-74]`.

The required core backends are defined in `REQUIRED_BACKENDS` `[src/fastmdxplora/remote/machines.py:46-47]()`:
```python
REQUIRED_BACKENDS = ("openmm", "pdbfixer", "openff.toolkit",
                     "openmmforcefields", "rdkit", "propka", "am1bcc")
```
For source checkouts, code parity is evaluated by matching **Git commits** and asserting that the working tree has no uncommitted changes `[docs/remote.md:78-84]()`. If an editable install version string diverges from the active commit hash, execution is halted to prevent schema or default divergence.

Sources: `docs/remote.md:39-85` [docs/remote.md:39-85](), `src/fastmdxplora/remote/machines.py:43-48` [src/fastmdxplora/remote/machines.py:43-48]()

---

## Install Plans and Confirmation

When a target machine lacks the correct environment or code commit, `fastmdx remote install` generates a deterministic **Install Plan** `[docs/remote.md:109-113]()`. 

### Safety and Non-Root Isolation

Install plans guarantee account-level isolation:
* No `sudo` privileges are requested or utilized `[docs/remote.md:136]()`.
* No modifications are written to shell startup profiles (`.bashrc`, `.zshrc`) `[docs/remote.md:136]()`.
* Separate version-specific conda environments (e.g., `fastmdx-2.5.6`) are provisioned so newer dependencies never break older studies `[docs/remote.md:137-138]()`.
* **CUDA Version Pinning**: `cuda-version` is explicitly pinned to match the driver's maximum supported CUDA version (or `12.6`), preventing runtime `CUDA_ERROR_UNSUPPORTED_PTX_VERSION` faults `[docs/remote.md:131-134]()`.

### Confirmation and Token Security

The `install` function in `[src/fastmdxplora/remote/installer.py:68-76]()` enforces strict human-in-the-loop confirmation:
```python
def install(name: str, *, confirm: Callable[[InstallPlan], bool],
            transport: Transport | None = None,
            code: CodeIdentity | None = None,
            local_runner=None) -> InstallOutcome:
```
For non-terminal interfaces (such as GUIs or AI agent MCP servers), authorization is mediated through short-lived cryptographic tokens generated by `plan_yes()` and verified by `confirmed_by()` in `[src/fastmdxplora/remote/installer.py:160-175]()`. These tokens bind directly to a hashed representation of the exact install plan (`plan_digest()`), expiring after 10 minutes (`PLAN_YES_S = 600`) `[src/fastmdxplora/remote/installer.py:54, 140-146]()`.

Sources: `docs/remote.md:109-165` [docs/remote.md:109-165](), `src/fastmdxplora/remote/installer.py:1-122` [src/fastmdxplora/remote/installer.py:1-122]()

---

## Sending Studies, VRAM Allocation and GPU Room

Once a machine is confirmed ready, studies are transferred and executed. Transfer semantics isolate inputs and manage hardware contention.

### Input Safety and Transfer

Only the study's active configuration and local input dependencies under `inputs/` are bundled and sent via `rsync` `[src/fastmdxplora/remote/send.py:3-7]()`. Symbolic links are resolved prior to copying, and paths referencing sensitive parent directories are blocked.

### Workstation GPU Sharing and VRAM Accounting

When targeting local workstations (as opposed to managed clusters running SLURM), multiple studies share available GPUs `[src/fastmdxplora/remote/send.py:21-25]()`. 

The GPU room subsystem (`[src/fastmdxplora/remote/gpu_room.py:1-24]()`) dynamically tracks VRAM utilization:
* **Probe Query**: `GPU_SCRIPT` executes `nvidia-smi` to query GPU indices, UUIDs, total/free memory, and active compute applications mapped to process groups `[src/fastmdxplora/remote/gpu_room.py:63-76]()`.
* **Empirical Cost Learning**: Rather than relying on static estimates, past simulation runs record their memory footprint and particle count in `cost.json` `[src/fastmdxplora/remote/gpu_room.py:11-13]()`.
* **Safety Margin**: Required VRAM is calculated via historical fits scaled by a safety margin factor (`MARGIN = 1.15`) `[src/fastmdxplora/remote/gpu_room.py:47-48]()`.
* **Pinning**: Studies are assigned to the GPU with the fewest concurrent local jobs and the most free memory, locked via `CUDA_VISIBLE_DEVICES` set to the GPU's UUID `[src/fastmdxplora/remote/gpu_room.py:5-7]()`.

```mermaid
title "GPU Room Evaluation and Workload Placement"

graph TD
    SendReq["prepare() / send() request<br/>src/fastmdxplora/remote/send.py"] --> RunGPUQuery["GPU_SCRIPT execution via SSH<br/>src/fastmdxplora/remote/gpu_room.py"]
    RunGPUQuery --> ParseRoom["room_from(found)<br/>src/fastmdxplora/remote/gpu_room.py"]
    ParseRoom --> CalcNeed["need_for(study)<br/>src/fastmdxplora/remote/gpu_room.py"]
    CalcNeed --> FitCheck{"GPUs have sufficient<br/>VRAM + 15% margin?"}
    FitCheck -- "Yes" --> PinGPU["Select optimal GPU & pin<br/>CUDA_VISIBLE_DEVICES=UUID"]
    FitCheck -- "No" --> RefuseSend["Refuse send with deficit metrics<br/>src/fastmdxplora/remote/send.py"]
    PinGPU --> RsyncCopy["Rsync inputs/ and Config<br/>src/fastmdxplora/remote/send.py"]
```
Sources: `src/fastmdxplora/remote/send.py:1-46` [src/fastmdxplora/remote/send.py:1-46](), `src/fastmdxplora/remote/gpu_room.py:1-78` [src/fastmdxplora/remote/gpu_room.py:1-78]()

---

## Job Tracking, Lifecycle, and Retrieval

To ensure durability across terminal closures or client disconnections, remote studies execute as detached background processes within isolated process groups on workstations, or as managed batch jobs (`sbatch`) on clusters `[src/fastmdxplora/remote/send.py:41-43]()`.

### Job Records and States

Job metadata is recorded locally in `user_config_dir() / "jobs/"` as standalone JSON files `[src/fastmdxplora/remote/jobs.py:41-44]()`. 

The lifecycle states mirror standard scheduler terminology (`[src/fastmdxplora/remote/jobs.py:33-38]()`):
* `ready`: Waiting in queue or unallocated.
* `running`: Actively executing simulation/analysis phases.
* `done`: Completed successfully with valid exit codes (`exit_code` written remotely).
* `failed`: Terminated with errors.
* `abandoned`: Cancelled or orphaned.

### Concurrency and File Locking

Because AI agent orchestrators and GUI servers frequently query job statuses asynchronously via threads, job record modifications are strictly serialized using thread-local reentrant locks (`held()` in `[src/fastmdxplora/remote/jobs.py:101-109]`). Atomic file writes utilize temporary scratch files (`tempfile.mkstemp`) followed by `os.replace` to eliminate partial read races `[src/fastmdxplora/remote/jobs.py:112-125]`.

Sources: `src/fastmdxplora/remote/send.py:41-46` [src/fastmdxplora/remote/send.py:41-46](), `src/fastmdxplora/remote/jobs.py:1-110` [src/fastmdxplora/remote/jobs.py:1-110]()

---
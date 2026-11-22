# Bench CLI Tool

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [benchmark/bench](benchmark/bench)
- [benchmark/templates/hpg.slurm.sh.jinja](benchmark/templates/hpg.slurm.sh.jinja)

</details>



The `bench` CLI tool provides a comprehensive benchmarking framework for TorchANI-Amber molecular dynamics simulations. It automates the execution of scaling studies and performance analysis across different system sizes, neural network models, and hardware configurations. The tool supports both local execution and HPC cluster submission with SLURM scheduling.

For information about interpreting benchmark results and performance metrics, see [Performance Testing and Analysis](#5.2).

## CLI Commands Overview

The `bench` tool provides two primary commands implemented using the Typer framework:

| Command | Purpose | Key Options |
|---------|---------|-------------|
| `run` | Execute benchmark simulations | `--model`, `--systems`, `--hpg`, `--tsteps` |
| `plot` | Generate performance plots from results | `--ns-per-day`, `--burn-in-tstep-num`, `--labels` |

**CLI Application Structure**
```mermaid
graph TB
    app["app: Typer(name='bench')"]
    app --> run_cmd["run() command"]
    app --> plot_cmd["plot() command"]
    
    run_cmd --> local_exec["Local Execution"]
    run_cmd --> hpg_submit["HPC Submission"]
    
    plot_cmd --> data_analysis["_plot_single()"]
    plot_cmd --> matplotlib_output["Performance Plots"]
    
    local_exec --> amber_sim["Amber MD Simulation"]
    hpg_submit --> slurm_sched["SLURM Scheduler"]
    
    slurm_sched --> remote_exec["Remote Execution"]
    remote_exec --> amber_sim
```

Sources: [benchmark/bench:21-31](), [benchmark/bench:54-150](), [benchmark/bench:309-340]()

## Run Command

The `run` command orchestrates benchmark execution with extensive configuration options for different simulation scenarios.

### Core Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `--model` | str | "ani2xr" | Neural network model to benchmark |
| `--tsteps` | int | 1000 | Number of MD timesteps to execute |
| `--systems` | List[str] | Auto-detected | System sizes for scaling studies |
| `--hpg` | bool | Auto-detected | Enable HPC cluster submission |
| `--cuda` | bool | Auto-detected | Use CUDA acceleration |

### Benchmark Types

The tool supports different benchmark kinds through the `BenchKind` enum:

```mermaid
graph LR
    bench_kind["--bench-kind"]
    bench_kind --> scaling["BenchKind.SCALING"]
    bench_kind --> remd["BenchKind.REMD"]
    
    scaling --> water_systems["Water box systems<br/>1k-200k atoms"]
    remd --> not_impl["NotImplementedError"]
    
    water_systems --> template["scaling.mdin.jinja"]
```

The scaling benchmark automatically selects water box systems ranging from 1,000 to 200,000 atoms when no specific systems are provided [benchmark/bench:177-200]().

### Configuration Management

Benchmark parameters are managed through the `ScalingConfig` dataclass:

```mermaid
graph TB
    config["ScalingConfig"]
    config --> cuaev["cuaev: bool"]
    config --> cuda["cuda: bool"] 
    config --> cutoff["cutoff: float"]
    config --> tstep_num["tstep_num: int"]
    config --> model["model: str"]
    config --> shake["shake: bool"]
    config --> dump_traj["dump_traj: bool"]
    config --> amber_nb["use_all_amber_nonbond: bool"]
    config --> amber_nl["use_amber_neighborlist: bool"]
    
    config --> json_export["to_json_file()"]
    json_export --> config_json["config.json"]
```

Sources: [benchmark/bench:38-52](), [benchmark/bench:264-274]()

### Execution Workflow

**Local vs HPC Execution Decision Tree**
```mermaid
graph TD
    start["bench run command"]
    start --> hpg_check{"--hpg specified?"}
    
    hpg_check -->|No| hostname_check{"hostname matches<br/>login*.ufhpc?"}
    hpg_check -->|Yes| hpg_true["hpg = True"]
    
    hostname_check -->|Yes| hpg_auto["hpg = True"]
    hostname_check -->|No| hpg_false["hpg = False"]
    
    hpg_true --> slurm_submit["send_to_scheduler()"]
    hpg_auto --> slurm_submit
    hpg_false --> local_exec["Local execution"]
    
    slurm_submit --> sys_exit["sys.exit(0)"]
    
    local_exec --> setup_dirs["Setup output directories"]
    setup_dirs --> system_loop["Iterate over systems"]
    system_loop --> render_mdin["Render mdin template"]
    render_mdin --> copy_files["Copy .prmtop/.inpcrd"]
    copy_files --> run_amber["subprocess.run(cmd)"]
    run_amber --> check_result{"Success?"}
    check_result -->|No| error_output["Print error and break"]
    check_result -->|Yes| next_system["Next system"]
```

Sources: [benchmark/bench:224-237](), [benchmark/bench:280-307]()

## Plot Command

The `plot` command generates performance visualizations from benchmark output data.

### Key Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--burn-in-tstep-num` | int | 50 | Skip initial timesteps in analysis |
| `--ns-per-day` | bool | False | Plot simulation speed vs walltime |
| `--labels` | List[str] | Auto-generated | Custom labels for plot series |
| `--max-num-atoms` | int | 1e12 | Filter systems by atom count |

### Data Processing Pipeline

```mermaid
graph LR
    input_paths["names_or_paths"]
    input_paths --> path_resolution["Resolve paths in ~/IO/ani-amber"]
    
    path_resolution --> system_dirs["System directories"]
    system_dirs --> walltime_data["walltime_ms.dat"]
    system_dirs --> inpcrd_data["inpcrd (atom count)"]
    
    walltime_data --> burn_in["Apply burn-in filter"]
    burn_in --> stats["Calculate mean/std"]
    
    inpcrd_data --> atom_count["Extract num_atoms"]
    
    stats --> plot_data["Plotting data"]
    atom_count --> plot_data
    
    plot_data --> matplotlib_viz["matplotlib visualization"]
    plot_data --> csv_export["CSV export"]
```

The plotting function automatically converts walltime measurements to ns/day performance metrics using the conversion factor `86.4 / means` [benchmark/bench:441-444]().

Sources: [benchmark/bench:309-385](), [benchmark/bench:387-467]()

## HPC Integration

The tool integrates with SLURM schedulers through the `send_to_scheduler` function and Jinja2 templates.

### SLURM Template System

```mermaid
graph TB
    hpg_template["hpg.slurm.sh.jinja"]
    hpg_template --> sbatch_directives["SBATCH directives"]
    hpg_template --> module_loading["Module loading"]
    hpg_template --> env_activation["Environment activation"]
    hpg_template --> bench_execution["bench command execution"]
    
    sbatch_directives --> job_name["--job-name={{ unique_id }}-v{{ version }}-{{ name }}"]
    sbatch_directives --> gpu_resources["--gres=gpu:{{ gpu }}"]
    sbatch_directives --> time_limit["--time={{ hours }}:00:00"]
    
    module_loading --> cuda_mod["CUDA modules"]
    module_loading --> conda_mod["Conda modules"]
    
    env_activation --> install_kinds["Different install_kind options"]
    install_kinds --> modules_env["modules: shared benchmark env"]
    install_kinds --> local_env["local: user conda env"]
    install_kinds --> shared_env["shared-env: group environment"]
```

The template supports multiple installation configurations based on the `install_kind` parameter [benchmark/templates/hpg.slurm.sh.jinja:17-29]().

### GPU Resource Management

| GPU Type | CUDA Version | Environment |
|----------|--------------|-------------|
| `b200:1` | 12.8 | ani-amber-blackwell |
| Standard | 12.4 | ani-amber-bench |
| Shared | 12.4 | ani-amber-gcc1104-cuda1204 |

Sources: [benchmark/templates/hpg.slurm.sh.jinja:1-32](), [benchmark/bench:227-236]()

## Configuration and Templates

### Jinja2 Template Environment

The tool uses a Jinja2 environment configured for strict template processing:

```mermaid
graph LR
    jinja_env["jinja2.Environment"]
    jinja_env --> loader["FileSystemLoader"]
    jinja_env --> strict["StrictUndefined"]
    jinja_env --> autoescape["select_autoescape()"]
    jinja_env --> formatting["trim_blocks + lstrip_blocks"]
    
    loader --> templates_dir["benchmark/templates/"]
    templates_dir --> scaling_template["scaling.mdin.jinja"]
    templates_dir --> slurm_template["hpg.slurm.sh.jinja"]
    
    strict --> template_vars["Template variable validation"]
    autoescape --> security["XSS protection"]
```

### Model-Specific Configuration

The tool automatically configures cutoff distances and CUAEV settings based on the selected model:

| Model Pattern | Cutoff (Å) | CUAEV Enabled |
|---------------|------------|---------------|
| `ani2dr` | 8.0 | True |
| `nutmeg*` | 10.0 | False |
| `aimnet*` | 10.0 | False |
| Default | 5.2 | True for `ani*` models |

Special handling exists for NutMeg models, which require charge file specification [benchmark/bench:282-285]().

Sources: [benchmark/bench:161-167](), [benchmark/bench:239-247](), [benchmark/bench:282-285]()

## Output Management

### Directory Structure

```mermaid
graph TB
    out_root["~/IO/ani-amber/"]
    out_root --> unique_dir["{{ unique_id }}-{{ name }}/"]
    
    unique_dir --> system_dirs["System directories"]
    system_dirs --> water_1k["water-1k/"]
    system_dirs --> water_2_5k["water-2_5k/"]
    system_dirs --> water_etc["..."]
    
    water_1k --> mdin_file["mdin"]
    water_1k --> config_file["config.json"]
    water_1k --> input_files["inpcrd, prmtop"]
    water_1k --> output_files["Output files"]
    
    output_files --> walltime_dat["walltime_ms.dat"]
    output_files --> amber_out["mdout, mdcrd, etc."]
```

### Environment Variables

The tool sets `TORCHANI_AMBER_WALLTIME=1` to enable walltime measurement collection from the Amber integration [benchmark/bench:278]().

### Performance Data Collection

Walltime data is collected per timestep and written to `walltime_ms.dat` files. The plotting system processes this data with configurable burn-in periods to exclude initialization overhead from performance analysis.

Sources: [benchmark/bench:254-259](), [benchmark/bench:288-294](), [benchmark/bench:418-433]()

---
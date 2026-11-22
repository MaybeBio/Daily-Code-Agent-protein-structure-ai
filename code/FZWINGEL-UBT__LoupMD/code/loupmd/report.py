"""The one-screen report of a run: header, physics, plan, gate, setup, speed, licence, warnings.

Made from the run's metadata (``loupmd.provenance``), so the screen and ``metadata.json`` cannot disagree.
"""
from __future__ import annotations

from . import models


def _bytes(n) -> str:
    return f"{n / 2 ** 30:.2f} GiB"


def _model_line(model) -> str:
    name = model["label"] or model["file"]
    head = f", head {model['head']}" if model["head"] else ""
    return f"{name} ({model['file']}, SHA-256 {model['sha256'][:16]}...{head})"


def _structure_line(structure) -> str:
    elements = ", ".join(f"{symbol} {count}" for symbol, count in structure["elements"].items())
    lengths = " x ".join(f"{sum(x * x for x in row) ** 0.5:.2f}" for row in structure["cell"])
    source = structure["source"] or "Atoms"
    repeat = structure["repeat"]
    if repeat and tuple(repeat) != (1, 1, 1):
        source += " x ({}, {}, {})".format(*repeat)
    fixed = f", {structure['fixed_atoms']} fixed" if structure.get("fixed_atoms") else ""
    return f"{source}: {structure['atoms']} atoms ({elements}{fixed}), cell {lengths} A"


def _physics_lines(metadata) -> list:
    integrator, schedule = metadata["integrator"], metadata["schedule"]
    timestep = integrator["timestep_fs"]
    if integrator["scheme"] == "nve":
        first = f"NVE, velocity Verlet, timestep {timestep:g} fs"
        if integrator.get("fixcm"):
            first += ", total momentum removed"
    else:
        if integrator["scheme"] == "mtk":
            first = (f"NPT, Martyna-Tobias-Klein with Nose-Hoover chains of {integrator['tchain']} and "
                     f"{integrator['pchain']} (experimental), timestep {timestep:g} fs, time constants "
                     f"{integrator['tau_fs']:g} fs and {integrator['taup_fs']:g} fs, pressure "
                     f"{integrator['pressure_GPa']:g} GPa, "
                     f"{'the cell keeps its shape' if integrator.get('cell_mode') != 'full' else 'full cell'}")
        elif integrator["scheme"] == "baoab":
            tau = integrator.get("taup_fs")
            first = (f"NPT, Langevin BAOAB with a Langevin-Hoover barostat (experimental), timestep {timestep:g} fs, "
                     f"friction {integrator['friction_per_fs']:.4g}/fs, pressure {integrator['pressure_GPa']:g} GPa, "
                     f"barostat time {'20 / friction' if tau is None else f'{tau:g} fs'}, "
                     f"{'the cell keeps its shape' if integrator.get('cell_mode') != 'full' else 'full cell'}")
        elif integrator["scheme"] == "berendsen" and integrator.get("ensemble") == "npt":
            mask = integrator.get("mask")
            cell = "the cell keeps its shape" if mask is None else f"cell vectors scaled singly, mask {tuple(mask)}"
            first = (f"NPT, Berendsen thermostat and barostat (experimental; not canonical: for equilibration), "
                     f"timestep {timestep:g} fs, time constants {integrator['tau_fs']:g} fs and "
                     f"{integrator['taup_fs']:g} fs, pressure {integrator['pressure_GPa']:g} GPa, compressibility "
                     f"{integrator['compressibility_per_GPa']:g}/GPa, {cell}")
        elif integrator["scheme"] == "berendsen":
            first = (f"NVT, Berendsen thermostat (not canonical: for equilibration), timestep {timestep:g} fs, "
                     f"time constant {integrator['tau_fs']:g} fs")
        elif integrator["scheme"] == "nose_hoover":
            first = (f"NVT, Nose-Hoover chain of {integrator['tchain']}, timestep {timestep:g} fs, time constant "
                     f"{integrator['tau_fs']:g} fs")
        elif integrator["scheme"] == "csvr":
            first = f"NVT, CSVR (Bussi), timestep {timestep:g} fs, time constant {integrator['tau_fs']:g} fs"
        else:
            first = f"NVT, Langevin, timestep {timestep:g} fs, friction {integrator['friction_per_fs']:.4g}/fs"
        if schedule is None:
            first += f", {integrator['temperature_K']:g} K"
        if integrator.get("fixcm"):
            first += ", centre of mass at rest"
    lines = [first]
    if schedule is not None:
        parts = [f"{s['phase']} {s['start_K']:g} -> {s['end_K']:g} K in {s['ps']:g} ps ({s['steps']} steps)"
                 if s["kind"] == "ramp" else f"hold {s['start_K']:g} K for {s['ps']:g} ps ({s['steps']} steps)"
                 for s in schedule["segments"]]
        lines.append("schedule: " + "; ".join(parts))
    steps = metadata["counters"]["steps"]
    lines.append(f"{steps} steps ({steps * timestep / 1000:g} ps) to step {metadata['step']}, seed {metadata['seed']}")
    return lines


def _plan_lines(metadata) -> list:
    plan, gpu = metadata["plan"], metadata["gpu"]
    where = (f"GPU {gpu['index']} ({gpu['name']}, compute capability {gpu['compute_capability']}, driver "
             f"{gpu['driver']})") if gpu else "the GPU"
    if plan.get("execution") == "tiled":
        tiles = f"{plan['tiles']} " if plan.get("tiles") else ""
        why = (f"capacity={plan.get('requested', 'tiled')!r} asked for tiles" if plan.get("tiled_because") == "asked"
               else "the cell does not fit the card whole")
        lines = [f"{tiles}tiles of at most {plan['receivers']:,} atoms on {where} ({why}); the integrator runs on "
                 f"the {plan.get('integrator_on', 'host')}"]
        if plan.get("wavefront"):
            lines.append("the tiles run in the wavefront order: the layer states of a moving band of tiles are "
                         "held, not the whole cell's")
    else:
        lines = [f"the whole system on {where}"]
    if plan["kernels"]:
        layers = f", {plan['interaction_layers']} interaction layers" if plan["interaction_layers"] else ""
        cutoff = f", cutoff {plan['r_max_A']:g} A" if plan["r_max_A"] else ""
        lines.append(f"{plan['kernels']} kernels{layers}{cutoff}; library {plan['library'] or 'unknown'}")
    memory = plan["memory"]
    if memory and plan.get("execution") == "tiled" and memory.get("tiled_global_bytes") is not None:
        # What the plan keeps in pinned host memory: the tile lists' edges, and with host_state the layers' outputs
        # and gradients as well (records written before the flag existed name the lists).
        held = "the tile lists' edges and the layer state" if memory.get("host_state") else "the tile lists' edges"
        lines.append(f"memory: the whole system would need {_bytes(memory['whole_bytes'])}; tiled "
                     f"{_bytes(memory['tiled_global_bytes'] + memory['tile_workspace_bytes'])} planned, "
                     f"{_bytes(memory['free_bytes'])} free on the card"
                     + (f"; {held} in pinned host memory ({_bytes(memory['host_bytes'])})"
                        if memory.get("host_bytes") else ""))
    elif memory:
        lines.append(f"memory: {_bytes(memory['whole_bytes'])} planned, {_bytes(memory['free_bytes'])} "
                     "free on the card")
    disp = metadata.get("dispersion")
    if disp:
        p = disp.get("parameters") or {}
        values = ", ".join(f"{k} {v:g}" for k, v in p.items())
        lines.append(f"dispersion: D3({disp['damping']}) {disp.get('functional') or ''} [{values}], pairs to "
                     f"{disp['pair_cutoff_bohr']:g} bohr, coordination numbers to {disp['cn_cutoff_bohr']:g} bohr, "
                     f"{'three-body term' if disp.get('three_body') else 'no three-body term'}, long range: "
                     f"{disp.get('long_range_used')} ({disp.get('long_range_chosen_by')})".replace("  ", " "))
        cost = disp.get("cost")
        if cost:
            text = f"dispersion cost: {cost['ms_per_evaluation']:.2f} ms per force evaluation on the starting structure"
            if "three_body_ms" in cost:
                text += f", of which the three-body term {cost['three_body_ms']:.2f} ms"
            lines.append(text)
        lines += dispersion_choice_lines(disp.get("long_range_choice"))
    skin = metadata.get("skin")
    if skin and skin["mode"] == "auto":
        measured = skin.get("measured_step_A")
        how = (f"largest step measured {measured:.3f} A" if measured is not None
               else "estimated; too few steps for a measurement")
        lines.append(f"neighbour skin {skin['skin_A']:g} A (auto: {how})")
    lines.append(plan["precision"])
    return lines


def dispersion_choice_lines(choice) -> list:
    """The setup check of ``long_range="auto"`` (PLAN.md S6-D07): every candidate with its deviation from the
    reference, its time and whether it was kept."""
    if not choice:
        return []
    rows = choice.get("candidates") or []
    if all(not row.get("checked") for row in rows):
        return [f"long range: {row['name']} not checked ({row.get('why', '')})" for row in rows] + \
               [f"long range: {left['method']} left out ({left['why']})" for left in choice.get("left_out", [])]
    lines = [f"long range checked against {choice['reference']}:"]
    for row in rows:
        name = row["name"] + (" (chosen)" if row["name"] == choice.get("chosen") else "")
        if "energy_meV_per_atom" not in row:
            lines.append(f"  {name}: dropped, {row.get('why', '')}")
            continue
        text = (f"  {name}: energy {row['energy_meV_per_atom']:.4f} meV/atom, largest force "
                f"{row['max_force_eV_per_A']:.1e} eV/A, stress {row['stress_GPa']:.1e} GPa")
        if row.get("ms") is not None:
            text += f", {row['ms']:.2f} ms"
        if not row.get("kept"):
            text += f"; dropped: {row.get('why', '')}"
        lines.append(text)
    lines += [f"  {left['method']}: left out ({left['why']})" for left in choice.get("left_out", [])]
    return lines


def _gate_line(gate) -> str:
    status = gate["status"]
    if status == "skipped":
        return 'skipped (check="skip"): run `loupmd validate` or pass check="gate" to compare with MACE float64'
    if status == "unavailable":
        return f"unavailable: {gate.get('why', 'the references could not be computed')}"
    worst = gate["worst"]
    return (f"{status}: worst ratios energy {worst['energy_ratio']:.2f}, force {worst['force_ratio']:.2f}, stress "
            f"{worst['stress_ratio']:.2f} of the 3 allowed, on {len({row['config'] for row in gate['rows']})} "
            "rattled copies")


def _speed_line(metadata) -> str:
    timing, counters = metadata["timing"], metadata["counters"]
    if not timing["ms_per_step"]:
        return "no step ran"
    return (f"{timing['ms_per_step']:.3f} ms/step with output ({timing['engine_ms_per_step']:.3f} in the engine), "
            f"{timing['ns_per_day']:.1f} ns/day, {timing['atom_steps_per_s'] / 1e6:.2f} million atom-steps/s; "
            f"{counters['rebuilds']} neighbour rebuilds, {counters['dangerous_builds']} dangerous")


def _licence_line(model) -> str:
    text = models.LICENCE_TEXT.get(model["licence"])
    return ((f"model: {text}" if text else "model: not in the label table, see its publisher")
            + "; LoupMD: MIT, its engine library LGPL-2.1-or-later")


def _block(title, lines) -> list:
    return [title] + ["  " + line for line in lines]


def text(metadata) -> str:
    """The report of a run from its metadata."""
    out = [f"LoupMD {metadata['loupmd']['version']}: MD run, status {metadata['status']}"]
    out += _block("Model and structure", [_model_line(metadata["model"]), _structure_line(metadata["structure"])])
    out += _block("Physics", _physics_lines(metadata))
    out += _block("Plan", _plan_lines(metadata))
    out += _block("Gate", [_gate_line(metadata["gate"])])
    setup = metadata["timing"]["setup_s"]
    bundle = metadata["bundle"] or "the bundle"
    out += _block("Setup", [f"{bundle}; {setup:.1f} s for export or cache, engine and the first force evaluation"
                            if setup is not None else "not started"])
    out += _block("Speed", [_speed_line(metadata)])
    out += _block("Licence", [_licence_line(metadata["model"])])
    if metadata["warnings"]:
        out += _block("Warnings", list(metadata["warnings"]))
    if metadata["output"]:
        out += _block("Output", [f"{metadata['output']['directory']}: thermo.*.csv every "
                                 f"{metadata['output']['thermo_every']} steps"
                                 + (f", trajectory.*.traj every {metadata['output']['trajectory_every']}"
                                    if metadata["output"]["trajectory_every"] else "")
                                 + ", restart.npz, simulation.json, metadata.json"])
    return "\n".join(out)

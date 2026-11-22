"""Step 1 (alternative): design with RFD4-Proteina on a Modal GPU.

Usage:
    python -m modal run run_design_rfd4.py --config inputs/configs_pipeline/pdl1_rfd4_search.yaml --dry-run
    python -m modal run run_design_rfd4.py --config <config> --check-config   # CPU only: Hydra composes the config
    python -m modal run run_design_rfd4.py --config inputs/configs_pipeline/pdl1_rfd4_search.yaml
    python -m modal run --detach run_design_rfd4.py --config inputs/configs_pipeline/pdl1_rfd4_search.yaml --spawn

The refolding oracle comes from `design.oracle` in the pipeline YAML: of3 (OpenFold3, primary), af3 (native AF3
weights, which you supply), af2 (fallback). Omit it for plain generation with no refolding.

Results are saved on the `inceptive-runs` Volume under <run_name>/design/inference_samples/.
Nothing here connects to the validation step yet: RFD4 does not write BindCraft2's
3_Ranked/!_Ranked.csv, so that adapter is a later step.
"""
import os
import subprocess

import yaml

from config_loader import load_config, require_keys
from modal_app import (AF2_MODEL_DIR, AF2_PARAMS_SRC, AF2_PARAMS_VOLUME_DIR, AF2_SRC_DIR,
                       LOCAL_TARGETS_DIR, OF3_MODEL_DIR, OF3_WEIGHTS_GLOB, RFD4_HF_REPO, RUNS_DIR, TARGETS_DIR,
                       WEIGHTS_DIR, af2_params_volume, app, rfd4_af2_image, rfd4_image, rfd4_of3_image,
                       rfd4_weights_volume, runs_volume)

COMMIT_EVERY_SECONDS = 300  # save progress to the Volume this often


def _prepare_af2_oracle():
    """Link the pieces RFD4's AF2 oracle expects: /app/alphafold (patched source) and AF2_MODEL_DIR/params."""
    os.makedirs("/app", exist_ok=True)
    if not os.path.exists("/app/alphafold"):
        os.symlink(AF2_SRC_DIR, "/app/alphafold")
    os.makedirs(AF2_MODEL_DIR, exist_ok=True)
    if not os.path.exists(f"{AF2_MODEL_DIR}/params"):
        os.symlink(AF2_PARAMS_SRC, f"{AF2_MODEL_DIR}/params")
    for needed in ("params_model_1_ptm.npz", "params_model_1_multimer_v3.npz"):
        if not os.path.exists(f"{AF2_MODEL_DIR}/params/{needed}"):
            raise FileNotFoundError(f"AF2 parameters missing: {AF2_MODEL_DIR}/params/{needed}")
    if not os.path.exists(f"{AF2_SRC_DIR}/alphafold/model/tri_flash.py"):
        raise FileNotFoundError(f"Patched AlphaFold source missing at {AF2_SRC_DIR}")


def _prepare_of3_oracle():
    """Point AF3_MODEL_DIR at the ported OpenFold3 weights and check their provenance stamp.

    The oracle family follows AF3_MODEL_DIR alone (RFD4 docs, refolding.md), so a run labelled `of3` is only
    OpenFold3 if this folder really holds the converted OF3 weights. Returns the model directory.
    """
    import glob
    import json
    (weights,) = glob.glob(OF3_WEIGHTS_GLOB)  # the HF snapshot folder; its hash is not fixed here
    if not os.path.exists(OF3_MODEL_DIR):
        os.symlink(weights, OF3_MODEL_DIR)
    with open(f"{OF3_MODEL_DIR}/of3_ported_weights.provenance.json") as f:
        prov = json.load(f)
    if prov.get("weight_family") != "openfold3":
        raise RuntimeError(f"{OF3_MODEL_DIR} is not an OpenFold3 weight folder: {prov.get('weight_family')!r}")
    ckpt = f"{OF3_MODEL_DIR}/{prov['converted_checkpoint']['filename']}"
    if os.path.getsize(ckpt) != prov["converted_checkpoint"]["bytes"]:
        raise RuntimeError(f"{ckpt} has the wrong size for its provenance file")
    os.environ["AF3_MODEL_DIR"] = OF3_MODEL_DIR
    return OF3_MODEL_DIR


AF3_NATIVE_MODEL_DIR = f"{WEIGHTS_DIR}/af3_weights"  # on the rfd4-weights Volume; filled in by hand (gated by Google)


def _prepare_af3_oracle():
    """Point AF3_MODEL_DIR at native AF3 weights, which the user supplies. Fails clearly if they are missing."""
    if not os.path.isdir(AF3_NATIVE_MODEL_DIR) or not os.listdir(AF3_NATIVE_MODEL_DIR):
        raise FileNotFoundError(
            f"Native AF3 weights not found at {AF3_NATIVE_MODEL_DIR} (Volume 'rfd4-weights', folder af3_weights/). "
            "AF3 parameters are distributed by Google on request and are not in the RFD4 Hugging Face repo. "
            "Upload them there (the folder must hold exactly one AF3 parameter set), or use `oracle: of3`."
        )
    if os.path.exists(f"{AF3_NATIVE_MODEL_DIR}/of3_ported_weights.provenance.json"):
        raise RuntimeError(f"{AF3_NATIVE_MODEL_DIR} holds OpenFold3 weights; use `oracle: of3` instead.")
    os.environ["AF3_MODEL_DIR"] = AF3_NATIVE_MODEL_DIR
    return AF3_NATIVE_MODEL_DIR


EXPERIMENT_DIR = "/tmp/rfd4_cfg"  # where a standalone RFD4 (Hydra) config file is written in the container


def _rfd4_command(spec_path, out_dir, num_replicates, overrides, experiment):
    """Build the rfd4-generate command.

    `experiment` is {"name": ..., "text": ...} for a standalone RFD4 config file (search, oracle, metrics
    tags, replicates, ...; see inputs/configs_rfd4/), or None to use only `overrides`.
    `inputs`, `out_dir` and `num_replicates` are command-line arguments, so they win over the file.
    """
    cmd = ["rfd4-generate"]
    if experiment:
        os.makedirs(EXPERIMENT_DIR, exist_ok=True)
        with open(f"{EXPERIMENT_DIR}/{experiment['name']}.yaml", "w", encoding="utf-8") as f:
            f.write(experiment["text"])
        cmd += ["--config-path", EXPERIMENT_DIR, "--config-name", experiment["name"]]
    cmd += [f"inputs={spec_path}", f"out_dir={out_dir}"]
    if num_replicates is not None:
        cmd.append(f"num_replicates={num_replicates}")
    return cmd + list(overrides)


def _run_rfd4(run_name, spec, num_replicates, overrides, experiment, oracle):
    """`oracle` is None, "af2", "of3" or "af3": which refolding oracle runtime to prepare."""
    run_dir = f"{RUNS_DIR}/{run_name}"
    out_dir = f"{run_dir}/design"
    os.makedirs(out_dir, exist_ok=True)

    spec_path = f"{run_dir}/rfd4_spec.yaml"
    with open(spec_path, "w") as f:
        yaml.safe_dump(spec, f, sort_keys=False)

    if oracle == "af2":
        _prepare_af2_oracle()

    # Download the weights the first time (skipped once they are on the Volume).
    from huggingface_hub import snapshot_download
    snapshot_download(RFD4_HF_REPO)

    # After the download: the OF3 weights are part of the same Hugging Face snapshot.
    if oracle == "of3":
        print("AF3_MODEL_DIR (OpenFold3):", _prepare_of3_oracle())
    elif oracle == "af3":
        print("AF3_MODEL_DIR (native AF3):", _prepare_af3_oracle())
    rfd4_weights_volume.commit()

    cmd = _rfd4_command(spec_path, out_dir, num_replicates, overrides, experiment)
    print("Running:", " ".join(cmd))
    proc = subprocess.Popen(cmd)
    while True:
        try:
            proc.wait(timeout=COMMIT_EVERY_SECONDS)
            break
        except subprocess.TimeoutExpired:
            runs_volume.commit()
    runs_volume.commit()

    if proc.returncode != 0:
        raise RuntimeError(f"rfd4-generate exited with code {proc.returncode}")
    return out_dir


# These functions run remotely, inside the container on a GPU.
# Their GPU and timeout are filled in later (see main) so they come from the config.
@app.function(
    image=rfd4_image,
    volumes={RUNS_DIR: runs_volume, WEIGHTS_DIR: rfd4_weights_volume},
)
def design(run_name: str, spec: dict, num_replicates, overrides: list, experiment=None):
    return _run_rfd4(run_name, spec, num_replicates, overrides, experiment, oracle=None)


# Same, plus the OpenFold3 refolding oracle: the primary oracle. Add `oracle: of3` to the design section.
@app.function(
    image=rfd4_of3_image,
    volumes={RUNS_DIR: runs_volume, WEIGHTS_DIR: rfd4_weights_volume},
)
def design_of3(run_name: str, spec: dict, num_replicates, overrides: list, experiment=None):
    return _run_rfd4(run_name, spec, num_replicates, overrides, experiment, oracle="of3")


# Native AF3 uses the same image and worker as OpenFold3; only the weights folder differs. The AF3 weights
# are distributed by Google on request and are NOT in the Hugging Face repo, so they must be placed on the
# rfd4-weights Volume at AF3_NATIVE_MODEL_DIR first. Add `oracle: af3` to the design section.
@app.function(
    image=rfd4_of3_image,
    volumes={RUNS_DIR: runs_volume, WEIGHTS_DIR: rfd4_weights_volume},
)
def design_af3(run_name: str, spec: dict, num_replicates, overrides: list, experiment=None):
    return _run_rfd4(run_name, spec, num_replicates, overrides, experiment, oracle="af3")


# Same, plus the AF2 refolding oracle (fallback; its scores are not on RFD4's AF3-tuned scale).
# Add `oracle: af2` to the design section to use this one.
@app.function(
    image=rfd4_af2_image,
    volumes={RUNS_DIR: runs_volume, WEIGHTS_DIR: rfd4_weights_volume, AF2_PARAMS_VOLUME_DIR: af2_params_volume},
)
def design_af2(run_name: str, spec: dict, num_replicates, overrides: list, experiment=None):
    return _run_rfd4(run_name, spec, num_replicates, overrides, experiment, oracle="af2")


# CPU-only check of the AF2 oracle environment: imports the worker's dependencies and the patched
# AlphaFold, and runs the shim. No GPU, so it is cheap. Run with:
#   python -m modal run run_design_rfd4.py::check_af2_env
@app.function(
    image=rfd4_af2_image,
    volumes={WEIGHTS_DIR: rfd4_weights_volume, AF2_PARAMS_VOLUME_DIR: af2_params_volume},
    timeout=900,
)
def check_af2_env():
    _prepare_af2_oracle()
    code = (
        # No `import tensorflow`: TF 2.16 needs NumPy<2 but the oracle image has NumPy 2.x, so its worker
        # must not import TF. If the imports below pull it in, the check shows it.
        "import jax, jaxlib, numpy, haiku, absl, Bio;"
        "import sys;"
        "print('jax', jax.__version__, 'jaxlib', jaxlib.__version__, 'numpy', numpy.__version__);"
        "import alphafold, alphafold.model.tri_flash as t, alphafold.model.model as m;"
        "print('alphafold from', alphafold.__file__);"
        "from alphafold.model import config; c=config.model_config('model_1_ptm');"
        "print('use_pallas default', c.model.global_config.use_pallas);"
        "print('tensorflow imported by alphafold:', 'tensorflow' in sys.modules)"
    )
    env = {**os.environ, "PYTHONPATH": "/app/alphafold", "JAX_PLATFORMS": "cpu", "CUDA_VISIBLE_DEVICES": ""}
    r = subprocess.run(["/opt/conda/bin/python", "-c", code], env=env, capture_output=True, text=True)
    print("python import check rc:", r.returncode)
    print(r.stdout[-2000:])
    print(r.stderr[-3000:])
    # The shim must turn an `apptainer exec ...` line into a plain python call.
    r2 = subprocess.run(
        ["apptainer", "exec", "--nv", "--env", "FOO=bar", "--env", "LD_LIBRARY_PATH=/x", "--bind", "/a:/a",
         "modal-shim", "/opt/conda/bin/python", "-c", "import os,sys;print('shim ok', os.environ['FOO'], sys.version.split()[0])"],
        capture_output=True, text=True)
    print("shim rc:", r2.returncode, r2.stdout.strip(), r2.stderr.strip()[-300:])
    # The worker script must at least start and print its flags.
    import rfproteina, pathlib
    worker = pathlib.Path(rfproteina.__file__).parent / "af2" / "run_alphafold2_batch.py"
    print("worker exists:", worker.exists(), worker)
    r3 = subprocess.run(["/opt/conda/bin/python", str(worker), "--help"], env=env, capture_output=True, text=True)
    print("worker --help rc:", r3.returncode)
    print((r3.stdout + r3.stderr)[-1500:])
    return r.returncode == 0 and r2.returncode == 0


# CPU-only check of the OpenFold3 oracle image (phase 1): the unpacked AF3 venv imports, its chemical-components
# data loads, the weights folder passes its provenance check, the shim turns `apptainer run ...` into a plain
# python call, and the worker script starts. No GPU, so it is cheap. Run with:
#   python -m modal run run_design_rfd4.py::check_of3_env
@app.function(
    image=rfd4_of3_image,
    volumes={WEIGHTS_DIR: rfd4_weights_volume},
    timeout=1800,
    memory=16384,
)
def check_of3_env():
    ok = True
    model_dir = _prepare_of3_oracle()
    print("AF3_MODEL_DIR ok:", model_dir, os.listdir(model_dir))
    env = {**os.environ, "JAX_PLATFORMS": "cpu", "CUDA_VISIBLE_DEVICES": ""}
    py = "/alphafold3_venv/bin/python"
    code = (
        "import sys, jax, numpy, haiku;"
        "print('python', sys.version.split()[0], 'jax', jax.__version__, 'numpy', numpy.__version__);"
        "import alphafold3; print('alphafold3 from', alphafold3.__file__);"
        "from alphafold3.constants import chemical_components as cc;"
        "ccd = cc.Ccd(); print('CCD loaded, has ALA:', 'ALA' in ccd, ' has ZN:', 'ZN' in ccd);"
        "from alphafold3.data import featurisation; print('featurisation imported')"
    )
    r = subprocess.run([py, "-c", code], env=env, capture_output=True, text=True)
    print("venv import check rc:", r.returncode)
    print(r.stdout[-2000:])
    print(r.stderr[-3000:])
    ok &= r.returncode == 0
    # The shim must turn `apptainer run ... <image> python ...` into a plain call that finds the venv's python.
    r2 = subprocess.run(
        ["apptainer", "run", "--nv", "--env", "FOO=bar", "--bind", "/a:/a", "modal-shim", "python", "-c",
         "import os,sys;print('shim ok', os.environ['FOO'], sys.executable)"],
        capture_output=True, text=True)
    print("shim rc:", r2.returncode, r2.stdout.strip(), r2.stderr.strip()[-300:])
    ok &= r2.returncode == 0 and "/alphafold3_venv" in r2.stdout
    # The worker script must at least start and print its flags (it imports jax and alphafold3).
    import pathlib
    import rfproteina
    worker = pathlib.Path(rfproteina.__file__).parent / "af3" / "run_alphafold_batch.py"
    print("worker exists:", worker.exists(), worker)
    r3 = subprocess.run([py, str(worker), "--help"], env=env, capture_output=True, text=True)
    print("worker --help rc:", r3.returncode)
    print((r3.stdout + r3.stderr)[-1200:])
    # absl exits with code 1 after printing --help, so judge by the flag list it printed.
    ok &= "--manifest" in (r3.stdout + r3.stderr)
    print("PHASE 1 CHECK:", "PASS" if ok else "FAIL")
    return ok


# Phase 4: known-positive / negative controls for the OpenFold3 oracle, using the same oracle code path and
# template recipe as the design runs. PD-L1 (target, chain A, templated) is paired with:
#   positive  its natural partner PD-1 from the crystal structure 4ZQK (should score as a real complex)
#   negative  ubiquitin (1UBQ), which has no reason to bind PD-L1 (should score low)
# plus the positive again WITHOUT the template, to show how much the template matters.
# This is NOT a de novo binder: a natural complex tells us the plumbing and scale are sane, not how the oracle
# treats designed binders. GPU (A100), a few minutes. Run with:
#   python -m modal run --detach run_design_rfd4.py::control_of3
@app.function(
    image=rfd4_of3_image,
    gpu="A100",
    volumes={RUNS_DIR: runs_volume, WEIGHTS_DIR: rfd4_weights_volume},
    timeout=3600,
)
def control_of3():
    import json
    import urllib.request
    from pathlib import Path

    import biotite.structure as struc
    import biotite.structure.io.pdbx as pdbx
    import numpy as np
    from atomworks.io import parse
    from atomworks.io.config import ParseConfig
    from atomworks.io.utils.atom_array_plus import as_atom_array_plus
    from atomworks.ml.conditions import C_CRD
    from biotite.sequence import ProteinSequence

    from rfproteina.metrics.oracles.af3_oracle import AF3Oracle
    from rfproteina.metrics.oracles.oracle_metric import OracleJobInput

    print("AF3_MODEL_DIR:", _prepare_of3_oracle())
    work = Path("/tmp/control")
    work.mkdir(parents=True, exist_ok=True)

    def fetch(pdb):
        path = work / f"{pdb}.cif"
        urllib.request.urlretrieve(f"https://files.rcsb.org/download/{pdb}.cif", path)
        return path

    def load(path):
        arr = pdbx.get_structure(pdbx.CIFFile.read(str(path)), model=1)
        return arr[struc.filter_amino_acids(arr) & ~arr.hetero]

    def seq_of(chain):
        _, names = struc.get_residues(chain)
        out = []
        for n in names:
            try:
                out.append(ProteinSequence.convert_letter_3to1(n))
            except KeyError:
                out.append("X")
        return "".join(out)

    def pick(arr, motif):
        for cid in np.unique(arr.chain_id):
            chain = arr[arr.chain_id == cid]
            if motif in seq_of(chain):
                return chain
        raise RuntimeError(f"no chain containing {motif}")

    complex_arr = load(fetch("4ZQK"))
    pdl1 = pick(complex_arr, "YVVEYGSNMTIECKF")
    pd1 = pick(complex_arr, "NWYRMSPSNQTDKL")
    ubq = load(fetch("1UBQ"))
    ubq = ubq[ubq.chain_id == np.unique(ubq.chain_id)[0]]
    pdl1 = pdl1[(pdl1.res_id >= 17) & (pdl1.res_id <= 131)]  # the same 115-residue domain the designs target
    print(f"PD-L1 {len(set(pdl1.res_id))} res, PD-1 {len(set(pd1.res_id))} res, ubiquitin {len(set(ubq.res_id))} res")
    # Sanity: the crystal pair really is in contact (CA pairs within 8 A).
    ca1, ca2 = pdl1[pdl1.atom_name == "CA"].coord, pd1[pd1.atom_name == "CA"].coord
    contacts = int((np.linalg.norm(ca1[:, None] - ca2[None], axis=-1) < 8.0).sum())
    print("PD-L1 / PD-1 CA pairs within 8 A in the crystal:", contacts)

    def combine(target, binder, name):
        t, b = target.copy(), binder.copy()
        t.chain_id[:] = "A"
        b.chain_id[:] = "B"
        cif = pdbx.CIFFile()
        pdbx.set_structure(cif, t + b, data_block=name)
        path = work / f"{name}.cif"
        cif.write(str(path))
        aa = as_atom_array_plus(parse(path, config=ParseConfig.from_preset("minimal"))["asym_unit"][0])
        mask = aa.chain_id == "A"  # the target is the templated part, as in the design runs
        C_CRD.set_annotation(aa, np.where(mask[:, None], C_CRD.ground_truth_value(aa), C_CRD.default_annotation(aa)))
        iid = "chain_iid" if "chain_iid" in aa.get_annotation_categories() else "chain_id"
        return aa, str(np.unique(aa.get_annotation(iid)[aa.chain_id == "B"])[0]), t, b

    cases = {}
    for name, binder in (("positive_pd1", pd1), ("negative_ubiquitin", ubq)):
        cases[name] = combine(pdl1, binder, name)

    results = {}
    runs = [
        ("positive_pd1", "templated", "sa_mask('C_CRD') & is_protein"),
        ("negative_ubiquitin", "templated", "sa_mask('C_CRD') & is_protein"),
        ("positive_pd1", "no_template", None),
    ]
    for case, variant, query in runs:
        aa, coi, t, b = cases[case]
        oracle = AF3Oracle(oracle_name="of3_ctrl", template_query=query, seed=1)
        out_dir = work / f"{case}_{variant}"
        out_dir.mkdir(exist_ok=True)
        oracle.setup()
        try:
            conf = oracle.fold_one(OracleJobInput(aa, f"{case}_{variant}", out_dir, chain_of_interest=coi))
        finally:
            oracle.teardown()
        keep = ("overall_plddt", "overall_ptm", "overall_iptm", "ranking_score", "plddt_coi", "ptm_coi",
                "iptm_coi", "min_ipae_coi", "ipae_coi")
        row = {k: conf.get(k) for k in keep}
        # Binder pose accuracy against the crystal (positive only): align on the target, measure the binder.
        if case == "positive_pd1":
            try:
                ref = as_atom_array_plus(parse(oracle.refolded_cif_path(out_dir, f"{case}_{variant}"),
                                               config=ParseConfig.from_preset("minimal"))["asym_unit"][0])
                def ca(x, c):
                    return x[(x.chain_id == c) & (x.atom_name == "CA")]

                _, transform = struc.superimpose(ca(aa, "A"), ca(ref, "A"))  # fit the refold's target onto the crystal's
                moved_binder = transform.apply(ca(ref, "B"))
                row["binder_CA_rmsd_vs_crystal_after_target_fit"] = float(struc.rmsd(ca(aa, "B"), moved_binder))
            except Exception as exc:  # the scores above are the point; this is a bonus
                row["binder_CA_rmsd_vs_crystal_after_target_fit"] = f"failed: {exc}"
        results[f"{case}/{variant}"] = row
        print(f"=== {case} / {variant}: {json.dumps(row)}")

    out = Path(RUNS_DIR) / "oracle_control"
    out.mkdir(parents=True, exist_ok=True)
    (out / "of3_control.json").write_text(json.dumps(results, indent=2))
    runs_volume.commit()
    print("wrote", out / "of3_control.json")
    return results


# CPU-only: ask Hydra to compose the full config for a run config WITHOUT running the model
# (rfd4-generate --cfg job). Catches wrong config names or override syntax before any GPU time.
@app.function(image=rfd4_af2_image, volumes={WEIGHTS_DIR: rfd4_weights_volume}, timeout=900)
def compose_config(spec: dict, num_replicates, overrides: list, experiment=None):
    spec_path = "/tmp/rfd4_spec.yaml"
    with open(spec_path, "w") as f:
        yaml.safe_dump(spec, f, sort_keys=False)
    base_cmd = _rfd4_command(spec_path, "/tmp/rfd4_check", num_replicates, overrides, experiment) + ["--cfg", "job"]
    # --resolve evaluates EVERY interpolation, including ones a real run never reads (such as
    # ${oc.env:DATA_PATH} for benchmark data), so give it a dummy DATA_PATH. If something else is
    # unresolvable, fall back to the unresolved view, which still proves the config composes.
    cmd = base_cmd + ["--resolve"]
    print("Running:", " ".join(cmd))
    r = subprocess.run(cmd, capture_output=True, text=True, env={**os.environ, "DATA_PATH": "/tmp/rfd4_data"})
    if r.returncode != 0 and "Environment variable" in r.stderr:
        print("--resolve hit an unset environment variable; retrying without it (values may show ${...}).")
        r = subprocess.run(base_cmd, capture_output=True, text=True)
    print("rc:", r.returncode)
    noise = ("MIRROR", "(1)", "(2)", "(3)", "Open Babel", "libcuda", "libcue_ops")
    keep = [l for l in r.stderr.splitlines() if not any(x in l for x in noise)]
    conf = None
    if r.returncode == 0:
        try:
            conf = yaml.safe_load(r.stdout)
        except yaml.YAMLError as exc:
            print("could not parse the composed config:", exc)
    if isinstance(conf, dict):
        # Show the settings we care about, so a wrong oracle or schedule is visible, not just "composes".
        for key in ("num_replicates", "batch_size", "global_prefix", "metrics_tags", "recycle_strategy"):
            print(f"  {key}: {conf.get(key)}")
        gen = conf.get("generation") or {}
        print(f"  generation.args.nsteps: {(gen.get('args') or {}).get('nsteps')}")
        # The tags must reach the dataset transform, or RFD4 silently skips refolding metrics.
        transform = ((gen.get("dataset") or {}).get("transform") or {})
        print(f"  generation.dataset.transform.metrics_tags: {transform.get('metrics_tags')}")
        print(f"  generation.dataset.num_replicates: {(gen.get('dataset') or {}).get('num_replicates')}")
        print(f"  inputs: {conf.get('inputs')}   out_dir: {conf.get('out_dir')}")
        metrics = conf.get("metrics") or {}
        print(f"  metrics groups present: {sorted(metrics.keys()) if isinstance(metrics, dict) else type(metrics).__name__}")
        names = set()

        def walk(node):
            if isinstance(node, dict):
                for k, v in node.items():
                    if k == "oracle_name":
                        names.add(str(v))
                    walk(v)
            elif isinstance(node, list):
                for v in node:
                    walk(v)
        walk(conf)
        print(f"  oracle_name values in the composed config: {sorted(names)}")
        # A target that is not templated folds badly in AF2 (chain pLDDT ~0.35), so show what is templated.
        oracles = (metrics.get("refolding_oracles") or {}) if isinstance(metrics, dict) else {}
        for key, node in oracles.items():
            if isinstance(node, dict) and "template_query" in node:
                print(f"  oracle {key}: template_query = {node['template_query']!r}")
        for key, node in oracles.items():
            if isinstance(node, dict) and "required_tags_any" in node:
                print(f"  oracle {key}: runs on tags {node['required_tags_any']}")
        # The ppi pass criterion reads this metric; an empty alignment mask silently drops it (and forces ppi.pass to 0).
        rm = (metrics.get("refolding_metrics") or {}) if isinstance(metrics, dict) else {}
        node = rm.get("refolded_target_backbone_aligned_binder_rmsd")
        if isinstance(node, dict):
            print(f"  refolded_target_backbone_aligned_binder_rmsd: align_mask = {node.get('align_mask')!r}")
        print("  search:")
        print("    " + yaml.safe_dump(conf.get("search"), sort_keys=False).replace("\n", "\n    "))
    elif r.returncode == 0:
        print(r.stdout[-1500:])
    print("stderr tail:")
    print("\n".join(keep[-25:]))
    return r.returncode


# CPU-only: build every example in the condition spec through RFD4's own loader (load, contig, conditions, finalize,
# validation) and write the annotated CIFs, WITHOUT running the model. Catches a bad chain id, an empty selection, an
# unknown condition name or a rejected contig before any GPU time, and shows what each condition ended up on.
@app.function(image=rfd4_image, timeout=900)
def check_spec(spec: dict):
    from collections import Counter
    from pathlib import Path

    import numpy as np
    from atomworks.io import parse
    from atomworks.io.config import ParseConfig
    from rfproteina.inference_utils.condition_spec import resolve_condition_spec_inputs

    work = Path("/tmp/spec_check")
    work.mkdir(parents=True, exist_ok=True)
    spec_path = work / "spec.yaml"
    with open(spec_path, "w") as f:
        yaml.safe_dump(spec, f, sort_keys=False)
    paths = resolve_condition_spec_inputs(spec_path, work / "cifs", validate=True)
    for p in paths:
        print(f"\n=== built {p.name} ({p.stat().st_size} bytes)")
        aa = parse(str(p), config=ParseConfig.from_preset("minimal"))["asym_unit"][0]
        cats = set(aa.get_annotation_categories())
        iid = "chain_iid" if "chain_iid" in cats else "chain_id"
        chains = np.asarray(aa.get_annotation(iid)).astype(str)
        print("atoms per chain:", dict(Counter(chains.tolist())))
        for c in sorted(set(chains)):
            m = chains == c
            seq = []
            seen = set()
            for rid, rn in zip(aa.res_id[m].tolist(), aa.res_name[m].tolist()):
                if rid not in seen:
                    seen.add(rid)
                    seq.append(rn)
            print(f"  chain {c}: {len(seq)} residues: {' '.join(seq[:12])}{' ...' if len(seq) > 12 else ''}")
        # The written CIF carries one `_atom_site.condition_*` column per condition: count the values per chain.
        lines = p.read_text().splitlines()
        cols = [l.strip()[len("_atom_site."):] for l in lines if l.startswith("_atom_site.")]
        start = next(i for i, l in enumerate(lines) if l.startswith("_atom_site.")) + len(cols)
        rows = []
        for l in lines[start:]:
            if l.startswith(("loop_", "#")):
                break
            if l.strip():
                rows.append(l.split())
        chain_col = cols.index("auth_asym_id") if "auth_asym_id" in cols else cols.index("label_asym_id")
        for name in [c for c in cols if c.startswith("condition_")]:
            k = cols.index(name)
            per_chain = {}
            for r in rows:
                if len(r) > k:
                    per_chain.setdefault(r[chain_col], Counter())[r[k]] += 1
            print(f"  {name}: " + "; ".join(f"{c}={dict(v)}" for c, v in sorted(per_chain.items())))
    return [str(p) for p in paths]


def build_spec(design_cfg):
    """Load the RFD4 condition spec and point every `input:` at the copy inside the container.

    Like BindCraft2 targets, inputs are found by FILE NAME in inputs/targets/.
    """
    with open(design_cfg["spec"]) as f:
        spec = yaml.safe_load(f)
    for name, entry in spec.items():
        if not isinstance(entry, dict) or "input" not in entry:
            continue
        file_name = os.path.basename(str(entry["input"]).replace("\\", "/"))
        if not os.path.exists(os.path.join(LOCAL_TARGETS_DIR, file_name)):
            raise FileNotFoundError(f"Input structure '{file_name}' (spec entry '{name}') "
                                    f"is not in {LOCAL_TARGETS_DIR}/. Put the file there.")
        entry["input"] = f"{TARGETS_DIR}/{file_name}"
        print(f"Input structure: {file_name} -> {entry['input']}")
    return spec


# This runs on your own computer and launches the remote function.
@app.local_entrypoint()
def main(config: str, dry_run: bool = False, spawn: bool = False, check_config: bool = False,
         check_spec_only: bool = False):
    cfg = load_config(config)
    require_keys(cfg, ["run_name", "design"], where=config)
    run_name, design_cfg = cfg["run_name"], cfg["design"]
    require_keys(design_cfg, ["gpu", "timeout_hours", "spec"], where="design section")
    spec = build_spec(design_cfg)

    # Optional standalone RFD4 (Hydra) config file with the search, oracle, metrics tags, replicates, ...
    # It is shipped to the container as text, so editing it never needs an image rebuild.
    experiment = None
    if "experiment" in design_cfg:
        exp_path = design_cfg["experiment"]
        if not os.path.exists(exp_path):
            raise FileNotFoundError(f"design.experiment file not found: {exp_path}")
        with open(exp_path, encoding="utf-8") as f:
            experiment = {"name": os.path.splitext(os.path.basename(exp_path))[0], "text": f.read()}

    # num_replicates: the pipeline value wins over the experiment file when both are given.
    # Without an experiment file there is nothing else to supply it, so default to 1.
    num_replicates = design_cfg.get("num_replicates")
    if num_replicates is None and experiment is None:
        num_replicates = 1
    if num_replicates is not None:
        num_replicates = int(num_replicates)
    overrides = [str(o) for o in design_cfg.get("overrides", [])]  # extra rfd4-generate arguments, applied last

    # The pipeline picks the refolding oracle, so the RFD4 config group is set from it (a command-line group
    # override beats the default in the experiment file). That way the runtime image and the config cannot disagree.
    oracle = design_cfg.get("oracle")  # None, "of3" (primary), "af3" (native weights needed) or "af2" (fallback)
    if oracle not in (None, "of3", "af3", "af2"):
        raise ValueError(f"design.oracle must be left out or one of of3, af3, af2; got {oracle!r}")
    if oracle:
        overrides = [f"metrics/refolding_oracles={oracle}"] + overrides

    print(f"Run name : {run_name}")
    print(f"Oracle   : {oracle or 'none'}")
    print(f"GPU      : {design_cfg['gpu']}   timeout: {design_cfg['timeout_hours']} h")

    options = {"gpu": design_cfg["gpu"], "timeout": int(design_cfg["timeout_hours"] * 3600)}
    if "cpu" in design_cfg:
        options["cpu"] = design_cfg["cpu"]
    if "memory_gb" in design_cfg:
        options["memory"] = int(design_cfg["memory_gb"] * 1024)  # Modal wants MiB
    print(f"Modal options: {options}")
    print(f"RFD4 config file: {design_cfg.get('experiment', 'none (overrides only)')}")
    print(f"num_replicates (pipeline): {num_replicates}   extra overrides: {overrides}")
    print(f"RFD4 spec:\n{yaml.safe_dump(spec, sort_keys=False)}")
    if check_spec_only:
        # CPU only: build the condition spec through RFD4's loader, no model, no GPU.
        check_spec.remote(spec)
        print("Spec built cleanly.")
        return
    if check_config:
        # CPU only: have Hydra compose the full config without running the model.
        rc = compose_config.remote(spec, num_replicates, overrides, experiment)
        print("Config composes cleanly." if rc == 0 else "Config did NOT compose; see the error above.")
        return
    if dry_run:
        print("Dry run, nothing launched.")
        return

    remote_design = {None: design, "of3": design_of3, "af3": design_af3, "af2": design_af2}[oracle].with_options(**options)
    if spawn:
        call = remote_design.spawn(run_name, spec, num_replicates, overrides, experiment)
        print(f"Spawned RFD4 run '{run_name}' (function call {call.object_id}). It keeps running without this terminal.")
        print(f"Check with: python -m modal volume ls inceptive-runs {run_name}/design")
        return
    out = remote_design.remote(run_name, spec, num_replicates, overrides, experiment)
    print(f"Done. Results on Volume 'inceptive-runs' at {out}")
    print(f"Download with: python -m modal volume get inceptive-runs {run_name} ./results")

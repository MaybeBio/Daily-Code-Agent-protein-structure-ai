"""
rnapro_run_selector.py - Kaggle script (GPU): rnapro_run.py unchanged except its defaults: the selector's
templates (selector_templates.csv from rnapro-inputs), tag selector_50. A separate notebook so the john run's
outputs stay as they are.

rnapro_run.py - run NVIDIA's RNAPro on a subset of chains with given templates.

Setup (every run, internet on):
    code      git clone NVIDIA-Digital-Bio/RNAPro at a fixed commit, pip install -e . --no-deps
              plus the few packages Kaggle's image lacks (no torch reinstall: Kaggle's torch is used)
    weights   nvidia/RNAPro-Private-Best-500M from Hugging Face (4.9 GB; the paper's main model)
    RNet2     RibonanzaNet2 from Kaggle Models (shujun717/ribonanzanet2, attached as a model source)
    CCD       components.cif from wwPDB; the RDKit cache is built only for the residues needed (A, C, G, U)
Kaggle's GPUs (T4/P100) are older than RNAPro's supported Ampere+, so: fp32, plain PyTorch
triangle kernels (no cuEquivariance), plain LayerNorm.

Inference follows the paper and rnapro_inference_example.sh: 1 seed, 1 sample, 200 diffusion steps,
10 recycles, and 5 predictions per chain using templates top1, top1-2, ..., top1-5
(RNAPro's own template_idx scheme).

Env: RR_SUBSET (smoke | 50), RR_TEMPLATES (template csv name), RR_TAG (label for outputs), RR_MAX_LEN
Outputs: predictions_<tag>.csv  (ID, resname, resid, x_1..z_5: C1' of the 5 predictions)
         cif_<tag>/<target>_<k>.cif, rnapro_<tag>.json (timing, memory, failures)
"""
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

INPUT = Path("/kaggle/input")
WORK = Path("/kaggle/working")
TMP = Path("/kaggle/temp")
SUBSET = os.environ.get("RR_SUBSET", "50")
TEMPLATES = os.environ.get("RR_TEMPLATES", "selector_templates_plain.csv")
TAG = os.environ.get("RR_TAG", f"selector_plain_{SUBSET}")
MAX_LEN = int(os.environ.get("RR_MAX_LEN", 512))
COMMIT = "83a0b90ae3ae1581ebedfe99301ea4e5965488ca"
HF_URL = "https://huggingface.co/nvidia/RNAPro-Private-Best-500M/resolve/main/rnapro-private-best-500m.ckpt"
CODE = TMP / "RNAPro"
EXTRA = ["ml_collections==1.1.0", "dm-tree==0.1.9", "biotite==1.4.0", "gemmi==0.6.7", "pdbeccdutils==0.8.6",
         "rdkit==2023.9.6", "modelcif==1.4", "optree==0.17.0", "icecream==2.1.7", "posix_ipc==1.3.0"]


def sh(cmd, **kw):
    print("$", cmd, flush=True)
    return subprocess.run(cmd, shell=True, check=True, **kw)


def find(name):
    hits = sorted(INPUT.rglob(name))
    if not hits:
        sys.exit(f"{name} not found under {INPUT}")
    return hits[0]


def setup(info):
    t0 = time.time()
    TMP.mkdir(parents=True, exist_ok=True)
    if not CODE.exists():
        sh(f"git clone -q https://github.com/NVIDIA-Digital-Bio/RNAPro {CODE} && cd {CODE} && git checkout -q {COMMIT}")
    installed = {}
    for req in EXTRA:                                   # pinned version first; else the newest one for this Python
        name = req.split("==")[0]
        r = subprocess.run(f"{sys.executable} -m pip install -q {req}", shell=True)
        if r.returncode != 0:
            r = subprocess.run(f"{sys.executable} -m pip install -q {name}", shell=True)
        v = subprocess.run(f"{sys.executable} -m pip show {name} | grep -i ^version", shell=True,
                           capture_output=True, text=True).stdout.strip().split(":")[-1].strip()
        installed[name] = v or "FAILED"
    info["packages"] = installed
    print(installed, flush=True)
    sh(f"{sys.executable} -m pip install -q --no-deps -e {CODE}")
    v = subprocess.run([sys.executable, "-c", "import torch,sys;print(torch.__version__, sys.version.split()[0])"],
                       capture_output=True, text=True).stdout.split()
    info["torch"], info["python"] = (v + ["?", "?"])[:2]
    info["gpu"] = subprocess.run("nvidia-smi --query-gpu=name,memory.total --format=csv,noheader", shell=True,
                                 capture_output=True, text=True).stdout.strip()

    ckpt = TMP / "rnapro-private-best-500m.ckpt"
    if not ckpt.exists():
        sh(f"wget -q -O {ckpt} {HF_URL}")
    info["checkpoint_gb"] = round(ckpt.stat().st_size / 1e9, 2)

    rnet = TMP / "ribonanzanet2"
    if not rnet.exists():
        src = find("pairwise.yaml").parent
        shutil.copytree(src, rnet)
    info["ribonanzanet2_files"] = sorted(p.name for p in rnet.iterdir())

    ccd = CODE / "release_data" / "ccd_cache"
    ccd.mkdir(parents=True, exist_ok=True)
    if not (ccd / "components.cif.rdkit_mol.pkl").exists():
        sh(f"cd {ccd} && wget -q https://files.wwpdb.org/pub/pdb/data/monomers/components.cif.gz && gunzip -f components.cif.gz")
        sys.path.insert(0, str(CODE / "preprocess"))
        import pickle
        from gen_ccd_cache import _get_component_rdkit_mol_processing
        mols = {}
        for code in ["A", "C", "G", "U", "N", "DA", "DC", "DG", "DT"]:
            m = _get_component_rdkit_mol_processing((code, ccd / "components.cif"))
            if m is not None:
                mols[code] = m
        with open(ccd / "components.cif.rdkit_mol.pkl", "wb") as fh:
            pickle.dump(mols, fh)
        (ccd / "clusters-by-entity-40.txt").touch()
        info["ccd_codes_cached"] = sorted(mols)
    info["setup_minutes"] = round((time.time() - t0) / 60, 1)
    return ckpt, rnet


def main():
    WORK.mkdir(parents=True, exist_ok=True)
    info = {"subset": SUBSET, "templates": TEMPLATES, "tag": TAG}
    ckpt, rnet = setup(info)
    print(json.dumps(info, indent=1), flush=True)

    import threading
    import pandas as pd
    seqs = pd.read_csv(find(f"subset_{SUBSET}.csv"))[["target_id", "sequence"]]
    base = TMP / f"run_{TAG}"
    base.mkdir(parents=True, exist_ok=True)
    msa_dir = find(f"{seqs.target_id.iloc[0]}.MSA.fasta").parent
    # RNAPro's converter writes into release_data/kaggle under the cwd
    sh(f"cd {base} && {sys.executable} {CODE}/preprocess/convert_templates_to_pt_files.py "
       f"--input_csv {find(TEMPLATES)} --output_name templates.pt")
    tpl = base / "release_data" / "kaggle" / "templates.pt"

    # ---- spread the chains over the GPUs (cost ~ length^2, longest first), then batches of CHUNK per GPU
    n_gpu = max(1, len([l for l in info["gpu"].splitlines() if l.strip()]))
    load, per_gpu = [0.0] * n_gpu, [[] for _ in range(n_gpu)]
    for _, r in seqs.assign(L=seqs.sequence.str.len()).sort_values("L", ascending=False).iterrows():
        g = load.index(min(load))
        per_gpu[g].append(r)
        load[g] += r.L ** 2
    CHUNK = int(os.environ.get("RR_CHUNK", 10))
    info["gpus_used"] = n_gpu

    def cmd_for(run_dir):
        return [sys.executable, str(CODE / "runner" / "inference.py"),
                "--model_name", "rnapro_base", "--seeds", "42", "--dump_dir", "out",      # relative: the runner prefixes "./"
                "--load_checkpoint_path", str(ckpt), "--dtype", "fp32",
                "--use_msa", "true", "--rna_msa_dir", str(msa_dir),
                "--use_template", "ca_precomputed", "--model.use_template", "ca_precomputed",
                "--template_data", str(tpl), "--template_idx", "0",
                "--model.use_RibonanzaNet2", "true", "--model.ribonanza_net_path", str(rnet),
                "--model.template_embedder.n_blocks", "2",
                "--model.N_cycle", "10", "--sample_diffusion.N_sample", "1", "--sample_diffusion.N_step", "200",
                "--load_strict", "true", "--num_workers", "0",
                "--triangle_attention", "torch", "--triangle_multiplicative", "torch",
                "--sequences_csv", str(run_dir / "sequences.csv"), "--max_len", str(MAX_LEN),
                "--logger", "print", "--n_templates_inf", "5"]

    cif_out = WORK / f"cif_{TAG}"
    cif_out.mkdir(exist_ok=True)
    batches, lock = [], threading.Lock()

    def save():
        parts = [pd.read_csv(b["dir"] / "submission.csv") for b in batches if (b["dir"] / "submission.csv").exists()]
        if parts:
            pd.concat(parts).to_csv(WORK / f"predictions_{TAG}.csv", index=False)
        errs = sorted({p.stem for b in batches for p in (b["dir"] / "out" / "ERR").glob("*.txt")
                       if (b["dir"] / "out" / "ERR").exists() and p.stem != "error"} |
                      {e for b in batches for e in b.get("missing", [])})
        info["batches"] = [{k: v for k, v in b.items() if k != "dir"} for b in batches]
        info["chains_with_errors"] = errs
        info["cif_files"] = len(list(cif_out.glob("*.cif")))
        info["elapsed_minutes"] = round((time.time() - t0) / 60, 1)
        (WORK / f"rnapro_{TAG}.json").write_text(json.dumps(info, indent=2, default=str))

    def worker(g):
        rows = per_gpu[g]
        rows = sorted(rows, key=lambda r: r.L)                    # short first: early batches finish fast
        for k in range(0, len(rows), CHUNK):
            part = pd.DataFrame(rows[k:k + CHUNK])[["target_id", "sequence"]]
            run_dir = base / f"gpu{g}_batch{k // CHUNK}"
            run_dir.mkdir(parents=True, exist_ok=True)
            part.to_csv(run_dir / "sequences.csv", index=False)
            env = dict(os.environ, LAYERNORM_TYPE="torch", PYTHONPATH=str(CODE), CUDA_VISIBLE_DEVICES=str(g),
                       RNAPRO_DATA_ROOT_DIR=str(CODE / "release_data" / "ccd_cache"))
            tb = time.time()
            proc = subprocess.run(cmd_for(run_dir), cwd=run_dir, env=env, capture_output=True, text=True)
            (WORK / f"inference_{TAG}_gpu{g}_batch{k // CHUNK}.log").write_text(
                proc.stdout[-100000:] + "\n---- stderr ----\n" + proc.stderr[-50000:])
            for p in (run_dir / "out").rglob("*_new.cif"):
                shutil.copy(p, cif_out / p.name)
            done = {p.name.split("_sample_")[0] for p in (run_dir / "out").rglob("*_new.cif")}
            with lock:
                batches.append({"dir": run_dir, "gpu": g, "chains": part.target_id.tolist(),
                                "lengths": part.sequence.str.len().tolist(), "returncode": proc.returncode,
                                "minutes": round((time.time() - tb) / 60, 1),
                                "missing": [c for c in part.target_id if c not in done]})
                save()
            print(f"gpu {g} batch {k // CHUNK}: {len(part)} chains, max length {part.sequence.str.len().max()}, "
                  f"{(time.time() - tb) / 60:.1f} min, return code {proc.returncode}", flush=True)

    t0 = time.time()
    mem_log = open(WORK / f"gpu_memory_{TAG}.csv", "w")
    watcher = subprocess.Popen("nvidia-smi --query-gpu=index,memory.used --format=csv,noheader -l 5",
                               shell=True, stdout=mem_log)
    threads = [threading.Thread(target=worker, args=(g,)) for g in range(n_gpu)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    watcher.terminate()
    mem_log.close()
    used = [int(l.split(",")[1].split()[0]) for l in (WORK / f"gpu_memory_{TAG}.csv").read_text().splitlines() if "," in l]
    info["peak_gpu_memory_mib"] = max(used) if used else None
    info["chains"] = int(len(seqs))
    info["inference_minutes"] = round((time.time() - t0) / 60, 1)
    save()
    print(json.dumps({k: v for k, v in info.items() if k != "batches"}, indent=1, default=str), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Helpers for part 2 of the practical: running TITO on proteins.

TITO / PLaTITO models are coarse grained: each residue is represented by its
C-alpha atom only. A model maps the current C-alpha coordinates ``x_t``
(in nm) plus conditions (amino-acid sequence, temperature T, lag time Δt) to a
sample ``x_{t+Δt} ~ p(x_{t+Δt} | x_t, S, T, Δt)``. Repeating this gives a
trajectory with time step Δt.

Everything here works offline: the TITO-3M checkpoint and the starting
structures are shipped in ``data/``.
"""

from __future__ import annotations

import base64
import io
import json
import logging
import time
import urllib.request
import warnings
from pathlib import Path

import matplotlib.pyplot as plt
import mdtraj as md
import numpy as np
import torch
from scipy.special import expit

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"
PROTEIN_DIR = DATA_DIR / "proteins"
CHECKPOINT = DATA_DIR / "checkpoints" / "tito_3M.ckpt"
OUTPUT_DIR = PROJECT_ROOT / "outputs"
LOCAL_3DMOL_JS = DATA_DIR / "3Dmol-min.js"  # optional offline copy of 3Dmol.js

# Residue names not in platito's vocabulary that we map to a standard amino acid.
# Norleucine (NLE, in the villin variant simulated by Lindorff-Larsen et al.) is a
# methionine isostere. With the unknown token "X" TITO-3M breaks the chain around
# these residues, so we map it to M. Anything else unknown becomes "X".
EXTRA_3_TO_1 = {
    "HID": "H", "HIE": "H", "HIP": "H", "CYX": "C", "ASH": "D", "GLH": "E",
    "LYN": "K", "MSE": "M", "NLE": "M",
}


# --------------------------------------------------------------------------
# Structures
# --------------------------------------------------------------------------
def list_proteins() -> dict:
    """Bundled fast-folding proteins: name -> (number of residues, MD temperature in K)."""
    temps = json.loads((PROTEIN_DIR / "temperatures.json").read_text())
    out = {}
    for name in sorted(temps):
        n_res = load_ca(PROTEIN_DIR / name / "folded.pdb").n_residues
        out[name] = (n_res, temps[name])
    return out


def reference_temperature(name: str) -> int:
    """Temperature (K) of the reference MD simulation (Lindorff-Larsen et al. 2011)."""
    return json.loads((PROTEIN_DIR / "temperatures.json").read_text())[name]


def load_ca(pdb_path) -> md.Trajectory:
    """Load a structure and keep only the C-alpha atoms of the first protein chain.

    Only the first frame/model is kept. Waters, ions and ligands are dropped.
    """
    with warnings.catch_warnings():  # e.g. dummy CRYST1 records in NMR/AlphaFold files
        warnings.simplefilter("ignore", UserWarning)
        traj = md.load(str(pdb_path))[0]

    def is_ca(atom):
        return atom.name == "CA" and atom.element is not None and atom.element.symbol == "C"

    chains = [c for c in traj.topology.chains if any(is_ca(a) for a in c.atoms)]
    if not chains:
        raise ValueError(f"No protein chain found in {pdb_path}")
    return traj.atom_slice([a.index for a in chains[0].atoms if is_ca(a)])


def load_protein(name: str, start: str = "unfolded"):
    """Load a bundled protein. Returns (starting structure, folded reference), C-alpha only."""
    start_ca = load_ca(PROTEIN_DIR / name / f"{start}.pdb")
    folded_ca = load_ca(PROTEIN_DIR / name / "folded.pdb")
    return start_ca, folded_ca


def fetch_structure(code: str, out_dir=OUTPUT_DIR / "structures") -> Path:
    """Download a structure (needs internet).

    ``code`` is either a PDB ID (e.g. ``"1L2Y"``) or an AlphaFold DB entry
    (``"AF-<UniProt ID>-F1"``, e.g. ``"AF-P01542-F1"``).
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{code}.pdb"
    if path.exists():
        return path
    if code.upper().startswith("AF-"):
        uniprot = code.split("-")[1]
        with urllib.request.urlopen(
            f"https://alphafold.ebi.ac.uk/api/prediction/{uniprot}", timeout=30
        ) as r:
            url = json.loads(r.read())[0]["pdbUrl"]
    else:
        url = f"https://files.rcsb.org/download/{code.upper()}.pdb"
    urllib.request.urlretrieve(url, path)
    return path


def sequence(ca: md.Trajectory) -> str:
    """One-letter amino-acid sequence of a C-alpha structure."""
    from platito.utils.amino_acid_vocab import AA_3_TO_1

    vocab = {**AA_3_TO_1, **EXTRA_3_TO_1}
    return "".join(vocab.get(r.name, "X") for r in ca.topology.residues)


def residue_ids(ca: md.Trajectory) -> list[int]:
    """Integer amino-acid tokens used by the model."""
    from platito.utils.amino_acid_vocab import AA_1_TO_ID

    return [AA_1_TO_ID.get(a, AA_1_TO_ID["X"]) for a in sequence(ca)]


# --------------------------------------------------------------------------
# Model
# --------------------------------------------------------------------------
def load_tito(path=CHECKPOINT, device: str = "cpu"):
    """Load a (PLa)TITO checkpoint for inference.

    The checkpoint stores whole network objects (not only weights), hence
    ``weights_only=False``. Only do this for checkpoints you trust.
    """
    from platito.models import PLaTITO

    logging.getLogger("lightning").setLevel(logging.ERROR)
    logging.getLogger("lightning.pytorch").setLevel(logging.ERROR)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        model = PLaTITO.load_from_checkpoint(
            str(path), map_location=device, weights_only=False
        )
    return model.to(device).eval()


def _conditions(ca: md.Trajectory, n: int, lag_ns, temperature, device):
    lag = torch.as_tensor(lag_ns, dtype=torch.long, device=device)
    temp = torch.as_tensor(temperature, dtype=torch.long, device=device)
    return {
        "lag": lag.expand(n).clone() if lag.ndim == 0 else lag,
        "temp": temp.expand(n).clone() if temp.ndim == 0 else temp,
        "residue_ids": torch.tensor([residue_ids(ca)] * n, device=device),
    }


@torch.no_grad()
def propagate(model, ca: md.Trajectory, x, lag_ns: int, temperature: int,
              ode_steps: int = 10, ode_method: str = "midpoint") -> np.ndarray:
    """One step of the learned transfer operator: x_{t+Δt} ~ p(. | x_t).

    Parameters
    ----------
    x : array [n, L, 3] (nm)
        Batch of current configurations (``n`` independent samples).
    lag_ns : int
        Lag time Δt in ns.
    ode_steps, ode_method :
        Number of steps and integrator ("euler", "midpoint", "rk4") for the
        flow-matching ODE that turns noise into a sample. The paper uses 50
        Euler steps. 10 midpoint steps (20 network evaluations) are about as
        accurate and 2.5x cheaper. 20 Euler steps are a bit too coarse: the
        small bias accumulates over long rollouts and breaks the chain.

    Returns
    -------
    array [n, L, 3] of new configurations (nm, centred at the origin).
    """
    device = model.device
    x = torch.as_tensor(np.asarray(x), dtype=torch.float32, device=device)
    cond = _conditions(ca, x.shape[0], lag_ns, temperature, device)
    out = model.sample(x0=x, ode_steps=ode_steps, ode_method=ode_method, **cond)
    return out.cpu().numpy()


@torch.no_grad()
def simulate(model, start: md.Trajectory, n_traj: int, n_steps: int,
             lag_ns: int, temperature: int, ode_steps: int = 10,
             ode_method: str = "midpoint", seed: int | None = 0,
             progress: bool = True) -> np.ndarray:
    """Generate ``n_traj`` trajectories of ``n_steps`` steps from one start structure.

    Returns
    -------
    coords : array [n_traj, n_steps + 1, L, 3] in nm. Frame 0 is the start.
        Time between frames is ``lag_ns``.
    """
    from tqdm.auto import trange

    if seed is not None:
        torch.manual_seed(seed)
    x = np.repeat(start.xyz[:1], n_traj, axis=0)
    x = x - x.mean(axis=1, keepdims=True)
    frames = [x]
    for _ in trange(n_steps, desc="TITO steps", disable=not progress):
        x = propagate(model, start, x, lag_ns, temperature, ode_steps, ode_method)
        frames.append(x)
    return np.stack(frames, axis=1)


def time_one_step(model, start, n_traj, lag_ns, temperature, ode_steps=10,
                  ode_method: str = "midpoint") -> float:
    """Wall-clock seconds for one TITO step with ``n_traj`` trajectories."""
    x = np.repeat(start.xyz[:1], n_traj, axis=0)
    propagate(model, start, x[:2], lag_ns, temperature, 2)  # warm-up
    t0 = time.perf_counter()
    propagate(model, start, x, lag_ns, temperature, ode_steps, ode_method)
    return time.perf_counter() - t0


# --------------------------------------------------------------------------
# Trajectories <-> files
# --------------------------------------------------------------------------
def to_mdtraj(coords: np.ndarray, top_ca: md.Trajectory, lag_ns: float = 1.0) -> md.Trajectory:
    """Wrap an array [n_frames, L, 3] (one trajectory) as an mdtraj Trajectory."""
    t = md.Trajectory(np.asarray(coords, dtype=np.float32), top_ca.topology)
    t.time = np.arange(len(t)) * lag_ns * 1000.0  # ps
    return t


def save_trajectories(coords: np.ndarray, top_ca: md.Trajectory, name: str,
                      lag_ns: float, out_dir=OUTPUT_DIR, reference=None) -> Path:
    """Save each trajectory as DCD (+ one PDB topology), aligned to ``reference``.

    Open them in ChimeraX / VMD / PyMOL, e.g.
    ``vmd topology.pdb traj_000.dcd`` or in ChimeraX ``open topology.pdb; open traj_000.dcd structureModel #1``.
    """
    out = Path(out_dir) / name
    out.mkdir(parents=True, exist_ok=True)
    ref = top_ca if reference is None else reference
    ref.save_pdb(str(out / "topology.pdb"))
    for i, c in enumerate(coords):
        t = to_mdtraj(c, top_ca, lag_ns).superpose(ref)
        t.save_dcd(str(out / f"traj_{i:03d}.dcd"))
    np.save(out / "coords_nm.npy", coords)
    return out


# --------------------------------------------------------------------------
# Observables. All take coords [n_traj, n_frames, L, 3] (or [n_frames, L, 3])
# and return arrays [n_traj, n_frames] (or [n_frames]).
# --------------------------------------------------------------------------
def _flat(coords, top_ca):
    coords = np.asarray(coords, dtype=np.float32)
    shape = coords.shape[:-2]
    t = md.Trajectory(coords.reshape(-1, *coords.shape[-2:]), top_ca.topology)
    return t, shape


def rmsd(coords, reference: md.Trajectory, top_ca=None) -> np.ndarray:
    """C-alpha RMSD (nm) to ``reference`` after optimal superposition."""
    t, shape = _flat(coords, top_ca or reference)
    return md.rmsd(t, reference, 0).reshape(shape)


def radius_of_gyration(coords, top_ca) -> np.ndarray:
    """Radius of gyration (nm) of the C-alpha atoms."""
    t, shape = _flat(coords, top_ca)
    return md.compute_rg(t).reshape(shape)


def native_contacts(reference: md.Trajectory, cutoff: float = 1.0,
                    min_seq_sep: int = 4):
    """C-alpha pairs (|i-j| >= min_seq_sep) closer than ``cutoff`` nm in the reference.

    Returns (pairs [n_contacts, 2], reference distances r0 [n_contacts]).
    """
    n = reference.n_atoms
    i, j = np.triu_indices(n, k=min_seq_sep)
    pairs = np.stack([i, j], axis=1)
    r0 = md.compute_distances(reference, pairs)[0]
    keep = r0 < cutoff
    return pairs[keep], r0[keep]


def fraction_native_contacts(coords, reference: md.Trajectory, cutoff: float = 1.0,
                             min_seq_sep: int = 4, beta: float = 50.0,
                             lam: float = 1.2) -> np.ndarray:
    """Fraction of native contacts Q (Best, Hummer & Eaton, PNAS 2013), C-alpha version.

    Q = mean over native pairs of 1 / (1 + exp(beta * (r - lam * r0))).
    Q ~ 1 for the folded structure, Q -> 0 for unfolded structures.
    beta in 1/nm, lam is the tolerance factor for thermal fluctuations.
    """
    pairs, r0 = native_contacts(reference, cutoff, min_seq_sep)
    t, shape = _flat(coords, reference)
    r = md.compute_distances(t, pairs)
    q = np.mean(expit(-beta * (r - lam * r0)), axis=1)  # expit(z) = 1 / (1 + exp(-z))
    return q.reshape(shape)


def bond_lengths(coords) -> np.ndarray:
    """Distances (nm) between consecutive C-alpha atoms (should be ~0.38 nm)."""
    coords = np.asarray(coords)
    return np.linalg.norm(coords[..., 1:, :] - coords[..., :-1, :], axis=-1)


def ca_distances(coords, n_beads: int | None = 16) -> np.ndarray:
    """C-alpha pair distances used as TICA features.

    To keep the number of features small compared to the number of frames we
    have (a few hundred), we use ``n_beads`` evenly spaced residues and all
    pairs among them that are not neighbours in that subset.
    ``n_beads=None`` uses all residues and all pairs with |i - j| > 2
    (as in the platito repository, which has far more data).

    coords [..., L, 3] -> [..., n_pairs]
    """
    coords = np.asarray(coords)
    L = coords.shape[-2]
    if n_beads is None or n_beads >= L:
        idx, excl = np.arange(L), 2 if n_beads is None else 1
    else:
        idx, excl = np.unique(np.linspace(0, L - 1, n_beads).round().astype(int)), 1
    i, j = np.triu_indices(len(idx), k=excl + 1)
    sub = coords[..., idx, :]
    return np.linalg.norm(sub[..., i, :] - sub[..., j, :], axis=-1)


def fit_tica(coords_list, lagtime: int = 1, dim: int = 2):
    """Fit a TICA model (deeptime) on C-alpha distances (see ``ca_distances``).

    coords_list: list of arrays [n_traj, n_frames, L, 3]; every trajectory is
    used as a separate time series. ``lagtime`` is in frames (model steps).
    """
    from deeptime.decomposition import TICA

    series = [ca_distances(traj) for c in coords_list for traj in c]
    return TICA(lagtime=lagtime, dim=dim).fit(series).fetch_model()


def tica_project(tica, coords) -> np.ndarray:
    """Project coords [n_traj, n_frames, L, 3] -> [n_traj, n_frames, dim]."""
    feats = ca_distances(coords)
    flat = tica.transform(feats.reshape(-1, feats.shape[-1]))
    return flat.reshape(*feats.shape[:-1], -1)


# --------------------------------------------------------------------------
# Free energies and plots
# --------------------------------------------------------------------------
def free_energy_1d(values, bins=30, range=None):
    """F(x) = -ln p(x) in units of kT, shifted so that min F = 0."""
    h, edges = np.histogram(np.ravel(values), bins=bins, range=range, density=True)
    with np.errstate(divide="ignore"):
        f = -np.log(h)
    f -= np.min(f[np.isfinite(f)])
    return 0.5 * (edges[1:] + edges[:-1]), f


def free_energy_2d(x, y, bins=40, range=None):
    """2D free energy -ln p(x, y) in kT. Returns (xcenters, ycenters, F[ny, nx])."""
    h, xe, ye = np.histogram2d(np.ravel(x), np.ravel(y), bins=bins, range=range,
                               density=True)
    with np.errstate(divide="ignore"):
        f = -np.log(h.T)
    f -= np.min(f[np.isfinite(f)])
    return 0.5 * (xe[1:] + xe[:-1]), 0.5 * (ye[1:] + ye[:-1]), f


def plot_timeseries(obs, lag_ns, ax=None, ylabel="", max_traj=16, color=None, label=None):
    """Plot an observable [n_traj, n_frames] versus time (ns), one line per trajectory."""
    ax = ax or plt.gca()
    t = np.arange(obs.shape[-1]) * lag_ns
    for k, o in enumerate(obs[:max_traj]):
        ax.plot(t, o, lw=0.8, alpha=0.6, color=color,
                label=label if k == 0 else None)
    ax.set_xlabel("time (ns)")
    ax.set_ylabel(ylabel)
    return ax


def plot_free_energy_2d(x, y, bins=20, range=None, ax=None, label=r"F / $k_BT$"):
    """Plot -ln p(x, y) (in kT) as a coloured histogram; empty bins stay white."""
    ax = ax or plt.gca()
    xc, yc, f = free_energy_2d(x, y, bins=bins, range=range)
    f = np.ma.masked_invalid(f)
    im = ax.pcolormesh(xc, yc, f, cmap="viridis", shading="nearest")
    plt.colorbar(im, ax=ax, label=label)
    return ax


def plot_snapshots(coords, frames, reference=None, top_ca=None, title=""):
    """Static 3D C-alpha traces of selected frames (works without internet)."""
    coords = np.asarray(coords)
    xs = []
    for f in frames:
        x = coords[f]
        if reference is not None:
            x = to_mdtraj(x, top_ca or reference).superpose(reference).xyz[0]
        xs.append(x - x.mean(0))
    r = max(np.abs(x).max() for x in xs)  # same scale in all panels
    fig = plt.figure(figsize=(3 * len(frames), 3))
    for k, (f, x) in enumerate(zip(frames, xs)):
        ax = fig.add_subplot(1, len(frames), k + 1, projection="3d")
        ax.plot(*x.T, "-", color="0.6", lw=1)
        ax.scatter(*x.T, c=np.arange(len(x)), cmap="viridis", s=15)
        ax.set_xlim(-r, r); ax.set_ylim(-r, r); ax.set_zlim(-r, r)
        ax.set_box_aspect((1, 1, 1))
        ax.set_title(f"frame {f}", fontsize=9)
        ax.set_axis_off()
    fig.suptitle(title)
    return fig


def _multimodel_pdb(xyz_nm, ca: md.Trajectory) -> str:
    """Multi-model PDB string with explicit CONECT records along the chain."""
    lines = []
    res = list(ca.topology.residues)
    for m, x in enumerate(xyz_nm * 10.0):  # nm -> Angstrom
        lines.append(f"MODEL     {m + 1:4d}")
        for i, (r, p) in enumerate(zip(res, x)):
            lines.append(
                f"ATOM  {i + 1:5d}  CA  {r.name:3s} A{i + 1:4d}    "
                f"{p[0]:8.3f}{p[1]:8.3f}{p[2]:8.3f}  1.00  0.00           C"
            )
        for i in range(1, len(res)):
            lines.append(f"CONECT{i:5d}{i + 1:5d}")
        lines.append("ENDMDL")
    lines.append("END")
    return "\n".join(lines)


def show_trajectory(coords, top_ca: md.Trajectory, reference=None, stride: int = 1,
                    width: int = 500, height: int = 400):
    """Animated 3D view of one trajectory [n_frames, L, 3] with py3Dmol.

    Uses a local copy of 3Dmol.js (``data/3Dmol-min.js``) if present, otherwise
    loads it from the internet. Without either, use ``plot_snapshots`` or open
    the saved DCD files in ChimeraX / VMD / PyMOL.
    """
    import py3Dmol

    t = to_mdtraj(np.asarray(coords)[::stride], top_ca)
    t.superpose(reference if reference is not None else t)
    kwargs = {}
    if LOCAL_3DMOL_JS.exists():
        b64 = base64.b64encode(LOCAL_3DMOL_JS.read_bytes()).decode()
        kwargs["js"] = f"data:text/javascript;base64,{b64}"
    view = py3Dmol.view(width=width, height=height, **kwargs)
    view.addModelsAsFrames(_multimodel_pdb(t.xyz, top_ca), "pdb")
    scheme = {"prop": "resi", "gradient": "roygb", "min": 1, "max": top_ca.n_atoms}
    view.setStyle({}, {"stick": {"radius": 0.3, "colorscheme": scheme},
                       "sphere": {"radius": 0.6, "colorscheme": scheme}})
    view.zoomTo()
    view.animate({"loop": "forward", "interval": 150})
    return view

"""Interface geometry that can honestly be computed from C-alpha coordinates, and nothing else.

This replaces an earlier `validation.py` that reported pLDDT, ipTM, buried surface area and shape
complementarity. None of those were computed: pLDDT and ipTM came from hand-written formulas with
no structure predictor behind them, buried area came from multiplying a residue count by a
constant, and shape complementarity was a fitted guess. They are gone.

What remains is measured directly from the coordinates:

  * how close the two chains come
  * how many residues sit at the interface
  * how many of the named target hotspots are engaged
  * how many C-alpha pairs are too close to be physical

That is a description of an arrangement in space. It is not evidence that a design folds or binds;
only structure prediction and experiment can speak to that. Nothing here should be read as a
confidence or a score, which is why none of it is combined into one.
"""
import numpy as np

INTERFACE_CUTOFF = 8.0      # C-alpha separation counted as interface contact, Angstrom
CLASH_CUTOFF = 3.8          # closer than this, two C-alphas cannot both be there


def interface_geometry(scaffold_ca, target_ca, hotspot_ca=None):
    """Measured interface descriptors. Every value is a count or a distance, never a prediction."""
    scaffold_ca = np.asarray(scaffold_ca, float)
    target_ca = np.asarray(target_ca, float)
    dists = np.linalg.norm(scaffold_ca[:, None, :] - target_ca[None, :, :], axis=2)

    nearest_per_scaffold_residue = dists.min(axis=1)
    out = {
        "min_ca_distance_angstrom": float(dists.min()),
        "interface_residues": int((nearest_per_scaffold_residue < INTERFACE_CUTOFF).sum()),
        "ca_pairs_within_cutoff": int((dists < INTERFACE_CUTOFF).sum()),
        "ca_clashes": int((dists < CLASH_CUTOFF).sum()),
        "interface_cutoff_angstrom": INTERFACE_CUTOFF,
    }

    if hotspot_ca is not None and len(hotspot_ca):
        hotspot_ca = np.asarray(hotspot_ca, float)
        hd = np.linalg.norm(scaffold_ca[:, None, :] - hotspot_ca[None, :, :], axis=2)
        engaged = int((hd.min(axis=0) < INTERFACE_CUTOFF).sum())
        out["hotspots_engaged"] = engaged
        out["hotspots_total"] = int(len(hotspot_ca))
    return out


def rank_key(geom):
    """Ordering for inspection only: most hotspots engaged, then most interface residues, no clashes.

    This orders candidates for a human to look at. It is not a quality score and does not predict
    which designs would work."""
    return (-geom.get("hotspots_engaged", 0), -geom["interface_residues"], geom["ca_clashes"])

"""Figure of the water radial distribution functions, Verlet against OpenMM (results/rdf.png)."""
import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
R = os.path.join(ROOT, "results")
runs = {"Verlet": "rdf_verlet.csv", "OpenMM": "rdf_openmm.csv"}
style = {"Verlet": dict(color="#2f6db0", lw=2), "OpenMM": dict(color="#c9a227", lw=1.5, ls="--")}
fig, axes = plt.subplots(1, 3, figsize=(11, 3.4), sharex=True)
for name, f in runs.items():
    d = np.genfromtxt(os.path.join(R, f), delimiter=",", names=True)
    for ax, col, title in zip(axes, ("g_OO", "g_OH", "g_HH"), ("O-O", "O-H", "H-H")):
        ax.plot(d["r_nm"], d[col], label=name, **style[name])
        ax.set_title(title)
axes[0].plot([0.280], [2.57], "o", color="#444", label="experiment (peak)")
for ax in axes:
    ax.set_xlim(0.1, 0.9)
    ax.set_xlabel("r (nm)")
    ax.grid(alpha=0.25)
    ax.spines[["top", "right"]].set_visible(False)
axes[0].set_ylabel("g(r)")
axes[0].legend(frameon=False)
fig.suptitle("TIP3P water at 298.15 K, 1 bar: radial distribution functions", fontsize=11)
fig.tight_layout()
fig.savefig(os.path.join(R, "rdf.png"), dpi=120)
print("results/rdf.png")

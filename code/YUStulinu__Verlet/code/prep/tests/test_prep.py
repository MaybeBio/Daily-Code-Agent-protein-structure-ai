import os
import sys

import numpy as np
import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.dirname(HERE))

from verlet_prep.__main__ import load_ff  # noqa: E402
from verlet_prep.forcefield import build_system  # noqa: E402
from verlet_prep.pdb import read_pdb  # noqa: E402
from verlet_prep.topology import read_vsys, write_vsys  # noqa: E402
from verlet_prep.water import water_box, water_geometry, waters_per_nm3  # noqa: E402

PDB = os.path.join(ROOT, "data", "pdb", "1UAO.pdb")


@pytest.fixture(scope="module")
def ff():
    return load_ff("tip3p")


def test_parameters_match_openmm(ff, tmp_path):
    """Our assignment of ff14SB to chignolin gives OpenMM's energies, term by term."""
    from verlet_prep import openmm_ref as ref

    s = build_system(ff, read_pdb(PDB), np.array([5.0, 5.0, 5.0]))
    ours, f_ours = ref.energies(ref.openmm_system(s, method="NoCutoff", dispersion=False), s.xyz)
    first_model = open(PDB).read().split("ENDMDL")[0] + "ENDMDL\nEND\n"
    path = tmp_path / "first.pdb"
    path.write_text(first_model)
    osys, pos = ref.openmm_forcefield_system(str(path), ["amber14/protein.ff14SB.xml", "amber14/tip3p.xml"])
    theirs, f_theirs = ref.energies(osys, pos)
    for term in ("bond", "angle", "torsion", "nonbonded"):
        assert ours[term] == pytest.approx(theirs[term], abs=1e-5), term
    # OpenMM caches the atom order of the first improper of each type signature, so a few
    # aromatic impropers list their atoms in another order: same energy, forces within 0.01
    assert np.abs(f_ours - f_theirs).max() < 1e-2


def test_vsys_round_trip(ff, tmp_path):
    s = build_system(ff, read_pdb(PDB), np.array([5.0, 5.0, 5.0]))
    path = tmp_path / "s.vsys"
    write_vsys(str(path), s)
    t = read_vsys(str(path))
    assert t.n == s.n and t.names == s.names
    assert np.allclose(t.xyz, s.xyz, atol=1e-6) and np.allclose(t.charge, s.charge)
    assert len(t.torsions) == len(s.torsions) and len(t.pairs14) == len(s.pairs14)
    assert t.exclusions == s.exclusions and t.molecules == s.molecules
    assert abs(s.charge.sum() - round(s.charge.sum())) < 1e-6  # whole net charge


def test_water_box(ff):
    doh, dhh, angle = water_geometry(ff)
    assert doh == pytest.approx(0.09572) and np.degrees(angle) == pytest.approx(104.52, abs=1e-3)
    box = water_box(ff, 216)
    assert len(box.residues) == 216
    assert 216 / box.box.prod() == pytest.approx(waters_per_nm3(0.997))
    for r in box.residues:  # every water has the force-field geometry
        o, h1, h2 = (a.xyz for a in r.atoms)
        assert np.linalg.norm(h1 - o) == pytest.approx(doh) and np.linalg.norm(h2 - h1) == pytest.approx(dhh)

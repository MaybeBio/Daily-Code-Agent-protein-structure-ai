"""Reference systems for validation against EMC and LAMMPS, and the locations of their files.

The reference data (EMC .data/.params, LAMMPS single points) are generated in reference/ by scripts/make_emc_reference.py and scripts/make_lammps_reference.py.
pcff.frc and pcff_templates.dat are read from the EMC installation (EMC_ROOT/field/cff/pcff); they are not distributed with this repository.
"""

import os
from pathlib import Path

from rdkit import Chem


REFERENCE_ROOT = Path(__file__).resolve().parent.parent / "reference"

# PCFF files as shipped with EMC v9.4.4; None when the environment variable EMC_ROOT (the EMC installation directory) is not set.
PCFF_FIELD_DIRECTORY = Path(os.environ["EMC_ROOT"]) / "field" / "cff" / "pcff" if "EMC_ROOT" in os.environ else None
FRC_PATH = PCFF_FIELD_DIRECTORY / "pcff.frc" if PCFF_FIELD_DIRECTORY else None
TEMPLATES_PATH = PCFF_FIELD_DIRECTORY / "pcff_templates.dat" if PCFF_FIELD_DIRECTORY else None
PCFF_FILES_AVAILABLE = FRC_PATH is not None and FRC_PATH.exists() and TEMPLATES_PATH.exists()

SYSTEMS = ["butane", "polyethylene"]


def polymer_chain_smiles(head_smiles: str, repeat_smiles: str, n_repeat_units: int, tail_smiles: str) -> str:
    return head_smiles + repeat_smiles * n_repeat_units + tail_smiles


# Reference systems built by EMC (scripts/make_emc_reference.py).
# molecule_smiles lists every distinct molecule of the system; openmm_pcff types them and maps them onto the EMC structure.
# Not included because EMC v9.4.4 stops with missing bond increments:
# N-methylacetamide and nylon-6 (amide N typed na), dimethyl sulfone, DMSO, trimethyl phosphate, CO2; nitro groups have no PCFF type.
SMALL_MOLECULES = {
    "benzene": "c1ccccc1",
    "toluene": "Cc1ccccc1",
    "propene": "C=CC",
    "butene": "C=CCC",
    "ethanol": "CCO",
    "diethyl_ether": "CCOCC",
    "acetone": "CC(=O)C",
    "methyl_acetate": "CC(=O)OC",
    "trimethylamine": "CN(C)C",
    "hexamethyldisiloxane": "C[Si](C)(C)O[Si](C)(C)C",
    "chlorobenzene": "Clc1ccccc1",
    "acetonitrile": "CC#N",
    "water": "O",
}

PROBE_MIXTURE_A = {
    "bromobenzene": "Brc1ccccc1",
    "fluorobenzene": "Fc1ccccc1",
    "benzonitrile": "N#Cc1ccccc1",
    "propionitrile": "CCC#N",
    "chloroethane": "CCCl",
    "dichloromethane": "ClCCl",
    "chloroform": "ClC(Cl)Cl",
    "fluoroethane": "CCF",
    "methanethiol": "CS",
    "dimethylsulfide": "CSC",
    "thiophene": "c1ccsc1",
    "furan": "c1ccoc1",
    "pyridine": "c1ccncc1",
    "phenol": "Oc1ccccc1",
    "anisole": "COc1ccccc1",
    "benzaldehyde": "O=Cc1ccccc1",
    "acetophenone": "CC(=O)c1ccccc1",
    "styrene": "C=Cc1ccccc1",
    "acrylonitrile": "C=CC#N",
    "vinylchloride": "C=CCl",
    "tetramethylsilane": "C[Si](C)(C)C",
    "phenylsilane": "C[Si](C)(C)c1ccccc1",
    "methylvinylether": "C=COC",
    "aniline": "Nc1ccccc1",
    "ethylamine": "CCN",
}

PROBE_MIXTURE_B = {
    "pyrrole": "c1cc[nH]c1",
    "imidazole": "c1cnc[nH]1",
    "oxazole": "c1cocn1",
    "aceticacid": "CC(=O)O",
    "benzoicacid": "OC(=O)c1ccccc1",
    "formaldehyde": "C=O",
    "butadiene": "C=CC=C",
    "allene": "C=C=C",
    "acetylene": "C#C",
    "propyne": "CC#C",
    "carbondisulfide": "S=C=S",
    "cyclopropane": "C1CC1",
    "cyclobutane": "C1CCC1",
    "cyclopentane": "C1CCCC1",
    "cyclohexane": "C1CCCCC1",
    "oxirane": "C1CO1",
    "oxetane": "C1COC1",
    "thf": "C1CCOC1",
    "dioxane": "C1COCCO1",
    "aziridine": "C1CN1",
    "trimethylsilanol": "C[Si](C)(C)O",
    "hexamethylcyclotrisiloxane": "C[Si]1(C)O[Si](C)(C)O[Si](C)(C)O1",
    "tetrafluoromethane": "FC(F)(F)F",
    "trifluorotoluene": "FC(F)(F)c1ccccc1",
    "iodomethane": "CI",
    "bromoethane": "CCBr",
    "ethanethiol": "CCS",
    "diphenylether": "c1ccc(Oc2ccccc2)cc1",
    "biphenyl": "c1ccc(-c2ccccc2)cc1",
    "naphthalene": "c1ccc2ccccc2c1",
    "cyclohexene": "C1=CCCCC1",
    "methylamine": "CN",
    "dimethylamine": "CNC",
    "tetrafluoroethylene": "FC(F)=C(F)F",
    "methanol": "CO",
    "ethylene": "C=C",
    "isobutylene": "CC(C)=C",
    "methylmethacrylate": "CC(=C)C(=O)OC",
    "phenylacetylene": "C#Cc1ccccc1",
}

EMC_SYSTEMS = {}

for name, smiles in SMALL_MOLECULES.items():
    EMC_SYSTEMS[name] = {
        "kind": "molecules",
        "description": f"Test molecule {smiles}; about 600 atoms at 0.5 g/cc.",
        "groups": {name: smiles},
        "n_atoms_total": 600,
        "molecule_smiles": [smiles],
    }

for name, groups in [("probe_mixture_a", PROBE_MIXTURE_A), ("probe_mixture_b", PROBE_MIXTURE_B)]:
    EMC_SYSTEMS[name] = {
        "kind": "molecules",
        "description": "Mixture of many small molecules with equal mole fractions, used to compare typing and parameter lookup (including automatic parameters) with EMC.",
        "groups": groups,
        "n_atoms_total": 60 * len(groups),
        "molecule_smiles": list(groups.values()),
    }

# Oligomers: 10 head-to-tail repeat units; the end groups attach to connection points 1 and 2 of the repeat unit.
POLYMERS = {
    "polystyrene": {"repeat": ("*CC(c1ccccc1)*", "CC(c1ccccc1)"), "head": ("*C", "C"), "tail": ("*C", "C"), "n_chains": 8},
    "pmma": {"repeat": ("*CC(C)(C(=O)OC)*", "CC(C)(C(=O)OC)"), "head": ("*C", "C"), "tail": ("*C", "C"), "n_chains": 8},
    "peo": {"repeat": ("*CCO*", "CCO"), "head": ("*C", "C"), "tail": ("*C", "C"), "n_chains": 12},
    "pdms": {"repeat": ("*[Si](C)(C)O*", "[Si](C)(C)O"), "head": ("*C", "C"), "tail": ("*[Si](C)(C)C", "[Si](C)(C)C"), "n_chains": 12},
}

N_REPEAT_UNITS = 10

for name, polymer in POLYMERS.items():
    chain_smiles = polymer_chain_smiles(polymer["head"][1], polymer["repeat"][1], N_REPEAT_UNITS, polymer["tail"][1])
    n_atoms_per_chain = Chem.AddHs(Chem.MolFromSmiles(chain_smiles)).GetNumAtoms()

    EMC_SYSTEMS[name] = {
        "kind": "polymer",
        "description": f"Oligomer, {N_REPEAT_UNITS} repeat units {polymer['repeat'][0]}, {polymer['n_chains']} chains.",
        "repeat_group": polymer["repeat"][0],
        "end_groups": {"head": (polymer["head"][0], 1), "tail": (polymer["tail"][0], 2)},
        "n_repeat_units": N_REPEAT_UNITS,
        "n_atoms_total": polymer["n_chains"] * n_atoms_per_chain,
        "molecule_smiles": [chain_smiles],
    }

# Molecules of the alkane systems (SYSTEMS), for the typing comparison.
ALKANE_MOLECULE_SMILES = {
    "butane": ["CCCC"],
    "polyethylene": [polymer_chain_smiles("C", "CC", 20, "C")],
}

# OpenMM settings that correspond to each LAMMPS case (see scripts/make_lammps_reference.py).
# The Ewald tolerance for periodic_ewald is chosen tight enough that the OpenMM Ewald sum is converged like the LAMMPS ewald 1e-10 reference.
CASE_SETTINGS = {
    "isolated": {"periodic": False, "coulomb_method": "no_cutoff", "ewald_error_tolerance": None},
    "isolated_modified": {"periodic": False, "coulomb_method": "no_cutoff", "ewald_error_tolerance": None},
    "periodic_nocoul": {"periodic": True, "coulomb_method": None, "ewald_error_tolerance": None},
    "periodic_ewald": {"periodic": True, "coulomb_method": "ewald", "ewald_error_tolerance": 1e-10},
}

def case_files(system_name: str, case: str) -> dict[str, Path]:
    case_directory = REFERENCE_ROOT / system_name / "singlepoint" / case

    if case.startswith("isolated"):
        data_path = case_directory / f"{system_name}_molecule1.data"
    else:
        data_path = REFERENCE_ROOT / system_name / f"{system_name}.data"

    return {
        "data": data_path,
        "params": case_directory / f"{system_name}.params",
        "log": case_directory / "log.lammps",
        "forces": case_directory / "forces.dump",
    }


def reference_molecules(system_name: str) -> list[Chem.Mol]:
    """RDKit molecules (explicit hydrogens) of a reference system, for typing it with openmm_pcff."""
    if system_name in EMC_SYSTEMS:
        smiles_list = EMC_SYSTEMS[system_name]["molecule_smiles"]
    else:
        smiles_list = ALKANE_MOLECULE_SMILES[system_name]

    return [Chem.AddHs(Chem.MolFromSmiles(smiles)) for smiles in smiles_list]

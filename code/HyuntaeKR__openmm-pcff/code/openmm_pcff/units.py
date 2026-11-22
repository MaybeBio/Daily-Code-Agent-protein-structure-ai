"""Conversion factors from LAMMPS real units to OpenMM units.

LAMMPS real: kcal/mol, Angstrom, degrees (in coefficient files), elementary charge, g/mol.
OpenMM: kJ/mol, nm, radians, elementary charge, amu (g/mol).
"""

import math


KJ_PER_KCAL = 4.184

NM_PER_ANGSTROM = 0.1

RADIANS_PER_DEGREE = math.pi / 180.0

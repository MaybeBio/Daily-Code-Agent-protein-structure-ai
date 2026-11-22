"""``LoupCalculator`` and ``lm.calc``: LoupMD as an ASE calculator.

ASE calls a calculator once per step and moves the atoms itself, so this front end runs one force evaluation per
call, with its copies between host and device: it is for relaxations, phonons, NEB and for checking LoupMD against
other codes. MD at full speed needs LoupMD to own the loop (``LoupEngine.run``).

The calculator is a thin layer over a ``ForceField`` (``loupmd.forcefield``): the model is resolved and the trust
rule applied when the calculator is made; the bundle and the engine are made at the first calculation, for the
structure's elements. The engine is kept while the atomic numbers stay; a change of their order or count sets the
system again on the same engine; an element outside the loaded bundle gets a new bundle and engine.

``dispersion=`` (a preset or an ``lm.Dispersion``, PLAN.md S6-D09) adds the D3 term to every calculation, resolved
against the model as ``lm.md`` does. The force field's engine is shared by its calculators, so each calculation sets
the calculator's own term on it (or removes it) before it runs.
"""
from __future__ import annotations

from ase.calculators.calculator import Calculator, all_changes

from ..errors import InputError, PlanRefused
from ..forcefield import ForceField, load


class LoupCalculator(Calculator):
    """Energy, free energy (the same number), forces, Voigt stress and per-atom energies in ASE units, for cells
    periodic in all three directions. See ``loupmd.calc`` for the arguments. Per-atom energies
    (``get_potential_energies``) need the generic kernels and a short-range model."""

    implemented_properties = ["energy", "free_energy", "forces", "stress", "energies"]

    def __init__(self, force_field: ForceField, *, skin: float = 0.5, dispersion=None):
        from .. import dispersion as _dispersion

        super().__init__()
        self.force_field, self.skin = force_field, float(skin)
        self.dispersion = _dispersion.resolve(_dispersion.parse(dispersion), functional=force_field.functional,
                                              family=force_field.family, model=force_field.name)
        if self.dispersion is not None:
            _dispersion.runnable(self.dispersion)

    @property
    def engine(self):
        """The ``LoupEngine`` of the last structure (``None`` before the first calculation)."""
        return self.force_field.engine

    def calculate(self, atoms=None, properties=("energy",), system_changes=all_changes):
        from ase.stress import full_3x3_to_voigt_6_stress

        Calculator.calculate(self, atoms, properties, system_changes)
        with_stress = "stress" in properties
        engine = self.force_field.engine_for(self.atoms, self.skin)
        if getattr(engine, "dispersion", None) != self.dispersion:
            if not hasattr(engine, "set_dispersion"):
                raise PlanRefused("dispersion with the tiled execution",
                                  why="the cell does not fit the GPU whole, and the tiled execution has no "
                                      "dispersion term in this version (PLAN.md S6-D09)",
                                  next_step="Use a smaller cell, or a calculator without dispersion.")
            engine.set_dispersion(self.dispersion)
        if "energies" in properties:            # atoms.get_potential_energies(): one more energy-only pass
            energy, forces, stress, energies = self.force_field.evaluate_per_atom(self.atoms, stress=with_stress,
                                                                                  skin=self.skin)
        else:
            energy, forces, stress = self.force_field.evaluate(self.atoms, stress=with_stress, skin=self.skin)
            energies = None
        self.results = {"energy": energy, "free_energy": energy, "forces": forces}
        if energies is not None:
            self.results["energies"] = energies
        if with_stress:
            self.results["stress"] = full_3x3_to_voigt_6_stress(stress)


def calc(model, *, head=None, checkpoint=None, sha256=None, trusted=False, download=False, charge=None,
         spin_multiplicity=None, device=None, skin=0.5, dispersion=None, engine_factory=None, ensure_bundle=None,
         probe=None, environ=None):
    """``atoms.calc = lm.calc("omat0-medium")``: an ASE calculator for ``model``.

    ``model`` is what ``lm.load`` takes (a label, a checkpoint path or a URL, with ``head``, ``checkpoint``,
    ``sha256`` / ``trusted``, ``download``, ``charge``, ``spin_multiplicity`` and ``device`` as there), or a
    ``ForceField`` that ``lm.load`` returned (then without those). ``skin`` is the neighbour-list skin in A.
    ``dispersion`` adds the D3 term (a preset name such as ``"d3bj"`` or an ``lm.Dispersion``).

    The stress is computed only when it is asked for.
    """
    if isinstance(model, ForceField):
        given = {"head": head, "checkpoint": checkpoint, "sha256": sha256, "charge": charge,
                 "spin_multiplicity": spin_multiplicity, "device": device}
        named = [name for name, value in given.items() if value is not None] + [
            name for name, value in (("trusted", trusted), ("download", download)) if value]
        if named:
            raise InputError(f"the model is already loaded, so {', '.join(named)} cannot be given here",
                             next_step="Pass them to lm.load instead.")
        return LoupCalculator(model, skin=skin, dispersion=dispersion)
    return LoupCalculator(load(model, head, checkpoint=checkpoint, sha256=sha256, trusted=trusted, download=download,
                               charge=charge, spin_multiplicity=spin_multiplicity, device=device or 0,
                               engine_factory=engine_factory, ensure_bundle=ensure_bundle, probe=probe,
                               environ=environ), skin=skin, dispersion=dispersion)

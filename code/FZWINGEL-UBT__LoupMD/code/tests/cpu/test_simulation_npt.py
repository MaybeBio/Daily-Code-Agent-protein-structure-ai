"""``Simulation`` with a barostat (plan task S4-T07) on the fake engine of ``fake_core.py``, taught a
made-up equation of state: the cell is the engine's, rows carry volume and pressure, frames and the restart carry
the cell, and the engine's stop at the cell limits becomes ``CellDivergedError``. No GPU needed."""
from __future__ import annotations

import numpy as np
import pytest
from ase import units
from ase.build import bulk
from ase.constraints import FixAtoms
from fake_core import SpringEngine

import loupmd
from loupmd import BackendError, CellDivergedError, InputError, Output, PlanRefused, _core, integrators, output, report
from loupmd.config import IntegratorConfig

BULK_GPA = 100.0            # the fake's bulk modulus


class CellEngine(SpringEngine):
    """The spring engine with a cell that answers pressure: P = B (V_eq / V - 1) plus the ideal-gas part, with
    V_eq 5% above the starting volume. A Berendsen NPT call scales cell, positions and spring sites as ASE's
    ``NPTBerendsen`` does."""

    diverge_at = None       # an md step at which the run stops as the engine does at its cell limits

    def set_state(self, positions, velocities, cell):
        super().set_state(positions, velocities, cell)
        self.cell = np.array(cell, dtype=float)
        self.v_eq = 1.05 * abs(np.linalg.det(self.cell))
        self.reference_volume = abs(np.linalg.det(self.cell))

    def get_cell(self):
        return self.cell.copy()

    def set_reference_volume(self, volume):
        self.reference_volume = float(volume)
        self.log.append(("reference volume", float(volume)))

    def _volume(self):
        return abs(float(np.linalg.det(self.cell)))

    def _virial_pressure(self):
        return BULK_GPA * (self.v_eq / self._volume() - 1.0)

    def _pressure(self):
        e_kin = 0.5 * float((self.masses[:, None] * self.vel ** 2).sum())
        return self._virial_pressure() + 2.0 * e_kin / (3.0 * self._volume()) / units.GPa

    def evaluate(self, positions, cell, compute_stress=True):
        energy, forces, _ = super().evaluate(positions, cell, compute_stress)
        stress = -self._virial_pressure() * units.GPa * np.eye(3) if compute_stress else None
        return energy, forces, stress

    def export_state(self):
        import pickle

        return pickle.dumps((self.n, self.pos, self.vel, self.cell, self.sites, self.v_eq))

    def import_state(self, blob):
        import pickle

        state = pickle.loads(blob)
        super().import_state(pickle.dumps(state[:5]))
        self.v_eq = state[5]
        if not hasattr(self, "reference_volume"):
            self.reference_volume = self._volume()

    def run(self, n_steps, it):
        if it.kind not in (_core.LOUP_BERENDSEN_NPT, _core.LOUP_BAOAB_NPT, _core.LOUP_MTK_NPT):
            return super().run(n_steps, it)
        if it.kind == _core.LOUP_MTK_NPT:                # the fake has one barostat: MTK's settings as Berendsen's
            it.compressibility_per_gpa = 1.0 / BULK_GPA
        if it.kind == _core.LOUP_BAOAB_NPT:              # the fake has one barostat: BAOAB's settings as Berendsen's
            it.tau_p_fs, it.compressibility_per_gpa = it.tau_p_fs or 20.0 / it.friction_per_fs, 1.0 / BULK_GPA
        dt = it.dt_fs * units.fs
        inverse_mass = self._inverse_mass()
        dof = 3 * self.n - (3 if it.fix_com else 0)
        forces = self._forces()
        for _ in range(n_steps):
            if CellEngine.diverge_at is not None and self.md_steps + 1 == CellEngine.diverge_at:
                raise BackendError(f"loup_run: the cell diverged: its volume is {21 * self.reference_volume:g} A^3, "
                                   f"outside [V0 / 20, 20 V0] with V0 = {self.reference_volume:g} A^3",
                                   call="loup_run")
            scale = 1.0 - it.dt_fs / it.tau_p_fs * it.compressibility_per_gpa / 3.0 * (it.pressure_gpa - self._pressure())
            factors = np.full(3, scale)
            if it.cell_mode == _core.LOUP_CELL_FULL:
                factors = np.where(np.array(list(it.cell_mask)) == 1, scale, 1.0)
            self.cell = factors[:, None] * self.cell                   # cubic cell: each vector by its factor
            self.pos, self.sites = self.pos * factors, self.sites * factors
            self.vel += 0.5 * dt * forces * inverse_mass
            self.pos += dt * self.vel
            forces = self._forces()
            self.vel += 0.5 * dt * forces * inverse_mass
            self.md_steps += 1
            self.total_steps += 1
            if it.thermo_every and self.md_steps % it.thermo_every == 0:
                e_kin = 0.5 * float((self.masses[:, None] * self.vel ** 2).sum())
                self.rows.append((self.md_steps, self._energy(), e_kin, 2 * e_kin / (dof * units.kB),
                                  self._pressure(), self._volume(), self._energy() + e_kin))
        self.forces_current = True
        self.log.append(("run", n_steps, it.kind, it.thermo_every))
        self.targets.append((n_steps, it.temp_k, it.temp_rate_k_per_step))
        return _core.LoupMDStats(step_ms=0.5, rebuilds=1, final_temperature_k=300.0, pipelined_steps=0)


NPT = dict(timestep_fs=1.0, temperature_K=300.0, taut_fs=50.0, pressure_GPa=0.0, taup_fs=20.0,
           compressibility_per_GPa=1.0 / BULK_GPA)


@pytest.fixture
def setup(tmp_path):
    checkpoint = tmp_path / "some.model"
    checkpoint.write_bytes(b"never unpickled here")
    SpringEngine.made, SpringEngine.poison_at, CellEngine.diverge_at = [], None, None

    def force_field():
        return loupmd.load(str(checkpoint), trusted=True, engine_factory=CellEngine,
                           ensure_bundle=lambda model_path, numbers, **more: model_path.with_name("bundle.loup"),
                           probe=lambda p: None)

    atoms = bulk("NaCl", "rocksalt", a=5.64, cubic=True).repeat((2, 2, 2))            # 64 atoms, cubic
    atoms.set_velocities(np.random.default_rng(3).normal(0.0, 0.02, atoms.positions.shape))

    def make(directory=None, integrator=None, structure=None, **more):
        out = Output(str(tmp_path / directory), **more) if directory else None
        return loupmd.Simulation(structure or atoms, force_field(),
                                 integrator=integrator or integrators.Berendsen(**NPT), output=out, seed=7)

    make.atoms, make.tmp_path, make.force_field = atoms, tmp_path, force_field
    return make


def test_the_record_and_its_struct():
    record = integrators.Berendsen(**NPT)
    config = record.to_config(seed=1)
    assert (config.ensemble, config.scheme, config.pressure_GPa, config.taup_fs, config.mask) == \
        ("npt", "berendsen", 0.0, 20.0, None)
    it = config.to_struct(thermo_every=5)
    assert (it.kind, it.tau_t_fs, it.tau_p_fs, it.pressure_gpa, it.cell_mode, it.thermo_every) == \
        (_core.LOUP_BERENDSEN_NPT, 50.0, 20.0, 0.0, _core.LOUP_CELL_HYDROSTATIC, 5)
    assert it.compressibility_per_gpa == pytest.approx(0.01)
    masked = integrators.Berendsen(**NPT, mask=[1, 1, 0]).to_config(seed=1)       # a run file's list
    it = masked.to_struct()
    assert masked.mask == (1, 1, 0) and it.cell_mode == _core.LOUP_CELL_FULL and list(it.cell_mask) == [1, 1, 0]
    assert integrators.from_data(integrators.to_data(record)) == record
    assert not integrators.Berendsen(timestep_fs=1.0, temperature_K=300.0, taut_fs=50.0).barostat

    for fields, reason in ((dict(pressure_GPa=None), "the Berendsen barostat needs pressure_GPa"),
                           (dict(taup_fs=None, compressibility_per_GPa=None),
                            "the Berendsen barostat needs taup_fs, compressibility_per_GPa"),
                           (dict(taup_fs=0.0), "taup_fs must be positive and finite, got 0.0"),
                           (dict(pressure_GPa=float("nan")), "pressure_GPa must be finite"),
                           (dict(mask=(0, 0, 0)), "mask frees no axis"),
                           (dict(mask=(1, 2, 0)), "mask must be three entries of 0 or 1")):
        with pytest.raises(InputError, match=reason):
            integrators.Berendsen(**{**NPT, **fields})
    with pytest.raises(InputError, match="pressure_GPa belongs to a barostat, and the ensemble is 'nvt'"):
        IntegratorConfig(ensemble="nvt", scheme="langevin", temperature_K=300.0, friction_per_fs=0.01,
                         pressure_GPa=1.0)
    with pytest.raises(InputError, match="MTK NPT needs pressure_GPa, tau_fs, taup_fs"):
        IntegratorConfig(ensemble="npt", scheme="mtk", temperature_K=300.0)


def test_an_npt_run_writes_cell_volume_and_pressure(setup):
    sim = setup("run", thermo_every=10, trajectory_every=50, restart_every=100)
    sim.run(steps=200)
    directory = setup.tmp_path / "run"
    engine, = SpringEngine.made
    header, rows = output.read_thermo(directory)
    assert header == list(output.THERMO_HEADER + output.NPT_COLUMNS)
    assert [int(row[0]) for row in rows] == list(range(0, 201, 10))
    volumes = np.array([float(row[8]) for row in rows]) * 64
    pressures = np.array([float(row[9]) for row in rows])
    start = setup.atoms.get_volume()
    assert volumes[0] == pytest.approx(start, rel=1e-12) and volumes[-1] == pytest.approx(engine._volume(), rel=1e-12)
    assert volumes[1] > volumes[0] and volumes[-1] > 1.03 * start               # towards V_eq = 1.05 V
    assert pressures[0] == pytest.approx(engine_start_pressure(setup.atoms), rel=1e-9)   # the host's row at step 0
    assert pressures[-1] == pytest.approx(engine._pressure(), rel=1e-12) and abs(pressures[-1]) < abs(pressures[0])

    frames = output.read_frames(directory)
    assert len(frames) == 5
    assert np.allclose(frames[0].cell.array, setup.atoms.cell.array)
    assert np.allclose(frames[-1].cell.array, engine.get_cell(), rtol=1e-12)
    assert frames[2].get_volume() > frames[1].get_volume() > frames[0].get_volume()
    current = sim.atoms
    assert np.array_equal(current.cell.array, engine.get_cell()) and np.array_equal(current.positions, engine.pos)

    with np.load(directory / "restart.npz") as data:
        assert np.array_equal(data["cell"], engine.get_cell())
        assert float(data["reference_volume_A3"]) == pytest.approx(start, rel=1e-15)
    sim.close()

    again = loupmd.Simulation.resume(directory, force_field=setup.force_field())
    resumed = SpringEngine.made[-1]
    assert ("reference volume", pytest.approx(start)) in [entry for entry in resumed.log if isinstance(entry, tuple)]
    assert np.array_equal(resumed.get_cell(), engine.get_cell())
    again.run(steps=50)
    header, rows = output.read_thermo(directory)
    assert header == list(output.THERMO_HEADER + output.NPT_COLUMNS) and int(rows[-1][0]) == 250
    assert float(rows[-1][8]) * 64 == pytest.approx(resumed._volume(), rel=1e-12)
    again.close()


def engine_start_pressure(atoms):
    """What the host row of step 0 holds: the fake's virial pressure at V = V_eq / 1.05 plus the ideal-gas part."""
    e_kin = float(atoms.get_kinetic_energy())
    return BULK_GPA * 0.05 + 2.0 * e_kin / (3.0 * atoms.get_volume()) / units.GPa


def test_rows_between_the_engine_s_own_cadence_carry_pressure(setup):
    """A restart cadence that is no multiple of the thermo cadence makes the simulation write rows from states it
    reads back; a barostat's rows then take their stress from one more evaluation."""
    sim = setup("odd", thermo_every=10, trajectory_every=None, restart_every=25)
    sim.run(steps=60)
    header, rows = output.read_thermo(setup.tmp_path / "odd")
    engine, = SpringEngine.made
    assert [int(row[0]) for row in rows] == list(range(0, 61, 10))
    assert all(np.isfinite(float(row[9])) and float(row[8]) > 0 for row in rows)
    assert float(rows[-1][9]) == pytest.approx(engine._pressure(), rel=1e-9)
    sim.close()


def test_the_cell_limits_and_other_refusals(setup):
    CellEngine.diverge_at = 30
    sim = setup("diverged", thermo_every=10)
    with pytest.raises(CellDivergedError, match="the cell left its limits between steps") as caught:
        sim.run(steps=100)
    assert "outside [V0 / 20, 20 V0]" in str(caught.value.why) and 30 <= caught.value.step <= 40
    CellEngine.diverge_at = None

    fixed = setup.atoms.copy()
    fixed.set_constraint(FixAtoms(indices=[0, 1]))
    with pytest.raises(PlanRefused, match="Berendsen's barostat with fixed atoms"):
        setup(structure=fixed)
    with pytest.raises(PlanRefused, match="a barostat with fixed atoms"):
        loupmd.Simulation(fixed, setup.force_field(),
                          integrator=integrators.Berendsen(**NPT, fixcm=False).to_config(seed=1))


def test_the_report_names_the_barostat():
    config = integrators.Berendsen(**NPT, mask=(1, 1, 0)).to_config(seed=1)
    import dataclasses

    line = report._physics_lines({"integrator": dataclasses.asdict(config), "schedule": None, "step": 10,
                                  "seed": 1, "counters": {"steps": 10}})[0]
    assert line.startswith("NPT, Berendsen thermostat and barostat (experimental")
    assert "pressure 0 GPa" in line and "mask (1, 1, 0)" in line and "time constants 50 fs and 20 fs" in line


def test_the_ase_drop_ins_take_ase_s_arguments_and_move_the_cell(setup):
    from loupmd.ase import md as ase_md

    atoms = setup.atoms.copy()
    start = atoms.get_volume()
    dyn = ase_md.NPTBerendsen(atoms, 1.0 * units.fs, temperature_K=300, pressure_au=1.0 * units.GPa,
                              taut=50 * units.fs, taup=20 * units.fs, compressibility_au=0.01 / units.GPa,
                              fixcm=False, model=setup.force_field())
    config = dyn.simulation.config
    assert (config.ensemble, config.scheme, config.mask, config.fixcm) == ("npt", "berendsen", None, False)
    assert (config.pressure_GPa, config.taup_fs, config.compressibility_per_GPa, config.tau_fs) == \
        (pytest.approx(1.0), pytest.approx(20.0), pytest.approx(0.01), pytest.approx(50.0))
    assert dyn.run(100) is True
    engine = SpringEngine.made[-1]
    assert np.array_equal(atoms.cell.array, engine.get_cell()) and atoms.get_volume() > 1.02 * start
    assert np.array_equal(atoms.positions, engine.pos)

    masked = ase_md.Inhomogeneous_NPTBerendsen(setup.atoms.copy(), 1.0 * units.fs, temperature_K=300,
                                               pressure_au=0.0, compressibility_au=0.01 / units.GPa,
                                               mask=(1, 0, 1), model=setup.force_field())
    config = masked.simulation.config
    assert config.mask == (1, 0, 1) and config.fixcm is True
    assert (config.tau_fs, config.taup_fs) == (pytest.approx(500.0), pytest.approx(1000.0))      # ASE's defaults
    masked.run(40)
    cell = SpringEngine.made[-1].get_cell()
    assert cell[1, 1] == setup.atoms.cell.array[1, 1] and cell[0, 0] != setup.atoms.cell.array[0, 0]

    with pytest.raises(InputError, match="NPTBerendsen needs pressure_au, compressibility_au"):
        ase_md.NPTBerendsen(atoms, units.fs, temperature_K=300, model=setup.force_field())
    with pytest.raises(InputError, match="pressure= .bar. and compressibility= .1/bar. are ASE's deprecated units"):
        ase_md.NPTBerendsen(atoms, units.fs, temperature_K=300, pressure=1.0, model=setup.force_field())


def test_lm_md_takes_a_barostat_s_record(setup, tmp_path):
    record = integrators.Berendsen(**NPT)
    result = loupmd.md(setup.atoms, model=setup.force_field(), steps=40, integrator=record,
                       output=str(tmp_path / "quick"), seed=3)
    assert result.simulation.config.ensemble == "npt" and result.metadata["arguments"]["ensemble"] == "NPT"
    assert result.metadata["arguments"]["integrator"]["pressure_GPa"] == 0.0
    assert "NPT, Berendsen thermostat and barostat (experimental" in result.summary
    header, rows = output.read_thermo(tmp_path / "quick")
    assert header == list(output.THERMO_HEADER + output.NPT_COLUMNS) and int(rows[-1][0]) == 40
    with pytest.raises(InputError, match="pressure_GPa= and cell_mode= conflict with the explicit integrator"):
        loupmd.md(setup.atoms, model=setup.force_field(), steps=40, integrator=record, pressure_GPa=1.0)


# ------------------------------------------------------------------------------------------ Langevin BAOAB NPT

def test_the_baoab_record_and_its_struct():
    record = integrators.LangevinBAOAB(timestep_fs=1.0, temperature_K=300.0, friction_per_fs=0.02, pressure_GPa=2.0)
    config = record.to_config(seed=5)
    assert (config.ensemble, config.scheme, config.cell_mode, config.taup_fs, config.fixcm, config.seed) == \
        ("npt", "baoab", "hydrostatic", None, False, 5)
    it = config.to_struct(thermo_every=4, temperature_K=250.0, rate_K_per_step=0.5)
    assert (it.kind, it.friction_per_fs, it.pressure_gpa, it.tau_p_fs, it.cell_mode, it.seed, it.fix_com) == \
        (_core.LOUP_BAOAB_NPT, 0.02, 2.0, 0.0, _core.LOUP_CELL_HYDROSTATIC, 5, 0)
    assert (it.temp_k, it.temp_rate_k_per_step, it.thermo_every) == (250.0, 0.5, 4)
    full = integrators.LangevinBAOAB(timestep_fs=1.0, temperature_K=300.0, friction_per_fs=0.02, cell_mode="full",
                                     barostat_tau_fs=800.0).to_config(seed=1).to_struct()
    assert (full.cell_mode, full.tau_p_fs, full.pressure_gpa) == (_core.LOUP_CELL_FULL, 800.0, 0.0)
    assert integrators.from_data(integrators.to_data(record)) == record and record.barostat
    assert IntegratorConfig(ensemble="npt", temperature_K=300.0, friction_per_fs=0.02, pressure_GPa=0.0).scheme == "baoab"

    base = dict(timestep_fs=1.0, temperature_K=300.0, friction_per_fs=0.02)
    for fields, error, reason in (
            (dict(external_stress_GPa=-1.0), PlanRefused, "LangevinBAOAB.external_stress_GPa=-1.0 is not in this"),
            (dict(barostat_mass_factor=2.0), PlanRefused, "LangevinBAOAB.barostat_mass_factor=2.0 is not in this"),
            (dict(disable_cell_langevin=True), PlanRefused, "LangevinBAOAB.disable_cell_langevin=True is not in"),
            (dict(max_volume_ratio=None), PlanRefused, "LangevinBAOAB.max_volume_ratio=None is not in this"),
            (dict(max_cell_length_A=50.0), PlanRefused, "LangevinBAOAB.max_cell_length_A=50.0 is not in this"),
            (dict(fixcm=True), InputError, "LangevinBAOAB.fixcm must be False"),
            (dict(friction_per_fs=0.0), InputError, "friction_per_fs must be positive and finite"),
            (dict(cell_mode="cubic"), InputError, "cell_mode must be one of"),
            (dict(barostat_tau_fs=-5.0), InputError, "taup_fs must be positive and finite"),
            (dict(pressure_GPa=float("inf")), InputError, "pressure_GPa must be finite")):
        with pytest.raises(error, match=reason):
            integrators.LangevinBAOAB(**{**base, **fields})
    for fields, reason in ((dict(mask=(1, 1, 0)), "mask is not a setting of Langevin BAOAB NPT"),
                           (dict(tau_fs=50.0), "tau_fs is not a setting of Langevin BAOAB NPT"),
                           (dict(fixcm=True), "fixcm must be False for Langevin BAOAB NPT")):
        with pytest.raises(InputError, match=reason):
            IntegratorConfig(ensemble="npt", temperature_K=300.0, friction_per_fs=0.02, pressure_GPa=0.0, **fields)
    with pytest.raises(InputError, match="cell_mode belongs to Langevin BAOAB and MTK NPT"):
        IntegratorConfig(ensemble="npt", scheme="berendsen", temperature_K=300.0, tau_fs=50.0, pressure_GPa=0.0,
                         taup_fs=20.0, compressibility_per_GPa=0.01, cell_mode="full")
    fixed = bulk("NaCl", "rocksalt", a=5.64, cubic=True)
    with pytest.raises(PlanRefused, match="LangevinBAOAB with fixed atoms"):
        record.to_config(seed=1, fixed_atoms=True)
    assert len(fixed) == 8


def test_lm_md_s_npt_is_baoab(setup, tmp_path):
    result = loupmd.md(setup.atoms, model=setup.force_field(), steps=40, timestep_fs=1.0, temperature_K=300,
                       ensemble="NPT", pressure_GPa=0.5, cell_mode="full", output=str(tmp_path / "npt"), seed=3)
    config = result.simulation.config
    assert (config.scheme, config.pressure_GPa, config.cell_mode, config.fixcm) == ("baoab", 0.5, "full", False)
    assert config.friction_per_fs == pytest.approx(0.02 * units.fs)
    arguments = result.metadata["arguments"]
    assert (arguments["ensemble"], arguments["pressure_GPa"], arguments["cell_mode"]) == ("NPT", 0.5, "full")
    assert "integrator" not in arguments
    assert "NPT, Langevin BAOAB with a Langevin-Hoover barostat (experimental)" in result.summary
    assert "pressure 0.5 GPa" in result.summary and "full cell" in result.summary
    header, rows = output.read_thermo(tmp_path / "npt")
    assert header == list(output.THERMO_HEADER + output.NPT_COLUMNS) and int(rows[-1][0]) == 40
    engine = SpringEngine.made[-1]
    assert [e for e in engine.log if isinstance(e, tuple) and e[0] == "run"][0][2] == _core.LOUP_BAOAB_NPT


def test_the_baoab_drop_in_takes_ase_s_arguments(setup):
    from loupmd.ase import md as ase_md

    atoms = setup.atoms.copy()
    dyn = ase_md.LangevinBAOAB(atoms, 2.0 * units.fs, temperature_K=350, externalstress=-1.5 * units.GPa,
                               hydrostatic=True, T_tau=80 * units.fs, P_tau=900 * units.fs,
                               model=setup.force_field())
    config = dyn.simulation.config
    assert (config.scheme, config.cell_mode, config.temperature_K) == ("baoab", "hydrostatic", 350)
    assert (config.timestep_fs, config.friction_per_fs, config.taup_fs, config.pressure_GPa) == \
        (pytest.approx(2.0), pytest.approx(1.0 / 80.0), pytest.approx(900.0), pytest.approx(1.5))
    assert dyn.run(20) is True and np.array_equal(atoms.cell.array, SpringEngine.made[-1].get_cell())
    default = ase_md.LangevinBAOAB(setup.atoms.copy(), 1.0 * units.fs, temperature_K=300, externalstress=0.0,
                                   model=setup.force_field()).simulation.config
    assert (default.cell_mode, default.taup_fs) == ("full", None)                   # ASE's defaults
    assert default.friction_per_fs == pytest.approx(1.0 / 50.0)                      # T_tau = 50 timesteps
    for options, reason in ((dict(temperature_K=None, externalstress=0.0), "without temperature_K or without"),
                            (dict(temperature_K=300), "without temperature_K or without externalstress"),
                            (dict(temperature_K=300, externalstress=[0.0, 0.0, 0.0]), "with 3 components"),
                            (dict(temperature_K=300, externalstress=0.0, P_mass=5.0), "P_mass=5.0"),
                            (dict(temperature_K=300, externalstress=0.0, disable_cell_langevin=True),
                             "disable_cell_langevin=True")):
        with pytest.raises(PlanRefused, match=reason):
            ase_md.LangevinBAOAB(setup.atoms.copy(), units.fs, model=setup.force_field(), **options)


# ------------------------------------------------------------------------------------- Martyna-Tobias-Klein NPT

def test_the_mtk_record_its_struct_and_its_drop_ins(setup, tmp_path):
    from loupmd.ase import md as ase_md

    record = integrators.MTK(timestep_fs=1.0, temperature_K=300.0, pressure_GPa=1.5, tdamp_fs=100.0, pdamp_fs=900.0)
    config = record.to_config(seed=2)
    assert (config.ensemble, config.scheme, config.tau_fs, config.taup_fs, config.cell_mode, config.fixcm) == \
        ("npt", "mtk", 100.0, 900.0, "hydrostatic", True)
    assert (config.tchain, config.pchain, config.tloop, config.ploop, config.mass_temperature_K) == (3, 3, 1, 1, 300.0)
    it = config.to_struct(thermo_every=3, temperature_K=250.0, rate_K_per_step=0.1)
    assert (it.kind, it.tau_t_fs, it.tau_p_fs, it.pressure_gpa, it.mass_temp_k, it.cell_mode, it.fix_com) == \
        (_core.LOUP_MTK_NPT, 100.0, 900.0, 1.5, 300.0, _core.LOUP_CELL_HYDROSTATIC, 1)
    assert (it.chain_length, it.chain_loops, it.p_chain_length, it.p_chain_loops) == (3, 1, 3, 1)
    assert (it.temp_k, it.temp_rate_k_per_step, it.thermo_every) == (250.0, 0.1, 3)
    full = integrators.MTK(timestep_fs=1.0, temperature_K=300.0, pressure_GPa=0.0, tdamp_fs=100.0, pdamp_fs=900.0,
                           tchain=2, pchain=4, tloop=2, ploop=3, cell_mode="full", fixcm=False)
    it = full.to_config(seed=2).to_struct()
    assert (it.cell_mode, it.chain_length, it.chain_loops, it.p_chain_length, it.p_chain_loops, it.fix_com) == \
        (_core.LOUP_CELL_FULL, 2, 2, 4, 3, 0)
    assert integrators.from_data(integrators.to_data(full)) == full and full.barostat

    base = dict(timestep_fs=1.0, temperature_K=300.0, pressure_GPa=0.0, tdamp_fs=100.0, pdamp_fs=900.0)
    for fields, reason in ((dict(pchain=9), "pchain must be an int from 1 to 8"),
                           (dict(tchain=0), "tchain must be an int from 1 to 8"),
                           (dict(ploop=101), "ploop must be an int from 1 to 100"),
                           (dict(pdamp_fs=0.0), "taup_fs must be positive and finite"),
                           (dict(temperature_K=0.0), "temperature_K must be positive and finite"),
                           (dict(cell_mode="cubic"), "cell_mode must be one of"),
                           (dict(fixcm="yes"), "MTK.fixcm must be True, False or 'auto'")):
        with pytest.raises(InputError, match=reason):
            integrators.MTK(**{**base, **fields})
    with pytest.raises(InputError, match="pchain belongs to the MTK barostat's chain"):
        IntegratorConfig(scheme="nose_hoover", temperature_K=300.0, tau_fs=100.0, pchain=3)
    with pytest.raises(PlanRefused, match="MTK with fixed atoms"):
        record.to_config(seed=1, fixed_atoms=True)

    result = loupmd.md(setup.atoms, model=setup.force_field(), steps=40, integrator=record,
                       output=str(tmp_path / "mtk"), seed=3)
    assert "NPT, Martyna-Tobias-Klein with Nose-Hoover chains of 3 and 3 (experimental)" in result.summary
    assert "time constants 100 fs and 900 fs, pressure 1.5 GPa" in result.summary
    assert output.read_thermo(tmp_path / "mtk")[0] == list(output.THERMO_HEADER + output.NPT_COLUMNS)

    atoms = setup.atoms.copy()
    dyn = ase_md.IsotropicMTKNPT(atoms, 2.0 * units.fs, 350.0, 0.5 * units.GPa, 80 * units.fs, 700 * units.fs,
                                 model=setup.force_field())
    config = dyn.simulation.config
    assert (config.scheme, config.cell_mode, config.fixcm, config.temperature_K) == ("mtk", "hydrostatic", False, 350.0)
    assert (config.timestep_fs, config.tau_fs, config.taup_fs, config.pressure_GPa) == \
        (pytest.approx(2.0), pytest.approx(80.0), pytest.approx(700.0), pytest.approx(0.5))
    assert dyn.run(20) is True and np.array_equal(atoms.cell.array, SpringEngine.made[-1].get_cell())
    full_dyn = ase_md.MTKNPT(setup.atoms.copy(), units.fs, temperature_K=300.0, pressure_au=0.0, tdamp=100 * units.fs,
                             pdamp=1000 * units.fs, tchain=2, pchain=2, model=setup.force_field())
    assert (full_dyn.simulation.config.cell_mode, full_dyn.simulation.config.pchain) == ("full", 2)



# ------------------------------------------------------------------------------- command line and run files

def test_npt_on_the_command_line_and_from_its_metadata(setup, tmp_path, monkeypatch, capsys):
    """``loupmd md --ensemble NPT --pressure`` is Langevin BAOAB; the run's ``metadata.json`` repeats it."""
    import json

    from ase.io import write

    from loupmd import quick, simulation
    from loupmd.cli import main

    write(tmp_path / "salt.cif", bulk("NaCl", "rocksalt", a=5.64, cubic=True))
    monkeypatch.setattr(quick, "load", lambda model, head=None, **options: setup.force_field())
    monkeypatch.setattr(simulation, "load", lambda model, head=None, **options: setup.force_field())
    monkeypatch.chdir(tmp_path)
    base = ["salt.cif", "--model", "some.model", "--trusted", "--temperature", "300", "--steps", "40", "--timestep",
            "1", "--seed", "3", "--initial-velocities", "maxwell_boltzmann", "--repeat", "2", "2", "2"]

    assert main(["md", *base, "--ensemble", "NPT", "--pressure", "0.5", "--cell-mode", "full", "--output", "a"]) == 0
    assert "NPT, Langevin BAOAB with a Langevin-Hoover barostat (experimental)" in capsys.readouterr().out
    metadata = json.loads((tmp_path / "a" / "metadata.json").read_text())
    arguments = metadata["arguments"]
    assert (arguments["ensemble"], arguments["pressure_GPa"], arguments["cell_mode"]) == ("NPT", 0.5, "full")
    arguments["output"]["directory"] = "b"
    (tmp_path / "again.json").write_text(json.dumps(metadata))
    assert main(["run", "again.json"]) == 0
    assert output.read_thermo(tmp_path / "a")[1] == output.read_thermo(tmp_path / "b")[1]
    assert output.read_thermo(tmp_path / "b")[0] == list(output.THERMO_HEADER + output.NPT_COLUMNS)

    assert main(["md", *base, "--ensemble", "NPT", "--pressure", "0.5", "--friction", "0.05", "--output", "c"]) == 0
    assert "friction 0.05/fs, pressure 0.5 GPa" in capsys.readouterr().out
    record = json.loads((tmp_path / "c" / "metadata.json").read_text())["arguments"]["integrator"]
    assert (record["type"], record["friction_per_fs"], record["pressure_GPa"]) == ("LangevinBAOAB", 0.05, 0.5)

    assert main(["md", *base, "--pressure", "0.5", "--output", "d"]) == 1
    assert "belong to ensemble='NPT'" in capsys.readouterr().err
    assert not (tmp_path / "d").exists()


def test_an_npt_profile_runs_at_its_pressure(setup, tmp_path, monkeypatch, capsys):
    """Owner's decision O23: ``loupmd md --profile`` with a profile at constant pressure is Langevin BAOAB at the
    profile's pressure, and ``--friction`` keeps both."""
    import json

    from ase.io import write

    from loupmd import quick, simulation
    from loupmd.cli import main

    write(tmp_path / "salt.cif", bulk("NaCl", "rocksalt", a=5.64, cubic=True))
    (tmp_path / "press.toml").write_text(
        'name = "press"\nensemble = "NPT"\npressure_GPa = 0.5\nsample_interval = 10\ntrajectory_interval = 20\n'
        '[[segments]]\nkind = "hold"\ntemperature_K = 300\nps = 0.04\n')
    monkeypatch.setattr(quick, "load", lambda model, head=None, **options: setup.force_field())
    monkeypatch.setattr(simulation, "load", lambda model, head=None, **options: setup.force_field())
    monkeypatch.chdir(tmp_path)
    base = ["salt.cif", "--model", "some.model", "--trusted", "--timestep", "1", "--seed", "3",
            "--initial-velocities", "maxwell_boltzmann", "--repeat", "2", "2", "2", "--profile", "press.toml"]

    assert main(["md", *base, "--output", "a"]) == 0
    out = capsys.readouterr().out
    assert "NPT, Langevin BAOAB with a Langevin-Hoover barostat (experimental)" in out and "pressure 0.5 GPa" in out
    arguments = json.loads((tmp_path / "a" / "metadata.json").read_text())["arguments"]
    assert (arguments["ensemble"], arguments["pressure_GPa"], arguments["cell_mode"]) == ("NPT", 0.5, "hydrostatic")
    header, rows = output.read_thermo(tmp_path / "a")
    assert header[:len(output.THERMO_HEADER) + len(output.NPT_COLUMNS)] == list(output.THERMO_HEADER
                                                                                 + output.NPT_COLUMNS)
    assert [int(row[0]) for row in rows] == [0, 10, 20, 30, 40]
    engine = SpringEngine.made[-1]
    assert [e for e in engine.log if isinstance(e, tuple) and e[0] == "run"][0][2] == _core.LOUP_BAOAB_NPT

    assert main(["md", *base, "--friction", "0.05", "--cell-mode", "full", "--output", "b"]) == 0
    assert "friction 0.05/fs, pressure 0.5 GPa" in capsys.readouterr().out
    record = json.loads((tmp_path / "b" / "metadata.json").read_text())["arguments"]["integrator"]
    assert (record["type"], record["friction_per_fs"], record["pressure_GPa"], record["cell_mode"]) == (
        "LangevinBAOAB", 0.05, 0.5, "full")

    assert main(["md", *base, "--pressure", "1.5", "--output", "c"]) == 0
    assert "pressure 1.5 GPa" in capsys.readouterr().out

    assert main(["md", *base, "--ensemble", "NVE", "--output", "d"]) == 1
    assert "profile 'press' runs NPT, the run file asks for ensemble='NVE'" in capsys.readouterr().err
    assert not (tmp_path / "d").exists()

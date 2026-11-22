"""Monte Carlo moves between MD steps (plan tasks S6-T02 to S6-T04): ``lm.mc.Swap``, ``Transmute`` and
``Displace``, as blocks between two ``run`` calls (``lm.mc.swap`` and the others) or every few steps of a run
(``Simulation.run(mc=...)``).

A swap exchanges the species at two sites: one atom of each species of a pair is chosen uniformly, the trial
energy comes from the engine's energy-only pass (``LOUP_EVAL_ENERGY_ONLY``), and the Metropolis rule is applied on
the host. LoupMD makes the exchange by moving the two atoms: they swap positions and velocities (FastMACE's
``velocities="exchange"``), so every atom keeps its index, element and mass and the engine needs no new setup
(PLAN.md D72). The configuration is the one a species swap gives; only the atoms' labels differ.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from .errors import InputError, PlanRefused

SWAP_VELOCITIES = ("exchange",)


def species_number(species) -> int:
    """An atomic number from a symbol or an atomic number."""
    from ase.data import atomic_numbers

    if isinstance(species, str):
        if species not in atomic_numbers:
            raise InputError(f"unknown chemical symbol {species!r}")
        return int(atomic_numbers[species])
    if isinstance(species, bool) or not isinstance(species, int) or species < 1:
        raise InputError(f"a species is an element symbol or an atomic number, got {species!r}")
    return int(species)


def _count(value, where):
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise InputError(f"{where} must be a positive whole number, got {value!r}")
    return value


@dataclass(frozen=True)
class Swap:
    """Swap the species of two atoms: a pair type uniformly from ``pairs``, then one atom of each species
    uniformly. ``every`` MD steps, then ``attempts`` attempts (``Simulation.run(mc=...)``). ``velocities``:
    ``"exchange"`` (the two atoms swap velocities, as FastMACE's default), the only one in LoupMD."""

    pairs: tuple
    every: int = 1
    attempts: int = 1
    velocities: str = "exchange"

    def __post_init__(self):
        if isinstance(self.pairs, (str, bytes)):
            raise InputError(f"Swap.pairs must be pairs of species, got {self.pairs!r}")
        try:
            pairs = tuple(tuple(pair) for pair in self.pairs)
        except TypeError:
            raise InputError(f"Swap.pairs must be pairs of species, got {self.pairs!r}") from None
        if not pairs:
            raise InputError("Swap.pairs needs at least one pair")
        numbers = []
        for pair in pairs:
            if len(pair) != 2:
                raise InputError(f"Swap.pairs: each pair names two species, got {pair!r}")
            first, second = (species_number(item) for item in pair)
            if first == second:
                raise InputError(f"Swap.pairs: a pair needs two different species, got {pair!r}")
            numbers.append((first, second))
        object.__setattr__(self, "pairs", tuple(numbers))
        _count(self.every, "Swap.every")
        _count(self.attempts, "Swap.attempts")
        if self.velocities not in SWAP_VELOCITIES:
            raise PlanRefused(f"Swap(velocities={self.velocities!r})",
                              why="LoupMD swaps two atoms by exchanging their positions and velocities, which is "
                                  "FastMACE's 'exchange'; 'rescale' and 'redraw' are not in this version",
                              next_step="Use velocities='exchange' (the default).")


@dataclass(frozen=True)
class Transmute:
    """Change one atom's element within the set ``species`` (semi-grand canonical): an atom of the set uniformly,
    then another element of the set uniformly; accepted with min(1, exp(-(dE - dmu) / kT)), where dmu is the
    difference of the configurational chemical potentials ``mu`` (eV, by species; absent species have 0; FastMACE's
    ``configurational_mu`` converts full ones). The atom takes the new element's standard mass; ``velocities``
    ``"rescale"`` keeps its kinetic energy, the only treatment in LoupMD. Every attempt sets the engine's system
    for the trial composition (PLAN.md D72: the re-setup cost is in ``Counters.setup_s``)."""

    species: tuple
    every: int = 1
    attempts: int = 1
    velocities: str = "rescale"
    mu: object = None

    def __post_init__(self):
        if isinstance(self.species, (str, bytes)):
            raise InputError(f"Transmute.species must be a set of species, got {self.species!r}")
        try:
            species = tuple(species_number(item) for item in self.species)
        except TypeError:
            raise InputError(f"Transmute.species must be a set of species, got {self.species!r}") from None
        if len(species) < 2 or len(set(species)) != len(species):
            raise InputError(f"Transmute.species needs at least two different species, got {self.species!r}")
        object.__setattr__(self, "species", species)
        _count(self.every, "Transmute.every")
        _count(self.attempts, "Transmute.attempts")
        if self.velocities != "rescale":
            raise PlanRefused(f"Transmute(velocities={self.velocities!r})",
                              why="LoupMD rescales the transmuted atom's velocity to keep its kinetic energy; "
                                  "'redraw' and 'redraw_all' are not in this version",
                              next_step="Use velocities='rescale' (the default).")
        mu = {}
        for key, value in dict(self.mu or {}).items():
            number = species_number(key)
            if number not in species:
                raise InputError(f"Transmute.mu names {key!r}, which is not in Transmute.species")
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise InputError(f"Transmute.mu[{key!r}] must be a finite number of eV, got {value!r}")
            mu[number] = float(value)
        object.__setattr__(self, "mu", tuple(sorted(mu.items())))

    def mu_of(self, number) -> float:
        return dict(self.mu).get(int(number), 0.0)


@dataclass(frozen=True)
class Displace:
    """Displace one atom (uniformly chosen among those not fixed) uniformly within a sphere of radius ``delta_A``;
    accepted with min(1, exp(-dE / kT)). A fixed step keeps the chain's detailed balance; FastMACE's adaptive step
    is not in this version."""

    delta_A: float
    every: int = 1
    attempts: int = 1
    adaptive: bool = False

    def __post_init__(self):
        if isinstance(self.delta_A, bool) or not isinstance(self.delta_A, (int, float)) or not (
                math.isfinite(self.delta_A) and self.delta_A > 0):
            raise InputError(f"Displace.delta_A must be positive and finite, got {self.delta_A!r}")
        object.__setattr__(self, "delta_A", float(self.delta_A))
        _count(self.every, "Displace.every")
        _count(self.attempts, "Displace.attempts")
        if self.adaptive is not False:
            raise PlanRefused("Displace(adaptive=True)",
                              why="an adapted step breaks detailed balance while it moves; LoupMD keeps the step "
                                  "fixed",
                              next_step="Choose delta_A from a short trial (about 30 % acceptance is usual).")


MOVES = ("swap", "transmute", "displace")


def kind(move) -> str:
    """``"swap"``, ``"transmute"`` or ``"displace"``."""
    if isinstance(move, Swap):
        return "swap"
    if isinstance(move, Transmute):
        return "transmute"
    if isinstance(move, Displace):
        return "displace"
    raise InputError(f"a Monte Carlo move is an lm.mc.Swap, Transmute or Displace, got {type(move).__name__}")


def record(move) -> dict:
    """The move as JSON: its kind and fields."""
    import dataclasses

    return {"move": kind(move), **{f.name: _plain(getattr(move, f.name)) for f in dataclasses.fields(move)}}


def from_record(data):
    """The move a ``record`` describes (a move passes through unchanged)."""
    if isinstance(data, (Swap, Transmute, Displace)):
        return data
    if not isinstance(data, dict) or data.get("move") not in MOVES:
        raise InputError(f"a Monte Carlo move record names its move ({', '.join(MOVES)}), got {data!r}")
    fields = {k: v for k, v in data.items() if k != "move"}
    if data["move"] == "transmute" and isinstance(fields.get("mu"), list):
        fields["mu"] = {int(k): float(v) for k, v in fields["mu"]}
    cls = {"swap": Swap, "transmute": Transmute, "displace": Displace}[data["move"]]
    try:
        return cls(**fields)
    except TypeError as error:
        raise InputError(f"a {data['move']} record has fields {sorted(fields)}: {error}") from None


def _plain(value):
    if isinstance(value, tuple):
        return [_plain(v) for v in value]
    return value


@dataclass
class Counters:
    """Attempted and accepted moves of one kind; ``rejected_nonfinite`` counts trial energies that were not
    finite (rejected, never patched)."""

    attempted: int = 0
    accepted: int = 0
    rejected_nonfinite: int = 0
    setup_s: float = 0.0          # transmute: time spent setting the engine's system for trial compositions

    @property
    def acceptance(self) -> float:
        return self.accepted / self.attempted if self.attempted else float("nan")

    def add(self, other: "Counters"):
        self.attempted += other.attempted
        self.accepted += other.accepted
        self.rejected_nonfinite += other.rejected_nonfinite
        self.setup_s += other.setup_s

    def as_dict(self) -> dict:
        return {"attempted": self.attempted, "accepted": self.accepted,
                "rejected_nonfinite": self.rejected_nonfinite, "setup_s": self.setup_s}


def _energy(engine, positions, cell) -> float:
    evaluate_energy = getattr(engine, "evaluate_energy", None)
    if evaluate_energy is not None:
        return float(evaluate_energy(positions, cell))
    return float(engine.evaluate(positions, cell, compute_stress=False)[0])


def swap_block(engine, move: Swap, positions, velocities, numbers, cell, energy: float, kT: float, rng,
               attempts: int | None = None):
    """``attempts`` (default ``move.attempts``) swap attempts from the state ``positions``, ``velocities`` of
    energy ``energy`` (eV); ``kT`` in eV; ``rng`` a ``numpy.random.Generator``. Returns ``(positions,
    velocities, energy, Counters)`` of the chain's last state; the arrays are new. The engine's device positions
    are those of the last trial afterwards: the caller sets the state it keeps."""
    import numpy as np

    if not (kT > 0 and math.isfinite(kT)):
        raise InputError(f"a swap needs a positive temperature, got kT = {kT!r} eV")
    positions = np.array(positions, dtype=float)
    velocities = np.array(velocities, dtype=float)
    numbers = np.asarray(numbers)
    sites = {}
    for a, b in move.pairs:
        sites[a] = np.flatnonzero(numbers == a)
        sites[b] = np.flatnonzero(numbers == b)
    usable = [pair for pair in move.pairs if len(sites[pair[0]]) and len(sites[pair[1]])]
    if not usable:
        raise InputError(f"no pair of Swap.pairs {move.pairs} has an atom of each species in the structure")
    counters = Counters()
    for _ in range(move.attempts if attempts is None else attempts):
        a, b = usable[rng.integers(len(usable))]
        i, j = int(rng.choice(sites[a])), int(rng.choice(sites[b]))
        trial = positions.copy()
        trial[[i, j]] = positions[[j, i]]
        trial_energy = _energy(engine, trial, cell)
        counters.attempted += 1
        if not math.isfinite(trial_energy):
            counters.rejected_nonfinite += 1
            continue
        excess = trial_energy - energy
        if excess <= 0.0 or rng.random() < math.exp(-excess / kT):
            positions = trial
            velocities[[i, j]] = velocities[[j, i]]
            energy = trial_energy
            counters.accepted += 1
    return positions, velocities, energy, counters


def displace_block(engine, move: Displace, positions, movable, cell, energy: float, kT: float, rng,
                   attempts: int | None = None):
    """``attempts`` (default ``move.attempts``) displace attempts from ``positions`` of energy ``energy``;
    ``movable`` the indices that may move. Returns ``(positions, energy, Counters)``; the engine's device
    positions are those of the last trial afterwards."""
    import numpy as np

    if not (kT > 0 and math.isfinite(kT)):
        raise InputError(f"a displace move needs a positive temperature, got kT = {kT!r} eV")
    positions = np.array(positions, dtype=float)
    movable = np.asarray(movable)
    if not len(movable):
        raise InputError("no atom may move: every atom is fixed")
    counters = Counters()
    for _ in range(move.attempts if attempts is None else attempts):
        i = int(rng.choice(movable))
        while True:                                       # uniform in the ball: rejection from the cube
            step = rng.uniform(-1.0, 1.0, 3)
            if step @ step <= 1.0:
                break
        trial = positions.copy()
        trial[i] += move.delta_A * step
        trial_energy = _energy(engine, trial, cell)
        counters.attempted += 1
        if not math.isfinite(trial_energy):
            counters.rejected_nonfinite += 1
            continue
        excess = trial_energy - energy
        if excess <= 0.0 or rng.random() < math.exp(-excess / kT):
            positions, energy = trial, trial_energy
            counters.accepted += 1
    return positions, energy, counters


@dataclass(frozen=True)
class SwapResult:
    """What a block of moves did (``swap``, ``transmute``, ``displace``): the counters and the potential energy
    after the block (eV)."""

    counters: Counters
    energy_eV: float


def swap(simulation, move: Swap, *, temperature_K=None, seed=None, attempts=None) -> SwapResult:
    """``move.attempts`` (or ``attempts``) swap attempts on a ``Simulation`` between two ``run`` calls, at
    ``temperature_K`` (default: the thermostat's). The kept state is set on the engine once, so its step count
    restarts as after any event (``Simulation.update``)."""
    if not isinstance(move, Swap):
        raise InputError(f"move must be an lm.mc.Swap, got {type(move).__name__}")
    return _block(simulation, move, temperature_K, seed, attempts)


def transmute(simulation, move: Transmute, *, temperature_K=None, seed=None, attempts=None) -> SwapResult:
    """``move.attempts`` (or ``attempts``) transmute attempts on a ``Simulation`` between two ``run`` calls, at
    ``temperature_K`` (default: the thermostat's). Elements the structure does not have yet must be in the run's
    bundle: ``lm.Simulation(..., elements=[...])``."""
    if not isinstance(move, Transmute):
        raise InputError(f"move must be an lm.mc.Transmute, got {type(move).__name__}")
    return _block(simulation, move, temperature_K, seed, attempts)


def displace(simulation, move: Displace, *, temperature_K=None, seed=None, attempts=None) -> SwapResult:
    """``move.attempts`` (or ``attempts``) displace attempts on a ``Simulation`` between two ``run`` calls, at
    ``temperature_K`` (default: the thermostat's)."""
    if not isinstance(move, Displace):
        raise InputError(f"move must be an lm.mc.Displace, got {type(move).__name__}")
    return _block(simulation, move, temperature_K, seed, attempts)


def _block(simulation, move, temperature_K, seed, attempts):
    import numpy as np
    from ase import units

    temperature = temperature_K if temperature_K is not None else simulation.config.temperature_K
    if temperature is None:
        raise InputError("a swap needs a temperature: the integrator has none", next_step="Pass temperature_K=.")
    rng = np.random.default_rng(seed)
    return simulation._mc_block(move, float(temperature) * units.kB, rng, attempts)

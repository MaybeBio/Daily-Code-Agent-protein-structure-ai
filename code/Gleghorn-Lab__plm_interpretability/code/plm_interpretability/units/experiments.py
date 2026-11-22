"""The preregistered passes: for E2 to E5 and the SAE sweep, which model, which bases at which blocks, under which
reference SAE's rates, and over which proteins (preregistration, `bases`, `hypotheses` and `budget`).

SAEs are named by the preregistration's `saes` keys; the members of ESMC-600's layer-27 sweep are named
`esmc_600_layer27_k{k}_{codebook}`, and their revisions are pinned at E0 (the script's `pin-sweep` stage). A residual SAE of layer L reads
the stream block L - 1 outputs; an MLP-output SAE's shard index is taken to be its block's, which E0's reconstruction
check confirms before any pass (`scripts/units_atlas.py parity`).

Rate references: ESMC-600 is matched at block 26 to its size-matched SAE (8,192 latents for 6,144 poles) for H1 to H6
and the depth atlas, and to the 16,384-latent SAE for the comparison across scale (H7), which every model has at its
75% block, so H7 compares three models at one rate distribution.
"""

from __future__ import annotations

import pandas as pd

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from .atlas import PlannedBasis
from .bases import Basis
from .concepts import DEPTHS, ExtractionPlan
from .rotation_search import SEARCH_SEEDS


ROTATION_SEEDS = tuple(range(10))
MODEL_NAMES = {"esmc_300": "ESMC-300", "esmc_600": "ESMC-600", "esmc_6b": "ESMC-6B", "esm2_8m": "ESM2-8M",
               "esm2_650m": "ESM2-650M"}  # as figures and tables name the models; ESM2, never ESM-2 (Logan, 2026-11-18)
# The sites where H1 to H3 and H5 compare bases: each model's pass, block and reference SAE (`sweep_name(64, 8192)`
# for ESMC-600), and the randomly initialized pass that is each trained pass's control.
HYPOTHESIS_SITES = {"esmc_600": ("e2", 26, "esmc_600_layer27_k64_8192"), "esmc_6b": ("e3", 59, "esmc_6b_layer60_k64_16384")}
RANDOM_INIT_PASSES = {"e2": "e5_600", "e3": "e5_6b"}
# H7's sites: each model's 75% block read at the rates of its 16,384-latent SAE, smallest model first.
SCALE_SITES = (("esmc_300", "e4", "block22/native@esmc_300_layer23_k64_16384"),
               ("esmc_600", "e2", "block26/native@esmc_600_layer27_k64_16384"),
               ("esmc_6b", "e3", "block59/native@esmc_6b_layer60_k64_16384"))
SWEEP_K = (16, 32, 64, 128, 256, 512)
SWEEP_CODEBOOKS = (8192, 16384, 32768, 65536, 131072)
SWEEP_PASS_K = (16, 64, 256)  # the sweep pass reads a 3 x 3 subgrid of the 30 members, spanning their range
SWEEP_PASS_CODEBOOKS = (8192, 32768, 131072)
BLOCKS = {"esmc_300": 30, "esmc_600": 36, "esmc_6b": 80}
CAUSAL_MODEL, CAUSAL_BLOCK = "esmc_600", 26  # E7 ablates the poles E2 labels at block 26 under the size-matched SAE's rates
CAUSAL_BUDGET_HOURS = 0.7
STEERING_BUDGET_HOURS = 0.15  # E7d: 2,700 steered passes of 64 proteins of at most 510 residues, after the calibration fit
PAYOFF_BUDGET_HOURS = {"esmc_600": 0.1, "esmc_6b": 0.2}  # E11's XGBoost fits; ESMC-6B's fingerprints are about twice as wide
PANEL_BUDGET_HOURS = {"esmc_600": 0.05, "esmc_6b": 0.12}  # E10's taxonomy panel, 12,000 atlas proteins (about 4.9 million residues)
RETEST_BUDGET_HOURS = {"esm2_8m": 0.1, "esm2_650m": 0.3}  # E1: two passes of both copies over about 16 million residues
# E14, exploratory, added on 2026-11-10 after Goodfire's neuron study (Tigges et al.), its readings fixed in the launch
# record before it ran. E14a's firing-strength bands at each model's three-quarter block: the block, the padded tokens a
# batch and GH200 hours, a sample pass and one counting pass of E1's set. E14c's fits at E8's sites, in GH200 hours.
STRENGTH_SITES = {"esmc_300": (22, 32_768, 0.15), "esmc_600": (26, 32_768, 0.2), "esmc_6b": (59, 16_384, 0.5)}
COALITION_BUDGET_HOURS = {"esmc_600": 0.15, "esmc_6b": 0.4}
# E15, exploratory, added on 2026-11-17 after three reports from Goodfire, on ESMC-600 alone: hours of one GH200 for
# each stage, inside the eight Logan gave that day. The attribution pass and the community tests stop at their
# budgets and keep what they finished; `--budget-hours` overrides either.
E15_BUDGET_HOURS = {"neuron-attribution": 1.25, "communities": 0.3, "community-tests": 3.0, "sparsify": 0.75,
                    "concept-groups": 0.6, "erasure-levels": 0.6, "write-sums": 0.2}
E15_TOKEN_BUDGET = {"neuron-attribution": 24_576,"community-tests": 32_768, "sparsify": 32_768, "erasure-levels": 32_768}
E15_HELD_OUT_PROTEINS = 2_500  # test proteins whose prompts the community tests draw from
E15_PILOT_PROTEINS = 24  # proteins of median length on which the summed attribution is set against a single prompt's
E15_SUMMED_OVERLAP = 0.9  # the mean Jaccard index at or above which the pass differentiates a batch's prompts together
E15_HELD_OUT_TARGETS = 16  # prompts of each held-out protein, when the pass differentiates one prompt a protein
E15_DISCOVERY_TARGETS = 48  # at most this many prompts of each discovery protein; the budget ends the pass sooner
# E15c's folder of the run for each score that ranks a prompt's units (`plm_interpretability.units.communities.SCORES`).
E15_DICTIONARY_FOLDERS = {"attribution": "communities", "activation": "communities_activation"}
# E16, exploratory, added on 2026-11-18: ESMC-600 with a fixed set of units a block at ESMC-300's size, against ESMC-300
# (`plm_interpretability.units.pruning`), on the GH200 Logan named that day.
E16_MODEL = "esmc_600"
E16_REFERENCE = "esmc_300"
E16_BUDGET_HOURS = {"prune-static": 0.5, "prune-probes": 1.5}
E16_TOKEN_BUDGET = 32_768


@dataclass(frozen=True)
class EsmcRetestPlan:
    """E13 on one ESMC model: InterPLM's evaluation (E1) at the plan's blocks, each SAE at the block its spec reads.

    Exploratory, added on 2026-11-07 after H0 to H7 were decided, when every basis's protein-level scores sat at a
    ceiling; its rules are in the experiment's launch record, written before it ran. The two models' four depths
    decide E13; the further plans (E13x: ESMC-300, every ESMC-600 block, ESMC-6B's every fourth, ten rotations, the
    feed-forward-write SAEs and the all-layer stream SAEs) were added the same night, after E13 on ESMC-600 had run,
    and are read descriptively, as are E13s's two (E8's sparsest rotations at the hypothesis blocks), added the next
    morning after every E13x plan had run.
    """

    model: str
    blocks: tuple[int, ...]
    saes: tuple[str, ...]  # each read at its spec's block, from the stream or the feed-forward write as the spec says
    token_budget: int  # padded tokens a batch, smaller where the arms are widest
    shuffled: bool  # InterPLM's randomized control, a permuted copy read beside the model
    budget_hours: float
    arms: tuple[str, ...] | None = None  # the arms kept beside the SAEs' (`retest.esmc_arm_values`); None keeps all
    rotation_seeds: tuple[int, ...] | None = None  # None: E1's three
    searched: bool = False  # E13s: E8's search re-run at the plan's one block, its bases read (`retest.SearchedBases`)


# E13x's all-layer stream SAEs, outside the preregistration: Biohub's one 16,384-latent, k 64 family per model, a
# shard per layer, read at the revisions current on 2026-11-07. Their layer-27 and layer-60 shards differ from the
# layer-specific repositories the hypothesis sites read (other weights), so each family is compared only with itself
# across depth.
DEPTH_SAE_FAMILIES = {"esmc_600": ("biohub/ESMC-600M-sae-k64-codebook16384", "8e903f96b76d6856041f4e8bcacb3c58a9c4da60"),
                      "esmc_6b": ("biohub/ESMC-6B-sae-k64-codebook16384", "acae3680d7559b0ddb71972b551dabd0842680cb")}


def depth_sae_name(model: str, block: int) -> str:
    """The run's name for an all-layer family's SAE on the stream `block` outputs (its shard `block + 1`)."""
    return f"{model}_all_layer{block + 1}_k64_16384"


def depth_sae_specs() -> dict[str, SaeSpec]:
    """Every block's all-layer SAE of each family in `DEPTH_SAE_FAMILIES`, shard L read on the stream block L - 1
    outputs, as E0 found for the layer-specific families; `units_atlas.py retest-esmc` checks the family's position
    from its reconstruction losses before a plan reads it."""
    return {depth_sae_name(model, block): SaeSpec(depth_sae_name(model, block), repo, revision, block + 1, block, "stream")
            for model, (repo, revision) in DEPTH_SAE_FAMILIES.items() for block in range(BLOCKS[model])}


def esmc_retest_plans() -> dict[str, EsmcRetestPlan]:
    """E13's plans by name: per model the concept depths and the stream SAEs the hypothesis sites compare, then E13x's.

    Budgets scale E1's rates (ESM-2 650M, two passes of both copies, about 45 min alone) by each model's forward cost
    and, for E13x, ESMC-600's E13 run (14 min 47 s for about 186,000 features at four blocks) by the features counted:
    ESMC-300's four depths count about 151,000, ESMC-600's 36 blocks about 705,000, the 131,072-latent
    feed-forward-write SAEs about 152,000 (ESMC-600) and 175,000 (ESMC-6B, whose forward dominates), the ten rotations
    about 75,000 (ESMC-600) and 168,000 (ESMC-6B), each half of ESMC-6B's every fourth block about 440,000, and the
    all-layer SAEs with the stream about 631,000 (ESMC-600) and 379,000 (ESMC-6B). Counts take 52 KB a feature on the
    GPU, so ESMC-6B's twenty blocks run as two plans. E13s's budgets cover the counting, about 63,000 (ESMC-600) and
    141,000 (ESMC-6B) features; E8's pass and search before it took 6 and 19 minutes."""
    depth_arms = ("residual", "mlp_native", "mlp_poles", "mlp_rotation0")
    rotation_arms = ("residual", "mlp_native", "mlp_poles", *(f"mlp_rotation{seed}" for seed in ROTATION_SEEDS))
    search_arms = (*depth_arms, "mlp_standard", *(f"mlp_{kind}{seed}" for kind in ("start", "searched") for seed in SEARCH_SEEDS))
    sites = dictionary_sites()  # E8's, whose search E13s re-runs
    every_fourth = tuple(range(3, BLOCKS["esmc_6b"], 4))  # 3 to 79, the concept depths among them
    every_block = tuple(range(BLOCKS["esmc_600"]))
    return {
        "esmc_600": EsmcRetestPlan("esmc_600", DEPTHS["esmc_600"], (sweep_name(64, 8192), sweep_name(64, 16384)), 32_768,
                                   True, 0.8),
        "esmc_6b": EsmcRetestPlan("esmc_6b", DEPTHS["esmc_6b"], ("esmc_6b_layer60_k64_16384", "esmc_6b_layer60_k64_65536"),
                                  16_384, False, 2.0),
        "esmc_300": EsmcRetestPlan("esmc_300", (7, 14, 22, 29), ("esmc_300_layer23_k64_16384",), 32_768, True, 0.5),
        "esmc_600_mlp": EsmcRetestPlan("esmc_600", (26,), ("esmc_600_mlp_k64_131072",), 16_384, False, 0.5, arms=depth_arms,
                                       rotation_seeds=(0,)),
        "esmc_6b_mlp": EsmcRetestPlan("esmc_6b", (59,), ("esmc_6b_mlp_k64_131072",), 8_192, False, 1.0, arms=depth_arms,
                                      rotation_seeds=(0,)),
        "esmc_600_depth": EsmcRetestPlan("esmc_600", every_block, (), 16_384, False, 1.5, arms=depth_arms, rotation_seeds=(0,)),
        "esmc_600_rotations": EsmcRetestPlan("esmc_600", (26,), (), 32_768, False, 0.4, arms=rotation_arms,
                                             rotation_seeds=ROTATION_SEEDS),
        "esmc_6b_rotations": EsmcRetestPlan("esmc_6b", (59,), (), 16_384, False, 0.8, arms=rotation_arms,
                                            rotation_seeds=ROTATION_SEEDS),
        "esmc_6b_depth_a": EsmcRetestPlan("esmc_6b", every_fourth[:10], (), 16_384, False, 1.2, arms=depth_arms,
                                          rotation_seeds=(0,)),
        "esmc_6b_depth_b": EsmcRetestPlan("esmc_6b", every_fourth[10:], (), 16_384, False, 1.2, arms=depth_arms,
                                          rotation_seeds=(0,)),
        "esmc_600_depth_sae": EsmcRetestPlan("esmc_600", every_block, tuple(depth_sae_name("esmc_600", block) for block in every_block),
                                             16_384, False, 1.5, arms=("residual",), rotation_seeds=()),
        "esmc_6b_depth_sae": EsmcRetestPlan("esmc_6b", every_fourth, tuple(depth_sae_name("esmc_6b", block) for block in every_fourth),
                                            16_384, False, 1.5, arms=("residual",), rotation_seeds=()),
        "esmc_600_search": EsmcRetestPlan("esmc_600", (sites["esmc_600"].block,), (), 32_768, False, 0.4, arms=search_arms,
                                          rotation_seeds=(0,), searched=True),
        "esmc_6b_search": EsmcRetestPlan("esmc_6b", (sites["esmc_6b"].block,), (), 16_384, False, 0.8, arms=search_arms,
                                         rotation_seeds=(0,), searched=True),
    }


@dataclass(frozen=True)
class DictionarySite:
    """E8 at one block: the MLP-output SAE on its feed-forward write and the residual SAEs on its output stream.

    The budget is dominated by the rotation search: three seeds of up to 300 steps, each step three float64 products of
    the 200,000-residue sample with an f-by-f rotation, about 0.35 s at f = 3,072 and 1.7 s at f = 6,912 on a GH200 at
    half its float64 peak.
    """

    model: str
    block: int
    saes: tuple[str, ...]
    budget_hours: float
    cofiring: bool = False  # also correlate the native poles with one another, for E10's co-firing blocks


def concept_plans() -> dict[str, tuple[ExtractionPlan, float]]:
    """The concept extraction of each model behind E6, E9, E10 and E11, with its GH200 budget in hours. ESMC-600 keeps
    every block's mean product for E9's decomposition; each model max-pools the SAE it is compared with at 75% depth.

    The protein-level tasks hold 31,169 distinct proteins and 12,116,164 residues at the pinned revision (counted
    2026-11-06; no sequence exceeds 1,023 residues): about 4.5 minutes through ESMC-600 and 13 through ESMC-6B at the
    atlas study's rates, plus about 4 minutes of float32 rotations at ESMC-6B's rotation block.
    """
    return {
        "esmc_600": (ExtractionPlan(DEPTHS["esmc_600"], rotation_block=26, rotation_seeds=ROTATION_SEEDS, sae=sweep_name(64, 8192),
                                    sae_block=26, all_blocks=True), 0.1),
        "esmc_6b": (ExtractionPlan(DEPTHS["esmc_6b"], rotation_block=59, rotation_seeds=ROTATION_SEEDS,
                                   sae="esmc_6b_layer60_k64_16384", sae_block=59), 0.3),
    }


def dictionary_sites() -> dict[str, DictionarySite]:
    """The two E8 sites, ESMC-600 block 26 and ESMC-6B block 59, by model."""
    return {
        "esmc_600": DictionarySite("esmc_600", 26, ("esmc_600_mlp_k64_131072", sweep_name(64, 8192), sweep_name(64, 16384)),
                                   0.15, cofiring=True),
        "esmc_6b": DictionarySite("esmc_6b", 59, ("esmc_6b_mlp_k64_131072", "esmc_6b_layer60_k64_16384",
                                                  "esmc_6b_layer60_k64_65536"), 0.5),
    }


@dataclass(frozen=True)
class SaeSpec:
    name: str
    repo: str
    revision: str | None  # None until pinned at E0
    layer: int  # the shard of the repository
    block: int  # the block whose output stream or feed-forward write it reads
    reads: str  # "stream" or "write"


@dataclass(frozen=True)
class PassPlan:
    name: str
    model: str
    plan: tuple[PlannedBasis, ...]
    budget_hours: float  # GH200 hours the experiment table allows the pass, its pilot's budget
    proteins: int | None = None  # a seeded subset of this many pass proteins; None for the whole atlas set
    random_init: bool = False
    rates_from: str | None = None  # a pass whose calibrated reference rates this one reuses

    @property
    def sae_keys(self) -> dict[str, str]:
        """The planned key of each SAE read as a basis, by SAE name."""
        return {planned.basis.sae: planned.key for planned in self.plan if planned.basis.kind == "sae"}

    @property
    def references(self) -> tuple[str, ...]:
        return tuple(sorted({planned.reference for planned in self.plan if planned.reference is not None}))

    @property
    def saes(self) -> tuple[str, ...]:
        """Every SAE the pass loads: its references and its SAE bases."""
        bases = {planned.basis.sae for planned in self.plan if planned.basis.sae is not None}
        return tuple(sorted(bases | set(self.references)))


@dataclass(frozen=True)
class SiteKeys:
    """The planned keys of the bases the hypotheses compare at one site."""

    native: str
    sign: str
    residual: str
    sae: str
    rotated: tuple[str, ...]


def sweep_name(k: int, codebook: int) -> str:
    return f"esmc_600_layer27_k{k}_{codebook}"


def site_name(site: str) -> str:
    """A hypothesis site as figures and tables name it, its model and block."""
    _, block, _ = HYPOTHESIS_SITES[site]
    return f"{MODEL_NAMES[site]}, block {block}"


def site_keys(block: int, reference: str) -> SiteKeys:
    """The keys of the native, sign-only, residual, SAE and rotated bases at one block under one reference SAE."""
    return SiteKeys(f"block{block}/native@{reference}", f"block{block}/sign@{reference}", f"block{block}/residual@{reference}",
                    f"block{block}/sae:{reference}", tuple(f"block{block}/rotation{seed}@{reference}" for seed in ROTATION_SEEDS))


def stem(experiment: str, key: str) -> str:
    """A planned pair's file stem in its pass's folders; a key the pass does not plan raises."""
    stems = {planned.key: planned.stem for planned in experiment_plans()[experiment].plan}
    if key not in stems:
        raise KeyError(f"Pass {experiment} plans no pair {key!r}.")
    return stems[key]


def score_table(root: Path, experiment: str, key: str, folder: str = "scores") -> pd.DataFrame:
    """One planned pair's per-pole table from a run directory, `RUN/passes/<experiment>/<folder>/<stem>.parquet`: its
    scores (`passes.score_pass`) by default, or another folder of the pass written by stem."""
    return pd.read_parquet(root / "passes" / experiment / folder / f"{stem(experiment, key)}.parquet")


def sae_specs(saes: Mapping[str, Mapping[str, object]], sweep_revisions: Mapping[str, str] | None = None) -> dict[str, SaeSpec]:
    """Every SAE the preregistration names, from its `saes` block and the sweep's E0 pins."""
    specs: dict[str, SaeSpec] = {}
    for name, entry in saes.items():
        if name.startswith("interplm"):
            continue
        if name == "esmc_600_layer27_sweep":
            block = int(entry["block"])
            for k in entry["k"]:
                for codebook in entry["codebook"]:
                    member = sweep_name(int(k), int(codebook))
                    revision = None if sweep_revisions is None else sweep_revisions.get(member)
                    specs[member] = SaeSpec(member, str(entry["repo_pattern"]).format(k=k, codebook=codebook), revision,
                                            block + 1, block, "stream")
            continue
        block = int(entry["block"])
        reads = "write" if "_mlp_" in name else "stream"
        # Biohub numbers an MLP-output repository's shards as its residual ones, by hidden state: shard b + 1 reads block
        # b (E0, 2026-11-06: ESMC-6B's MLP shard 59 reconstructs block 58's write at 0.368, block 59's at 0.821).
        specs[name] = SaeSpec(name, str(entry["repo"]), str(entry["revision"]), block + 1, block, reads)
    return specs


def _sae(name: str, block: int, reads: str = "stream") -> Basis:
    return Basis("sae", block, sae=name, reads=reads)


def _unit_bases(block: int, reference: str, *, native_profile: str, extras: bool) -> list[PlannedBasis]:
    planned = [PlannedBasis(Basis("native", block), native_profile, reference)]
    if extras:
        planned += [PlannedBasis(Basis(kind, block), "contrast", reference) for kind in ("leak", "sign", "gate")]
    planned += [PlannedBasis(Basis("rotation", block, seed=seed), "contrast", reference) for seed in ROTATION_SEEDS]
    return planned


def experiment_plans() -> dict[str, PassPlan]:
    """The passes of E2 to E5 and the sweep, by name."""
    matched_600, shared_600 = sweep_name(64, 8192), sweep_name(64, 16384)
    shared_6b, shared_300 = "esmc_6b_layer60_k64_16384", "esmc_300_layer23_k64_16384"
    depth = [PlannedBasis(Basis(kind, block, **({"seed": 0} if kind == "rotation" else {})), "contrast", matched_600)
             for block in range(BLOCKS["esmc_600"]) if block != 26 for kind in ("native", "rotation")]
    e2 = (*depth, *_unit_bases(26, matched_600, native_profile="selection", extras=True),
          PlannedBasis(Basis("native", 26), "contrast", shared_600),
          PlannedBasis(Basis("residual", 26), "selection", matched_600),
          PlannedBasis(_sae(matched_600, 26), "selection"), PlannedBasis(_sae(shared_600, 26), "contrast"))
    e3 = (*_unit_bases(59, shared_6b, native_profile="selection", extras=True),
          PlannedBasis(Basis("residual", 59), "selection", shared_6b),
          PlannedBasis(_sae(shared_6b, 59), "selection"),
          PlannedBasis(_sae("esmc_6b_layer60_k64_65536", 59), "contrast"),
          PlannedBasis(_sae("esmc_6b_mlp_k64_131072", 59, "write"), "contrast"))
    e4 = (*_unit_bases(22, shared_300, native_profile="contrast", extras=False),
          PlannedBasis(Basis("residual", 22), "contrast", shared_300), PlannedBasis(_sae(shared_300, 22), "contrast"))
    e5_600 = tuple(PlannedBasis(Basis("native", block), "contrast", matched_600) for block in range(BLOCKS["esmc_600"]))
    e5_6b = (PlannedBasis(Basis("native", 59), "contrast", shared_6b),)
    sweep = tuple(
        planned
        for k in SWEEP_PASS_K for codebook in SWEEP_PASS_CODEBOOKS
        for planned in (PlannedBasis(Basis("native", 26), "contrast", sweep_name(k, codebook)),
                        PlannedBasis(_sae(sweep_name(k, codebook), 26), "contrast"))
    )
    return {
        "e2": PassPlan("e2", "esmc_600", e2, 0.8),
        "e2_sweep": PassPlan("e2_sweep", "esmc_600", sweep, 0.2, proteins=20_000),
        "e3": PassPlan("e3", "esmc_6b", e3, 1.1),
        "e4": PassPlan("e4", "esmc_300", e4, 0.3),
        "e5_600": PassPlan("e5_600", "esmc_600", e5_600, 0.25, proteins=30_000, random_init=True, rates_from="e2"),
        "e5_6b": PassPlan("e5_6b", "esmc_6b", e5_6b, 0.25, proteins=30_000, random_init=True, rates_from="e3"),
    }

"""One planned pass end to end, given a loaded model and SAEs: calibrate, stream, check the rate match, and score; and
E8's dictionary test and sparsest-rotation search at one block.

`scripts/units_atlas.py` loads the pinned models and SAEs and calls these; `tests/test_units_passes.py` drives them with
a tiny ESM++ and tiny SAEs. Inputs are the files the script's `inputs` stage writes under `RUN/inputs`: the atlas set,
its description (digest, vocabulary size, units, term columns), the terms table (each token's unit and scope) and the
vocabulary's ancestor matrix.

Symbols: n proteins; p poles; t terms; r residues; f units; m SAE latents.
"""

from __future__ import annotations

import json
import time
import numpy as np
import pandas as pd
import scipy.sparse as sp
import torch

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from torch import Tensor, nn

from foundry.embedding import encode_topk
from foundry.pilot import Pilot
from .atlas import PROFILES, AtlasPass, calibrate, encode_batch, length_batches, residue_sample, transformer_units
from .atlas_set import (
    MIN_DOMINANCE, MIN_SELECTION, SUBSET_SEED, AtlasSet, calibration_sequences, local_ancestors, local_presence, pass_proteins,
    residue_budget_proteins,
)
from .bases import Basis, basis_width
from .capture import DOWN_PROJECTION_INDEX, BlockReader, BlockStates
from .causal import transformer_blocks
from .compendium import CHAIN, Vocabulary
from .dictionary import THRESHOLDS, CorrelationAccumulator, copy_report, matched_write_cosines
from .experiments import PassPlan
from .firing_rates import KS_TOLERANCE, ks_distance
from .observed import TermLabels
from .poles import sign_poles, swiglu_poles
from .rotation_search import SEARCH_SEEDS, native_objective, sparsest_rotation, standardization, standardize
from .rotations import basis_recovery, haar_rotation, rotate
from .scores import global_scores, local_scores, selected_labels
from .specificity import TermRelations


DICTIONARY_RESIDUES = 2_000_000
ROTATION_RESIDUES = 200_000
CONTROL_SEED = 0  # E2's first rotation: its poles give the dictionary test's chance level
DICTIONARY_TOKEN_BUDGET = 16_384
PILOT_SEARCH_STEPS = 2


@dataclass
class PassInputs:
    frame: pd.DataFrame  # the atlas set, one row per protein
    digest: str
    vocabulary_size: int
    term_columns: dict[int, dict[int, int]]  # minimum informative count -> token -> column
    ancestors: sp.csr_matrix  # (t, t)
    unit: np.ndarray  # (t,) each global term's observation unit, -1 where none scores it
    scopes: dict[int, int]  # local token -> the amino acid it is scored on

    @classmethod
    def read(cls, directory: Path) -> PassInputs:
        description = json.loads((directory / "atlas_set.json").read_text(encoding="utf-8"))
        columns = {int(minimum): {int(token): int(column) for token, column in values.items()}
                   for minimum, values in description["term_columns"].items()}
        terms = pd.read_parquet(directory / "terms.parquet", columns=["token", "unit", "scope"]).sort_values("token")
        return cls(pd.read_parquet(directory / "atlas_set.parquet"), description["digest"],
                   int(description["vocabulary_size"]), columns, sp.load_npz(directory / "ancestors.npz").tocsr(),
                   terms["unit"].to_numpy(dtype=np.int64),
                   {int(token): int(scope) for token, scope in zip(terms["token"], terms["scope"], strict=True) if scope != CHAIN})

    def tokens(self, minimum: int) -> np.ndarray:
        """The local tokens of one term set, in column order."""
        columns = self.term_columns[minimum]
        return np.array(sorted(columns, key=columns.get), dtype=np.int64)  # (t_minimum,)


def write_inputs(built: AtlasSet, words: Vocabulary, ancestors: sp.csr_matrix, directory: Path, **facts: object) -> None:
    """The files `PassInputs.read` reads: the atlas set, its description (with any further `facts`), the terms table and
    the ancestors (`compendium.ancestor_matrix`)."""
    if ancestors.shape != (built.vocabulary_size, built.vocabulary_size):
        raise ValueError(f"The ancestor matrix {ancestors.shape} does not cover {built.vocabulary_size} terms.")
    directory.mkdir(parents=True, exist_ok=True)
    built.proteins.to_parquet(directory / "atlas_set.parquet", index=False)
    sp.save_npz(directory / "ancestors.npz", sp.csr_matrix(ancestors))
    words.terms.to_parquet(directory / "terms.parquet", index=False)
    splits = built.proteins.groupby("split").agg(proteins=("accession", "size"), residues=("length", "sum"))
    description = {
        "digest": built.digest, "vocabulary_size": built.vocabulary_size, "units": list(words.units),
        "intrinsic_tokens": built.intrinsic_tokens,
        "term_columns": {str(minimum): {str(token): column for token, column in built.term_columns(minimum).items()}
                         for minimum in (MIN_SELECTION, MIN_DOMINANCE)},
        "informative": {str(token): count for token, count in built.informative.items()},
        "splits": splits.astype(int).to_dict(orient="index"), **facts,
    }
    (directory / "atlas_set.json").write_text(json.dumps(description, indent=2, default=str), encoding="utf-8")


def run_pass(
    model: nn.Module,
    saes: Mapping[str, nn.Module],
    reads: Mapping[str, tuple[int, str]],
    plan: PassPlan,
    inputs: PassInputs,
    output: Path,
    device: torch.device,
    *,
    pilot: Pilot | None = None,
    given_rates: Mapping[str, Tensor] | None = None,
    given_validation_rates: Mapping[str, Sequence[float]] | None = None,
    log: Callable[[str], None] = print,
    **options: object,
) -> dict[str, object]:
    """Calibrate (or reuse a saved calibration), stream the pass and check every pair's rate match on validation residues.

    `reads` gives each reference SAE's block and input; a randomly initialized pass gives the trained pass's calibration
    and validation rates instead of SAEs. `options` reach `AtlasPass` (token budget, checkpoint interval).
    """
    # given_rates: (m,) by reference name
    proteins = pass_proteins(inputs.frame, subset=plan.proteins).ordered()
    references = {name: Basis("sae", reads[name][0], sae=name, reads=reads[name][1]) for name in plan.references}
    units, width = transformer_units(model), model.config.hidden_size
    seeds = sorted({planned.basis.seed for planned in plan.plan if planned.basis.kind == "rotation"})
    rotations = {seed: haar_rotation(units, seed, dtype=torch.float32, device=device) for seed in seeds}
    calibration_path = output / "calibration.pt"
    if calibration_path.exists():
        saved = torch.load(calibration_path, weights_only=True)
    else:
        matches, rates = calibrate(model, model.tokenizer, calibration_sequences(inputs.frame), plan.plan, references,
                                   rotations=rotations, saes=saes, device=device, rates=given_rates)
        saved = {"thresholds": {key: match.thresholds.cpu() for key, match in matches.items()}, "rates": rates,
                 **{field: {key: getattr(match, field).cpu() for key, match in matches.items()}
                    for field in ("natural", "achieved", "targets")}}
        output.mkdir(parents=True, exist_ok=True)
        torch.save(saved, calibration_path)
    codebooks = {name: int(sae.params.codebook_dim) for name, sae in saes.items()}
    widths = {planned.basis.name: basis_width(planned.basis, width, units, codebooks.get(planned.basis.sae or ""))
              for planned in plan.plan}
    run = AtlasPass(model, model.tokenizer, plan.plan, proteins, inputs.term_columns, saved["thresholds"], widths, output,
                    device, rotations=rotations, saes=saes, scopes=inputs.scopes, log=log, **options)
    timing = run.run(pilot)
    receipt: dict[str, object] = {"experiment": plan.name, "atlas_set_digest": inputs.digest, "proteins": len(proteins.accession),
                                  "pass_digest": run.digest, "timing": timing, "complete": run.done == len(run.batches)}
    if not receipt["complete"]:
        return receipt
    validation = run.validation_rates()
    if given_validation_rates is not None:
        reference_rates = {name: torch.as_tensor(given_validation_rates[name], dtype=torch.float64) for name in plan.references}
    else:
        reference_rates = {name: validation[plan.sae_keys[name]] for name in plan.references}
    acceptance = {}
    for planned in plan.plan:
        if planned.reference is not None:
            distance = ks_distance(validation[planned.key], reference_rates[planned.reference])
            acceptance[planned.key] = {"ks": distance, "accepted": distance < KS_TOLERANCE}
    receipt.update(acceptance=acceptance,
                   validation_reference_rates={name: rates.tolist() for name, rates in reference_rates.items()})
    return receipt


def score_pass(plan: PassPlan, inputs: PassInputs, output: Path, *, device: str = "cpu") -> dict[str, pd.DataFrame]:
    """Each planned pair's per-pole specificity, written to `output/scores`; `selection` pairs also get their labels."""
    proteins = pass_proteins(inputs.frame, subset=plan.proteins).ordered()
    order = inputs.frame.set_index("accession").loc[proteins.accession].reset_index()
    labels = TermLabels.from_frame(order, inputs.vocabulary_size, inputs.unit)
    train = np.flatnonzero(proteins.split == "train")  # (n_train,)
    global_relations = TermRelations(inputs.ancestors, labels.positives[train])
    dominance_tokens = inputs.tokens(MIN_DOMINANCE)  # (t_dominance,)
    local_relations = TermRelations(local_ancestors(inputs.ancestors, dominance_tokens),
                                    local_presence(order.iloc[train], dominance_tokens))
    tables_dir = output / "scores"
    tables_dir.mkdir(parents=True, exist_ok=True)
    tables: dict[str, pd.DataFrame] = {}
    for planned in plan.plan:
        maxima = np.load(output / "maxima" / f"{planned.stem}.npy", mmap_mode="r")  # (n, p)
        table = global_scores(maxima, proteins.split, labels, global_relations, device=device)
        state = torch.load(output / "state" / f"{planned.stem}.pt", weights_only=True)["train"]
        kept_tokens = inputs.tokens(PROFILES[planned.profile].min_informative)  # (t_profile,)
        position = {int(token): column for column, token in enumerate(kept_tokens)}
        dominance = np.array([position[int(token)] for token in dominance_tokens], dtype=np.int64)  # (t_dominance,)
        sums = {key.removeprefix("sum."): value.double().numpy() for key, value in state.items() if key.startswith("sum.")}
        counts = {key: state[key].numpy() for key in ("n_informative", "inside_exposure", "outside_exposure")}
        local = local_scores({**{key: value[:, dominance] for key, value in sums.items()},
                              "n_informative": counts["n_informative"][dominance]}, dominance_tokens, local_relations)
        table = table.merge(local, on="pole", validate="one_to_one")
        table.to_parquet(tables_dir / f"{planned.stem}.parquet", index=False)
        tables[planned.key] = table
        if planned.profile == "selection":
            selected_labels({**sums, **counts}, kept_tokens).to_parquet(tables_dir / f"{planned.stem}.labels_local.parquet",
                                                                        index=False)
    return tables


def subset_scores(plan: PassPlan, subset: int, inputs: PassInputs, output: Path, keys: Sequence[str], *,
                  device: str = "cpu") -> dict[str, pd.DataFrame]:
    """Global scores of some of a pass's pairs over the proteins of a seeded subset of it, the random-init pass's own, so
    trained and random networks are compared on the same proteins; written to `output/scores_subset_<subset>`."""
    proteins = pass_proteins(inputs.frame, subset=plan.proteins).ordered()
    chosen = pass_proteins(inputs.frame, subset=subset).ordered()
    row_of = {accession: row for row, accession in enumerate(proteins.accession)}
    rows = np.array([row_of[accession] for accession in chosen.accession], dtype=np.int64)  # (n_subset,)
    order = inputs.frame.set_index("accession").loc[chosen.accession].reset_index()
    labels = TermLabels.from_frame(order, inputs.vocabulary_size, inputs.unit)
    relations = TermRelations(inputs.ancestors, labels.positives[np.flatnonzero(chosen.split == "train")])
    by_key = {planned.key: planned for planned in plan.plan}
    tables_dir = output / f"scores_subset_{subset}"
    tables_dir.mkdir(parents=True, exist_ok=True)
    tables = {}
    for key in keys:
        maxima = np.load(output / "maxima" / f"{by_key[key].stem}.npy", mmap_mode="r")  # (n, p)
        tables[key] = global_scores(np.asarray(maxima[rows]), chosen.split, labels, relations, device=device)
        tables[key].to_parquet(tables_dir / f"{by_key[key].stem}.parquet", index=False)
    return tables


def run_dictionary(
    model: nn.Module,
    saes: Mapping[str, nn.Module],
    reads: Mapping[str, str],
    block: int,
    inputs: PassInputs,
    output: Path,
    device: torch.device,
    *,
    residues: int = DICTIONARY_RESIDUES,
    sample: int = ROTATION_RESIDUES,
    seeds: Sequence[int] = SEARCH_SEEDS,
    steps: int = 300,
    token_budget: int = DICTIONARY_TOKEN_BUDGET,
    cofiring: bool = False,
    keep_rotations: bool = False,
    pilot: Pilot | None = None,
    log: Callable[[str], None] = print,
) -> dict[str, object]:
    """E8 at one block (preregistration, `dictionary_test` and `sparsest_rotation`).

    Over the training proteins whose residues first reach `residues`, each SAE's latents are correlated with the block's
    native poles and with the poles of rotation `CONTROL_SEED`, the chance level; `reads` gives each SAE's input,
    "stream" or "write". With `cofiring`, the native poles are also correlated with one another over the same residues
    and the matrix is written to `pole_cofiring.npy`, for E10's co-firing blocks. Then the units' products at a seeded
    sample of `sample` of those residues, standardized, are searched for their sparsest rotation from each seed's Haar
    start. With `keep_rotations` the found rotations (float32) and the sample's standardization go to `searched.npz`,
    for E13s to read the units in them. Under a pilot only its window streams, and two search steps on the residues it
    kept time the search; the receipt then says the run is incomplete.
    """
    proteins = residue_budget_proteins(inputs.frame, residues).ordered()
    lengths = proteins.lengths  # (n,)
    total = int(lengths.sum())
    units = transformer_units(model)
    control = haar_rotation(units, CONTROL_SEED, dtype=torch.float32, device=device)  # (f, f)
    accumulators = {(name, basis): CorrelationAccumulator(int(sae.params.codebook_dim), 2 * units, device)
                    for name, sae in saes.items() for basis in ("native", "rotation")}
    pole_pairs = CorrelationAccumulator(2 * units, 2 * units, device) if cofiring else None
    keep = residue_sample(total, sample, SUBSET_SEED)  # (r_total,)
    kept: list[Tensor] = []
    seen = 0

    def consume(states: BlockStates) -> None:
        nonlocal seen
        product = states.product()  # (r, f)
        poles = {"native": swiglu_poles(states.gate, states.up).main(), "rotation": sign_poles(rotate(product, control))}
        for name, sae in saes.items():
            codes = encode_topk(states.write if reads[name] == "write" else states.stream, sae)  # (r, k) each
            for basis, activations in poles.items():  # (r, 2f)
                accumulators[name, basis].update_codes(codes.indices, codes.values, activations)
        if pole_pairs is not None:
            pole_pairs.update(poles["native"], poles["native"])
        chosen = torch.from_numpy(keep[seen:seen + product.shape[0]]).to(product.device)  # (r,)
        kept.append(product[chosen].cpu())
        seen += product.shape[0]

    batches = length_batches(lengths, token_budget)
    started = time.time()
    sources = set(reads[name] for name in saes)
    with BlockReader(model, [block], consume, write_blocks=[block] if "write" in sources else [],
                     stream_blocks=[block] if "stream" in sources else []) as reader:
        indices = range(len(batches))
        for index in pilot.watch(indices) if pilot is not None else indices:
            input_ids, attention_mask, residue_mask = encode_batch(model.tokenizer, proteins.sequence[batches[index]], device)
            reader.run(input_ids, attention_mask, residue_mask)
    elapsed = time.time() - started
    receipt: dict[str, object] = {"block": block, "proteins": len(lengths), "residues": seen, "seconds": elapsed,
                                  "residues_per_second": seen / max(elapsed, 1e-9), "complete": seen == total}
    sampled = torch.cat(kept) if kept else torch.zeros((0, units))  # (r_sample, f), on the CPU
    kept.clear()
    if not receipt["complete"]:
        if len(sampled) > 1:
            timed = time.time()
            sparsest_rotation(standardize(sampled.to(device)), seed=seeds[0], steps=PILOT_SEARCH_STEPS)
            receipt["search_pilot"] = {"residues": len(sampled), "steps": PILOT_SEARCH_STEPS, "seconds": time.time() - timed}
        return receipt
    output.mkdir(parents=True, exist_ok=True)
    if pole_pairs is not None:
        np.save(output / "pole_cofiring.npy", pole_pairs.correlations().float().cpu().numpy())  # (2f, 2f)
        receipt["pole_cofiring"] = {"poles": 2 * units, "residues": pole_pairs.count}
        del pole_pairs
    write = transformer_blocks(model)[block].ffn[DOWN_PROJECTION_INDEX].weight  # (d, f)
    dictionaries = {}
    for name, sae in saes.items():
        native = accumulators.pop((name, "native"))
        copies = copy_report(native)
        chance = copy_report(accumulators.pop((name, "rotation")))
        cosines = matched_write_cosines(sae.W_dec, write, copies.best_pole)  # (m,)
        pd.DataFrame({
            "latent": np.arange(len(cosines)), "best_pole": copies.best_pole.cpu().numpy(),
            "best_correlation": copies.best_correlation.cpu().numpy(), "mass": native.mass.cpu().numpy(),
            "write_cosine": cosines.cpu().numpy(), "rotated_best_correlation": chance.best_correlation.cpu().numpy(),
        }).to_parquet(output / f"{name}.parquet", index=False)
        dictionaries[name] = {
            "reads": reads[name], "latents": len(cosines),
            "native_shares": {str(threshold): share for threshold, share in copies.shares.items()},
            "rotated_shares": {str(threshold): share for threshold, share in chance.shares.items()},
            "copying_latents": {str(threshold): int((copies.best_correlation >= threshold).sum()) for threshold in THRESHOLDS},
            "median_write_cosine": {str(threshold): float(cosines[copies.best_correlation >= threshold].median())
                                    if bool((copies.best_correlation >= threshold).any()) else None
                                    for threshold in THRESHOLDS},
        }
        del native
        log(f"{name}: {dictionaries[name]['native_shares']} of activity copies a native pole, "
            f"{dictionaries[name]['rotated_shares']} a rotated one")
    sampled = sampled.to(device)  # (r_sample, f), once the accumulators are freed
    standard = standardization(sampled)
    samples = standard.apply(sampled)  # (r_sample, f), float64
    del sampled
    searches, axes, rotations = [], {}, {}
    for seed in seeds:
        found = sparsest_rotation(samples, seed=seed, steps=steps)
        axes[str(seed)] = found.rotation.abs().amax(dim=0).cpu().numpy()  # (f,)
        if keep_rotations:
            rotations[f"rotation{seed}"] = found.rotation.float().cpu().numpy()  # (f, f)
        searches.append({"seed": seed, "start_recovery": basis_recovery(haar_rotation(units, seed, dtype=torch.float64)),
                         "recovery": float(axes[str(seed)].mean()), "start_objective": found.objective[0],
                         "objective": found.objective[-1], "steps": len(found.objective) - 1})
        log(f"search from seed {seed}: recovery {searches[-1]['recovery']:.3f} after {searches[-1]['steps']} steps")
    np.savez(output / "axis_recovery.npz", **axes)
    if keep_rotations:
        np.savez(output / "searched.npz", mean=standard.mean.cpu().numpy(), scale=standard.scale.cpu().numpy(), **rotations)
    receipt.update(dictionaries=dictionaries, rotation_search={
        "residues": int(samples.shape[0]), "native_objective": float(native_objective(samples)), "searches": searches})
    (output / "report.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    return receipt

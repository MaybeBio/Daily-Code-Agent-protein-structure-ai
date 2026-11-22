"""Read a canonical property release (its `dataset.json` and split Parquet files) into arrays a control head can use.

A release is the directory `production_suite` exports: `dataset.json` names the task, the label vocabulary and each
split's file with its SHA-256; every split file carries `seqs`, `labels`, `label_mask`, `cluster_id`, `source_json` and
`evidence_json`. The reader checks each file against its declared digest, decodes dense, list and compact labels into
one dense array, and keeps the metadata the metadata-only control reads: the source namespace, the organism and the
first EC number.

Symbols: n rows of a split, v label columns.
"""

from __future__ import annotations

import json
import re
import numpy as np

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from foundry.digests import sha256_file


MANIFEST_FILE = "dataset.json"
TASK_TYPES = ("binary", "multiclass", "multilabel", "regression")
SPLITS = ("train", "validation", "test")
COLUMNS = ("seqs", "labels", "label_mask", "cluster_id", "source_json", "evidence_json")
ORGANISM_NAME = re.compile(r"\sOS=(.+?)\s(?:OX|GN|PE|SV)=")
ORGANISM_TAXON = re.compile(r"\sOX=(\d+)")
NO_ORGANISM = "unknown"
NO_EC = "none"


@dataclass(frozen=True)
class Split:
    """One split's rows: the protein texts, the labels with what is observed, and the row metadata."""

    name: str
    sequences: np.ndarray  # (n,) protein texts
    labels: np.ndarray  # (n,) float64 value or class, or (n, v) float32 multilabel targets
    observed: np.ndarray  # (n,) or (n, v) bool, which labels are observed
    cluster: np.ndarray  # (n,) finest cluster id of each row
    source: np.ndarray  # (n,) source namespace of each row
    species: np.ndarray  # (n,) organism key (taxon id or name) of each row
    genus: np.ndarray  # (n,) first word of the organism name
    ec: np.ndarray  # (n,) first EC number of each row, NO_EC for none

    @property
    def rows(self) -> int:
        return len(self.sequences)


@dataclass(frozen=True)
class Release:
    """A release's identity and the splits a control reads."""

    directory: Path
    dataset_id: str
    task_type: str
    vocabulary: tuple[str, ...]
    units: str | None
    manifest_sha256: str
    splits: dict[str, Split]

    @property
    def width(self) -> int:
        """Label columns v: one for a regression or binary task, the vocabulary's size otherwise."""
        return len(self.vocabulary) if self.task_type in ("multiclass", "multilabel") else 1


def read_release(directory: Path, splits: Sequence[str] = SPLITS) -> Release:
    """The release at `directory`, its split files checked against `dataset.json`."""
    import pyarrow.parquet as parquet

    manifest_path = directory / MANIFEST_FILE
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    task_type = manifest["task_type"]
    if task_type not in TASK_TYPES:
        raise ValueError(f"{manifest_path} declares task_type {task_type!r}; a control reads one of {TASK_TYPES}.")
    vocabulary = tuple(str(name) for name in manifest["label_vocabulary"])
    width = len(vocabulary) if task_type in ("multiclass", "multilabel") else 1
    missing = [name for name in splits if name not in manifest["splits"]]
    if missing:
        raise ValueError(f"{manifest_path} has no splits {missing}; it has {sorted(manifest['splits'])}.")
    read: dict[str, Split] = {}
    for name in splits:
        declared = manifest["splits"][name]
        path = directory / declared["path"]
        digest = sha256_file(path)
        if digest != declared["sha256"]:
            raise ValueError(f"{path} has SHA-256 {digest}; {MANIFEST_FILE} declares {declared['sha256']}.")
        table = parquet.read_table(path, columns=list(COLUMNS)).to_pydict()
        if len(table["seqs"]) != declared["rows"]:
            raise ValueError(f"{path} holds {len(table['seqs'])} rows; {MANIFEST_FILE} declares {declared['rows']}.")
        read[name] = decode_split(name, table, task_type=task_type, width=width)
    return Release(directory, str(manifest["dataset_id"]), task_type, vocabulary, manifest.get("units"),
                   sha256_file(manifest_path), read)


def decode_split(name: str, table: Mapping[str, list[Any]], *, task_type: str, width: int) -> Split:
    """A split's columns as arrays; labels and masks of every stored encoding become one dense array each."""
    labels, observed = decode_labels(table["labels"], table["label_mask"], task_type=task_type, width=width)
    sources, species, genera, ecs = [], [], [], []
    for source_json, evidence_json in zip(table["source_json"], table["evidence_json"], strict=True):
        sources.append(str(json.loads(source_json)["namespace"]))
        values = json.loads(evidence_json).get("source_values", {})
        key, genus = organism_of(values)
        species.append(key)
        genera.append(genus)
        ecs.append(ec_of(values))
    return Split(name, np.array(table["seqs"], dtype=object), labels, observed, np.array(table["cluster_id"], dtype=object),
                 np.array(sources, dtype=object), np.array(species, dtype=object), np.array(genera, dtype=object),
                 np.array(ecs, dtype=object))


def decode_labels(labels: Sequence[Any], masks: Sequence[Any], *, task_type: str, width: int) -> tuple[np.ndarray, np.ndarray]:
    """Dense labels and their observed mask from scalar, list or compact struct rows.

    A regression, binary or multiclass row is one float (or a one-element list); its mask one boolean. A multilabel row
    is a list of v floats with a list of v booleans, or the compact struct `{width, indices, values}` with the mask
    `{default_observed, exceptions}`. Unobserved entries are stored as 0.
    """
    if task_type != "multilabel":
        values = np.array([_scalar(label) for label in labels], dtype=np.float64)  # (n,)
        observed = np.array([_scalar(mask) for mask in masks], dtype=np.bool_)  # (n,)
        if task_type == "multiclass" and observed.any():
            seen = values[observed]  # (n_observed,)
            if (seen != np.round(seen)).any() or seen.min() < 0 or seen.max() >= width:
                raise ValueError(f"multiclass labels must be class indices below {width}.")
        return values, observed  # (n,), (n,)
    dense = np.zeros((len(labels), width), dtype=np.float32)  # (n, v)
    observed_matrix = np.zeros((len(labels), width), dtype=np.bool_)  # (n, v)
    for row, (label, mask) in enumerate(zip(labels, masks, strict=True)):
        if isinstance(label, Mapping):
            if int(label["width"]) != width:
                raise ValueError(f"a compact row declares width {label['width']}; the vocabulary has {width} labels.")
            indices = np.asarray(label["indices"], dtype=np.int64)  # (k,)
            dense[row, indices] = np.asarray(label["values"], dtype=np.float32)
            observed_matrix[row] = bool(mask["default_observed"])
            exceptions = np.asarray(mask["exceptions"], dtype=np.int64)  # (m,)
            observed_matrix[row, exceptions] = not bool(mask["default_observed"])
        else:
            if len(label) != width or len(mask) != width:
                raise ValueError(f"a multilabel row has {len(label)} labels and {len(mask)} mask entries; expected {width}.")
            dense[row] = np.asarray(label, dtype=np.float32)
            observed_matrix[row] = np.asarray(mask, dtype=np.bool_)
    dense[~observed_matrix] = 0.0
    return dense, observed_matrix  # (n, v), (n, v)


def _scalar(value: Any) -> Any:
    if isinstance(value, list):
        if len(value) != 1:
            raise ValueError(f"a single-label row holds one value; received {len(value)}.")
        return value[0]
    return value


def organism_of(values: Mapping[str, Any]) -> tuple[str, str]:
    """The organism key (its taxon id when known, else its name) and genus of a row's source values.

    A Swiss-Prot comment carries the organism's record under `organism`; a BRENDA row carries the UniProt header of
    its sequence, whose `OS=` and `OX=` fields name the organism. Rows without either are `unknown`.
    """
    organism = values.get("organism")
    if isinstance(organism, Mapping) and organism.get("name"):
        name, taxon = str(organism["name"]), organism.get("taxon_id")
    else:
        header = str((values.get("sequence") or {}).get("header") or "")
        found, taxa = ORGANISM_NAME.search(header), ORGANISM_TAXON.search(header)
        name = found.group(1) if found else (organism if isinstance(organism, str) else "")
        taxon = taxa.group(1) if taxa else None
    if not name:
        return NO_ORGANISM, NO_ORGANISM
    return (f"taxon:{taxon}" if taxon else name), name.split()[0]


def ec_of(values: Mapping[str, Any]) -> str:
    """The first EC number of a row's source values, NO_EC when it has none."""
    numbers = values.get("ec_numbers") or ([values["ec_number"]] if values.get("ec_number") else [])
    return str(sorted(numbers)[0]) if numbers else NO_EC

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, Optional

import numpy as np
import torch
from torch import Tensor, nn
from torch.nn.functional import one_hot


@dataclass(frozen=True)
class PairRowLayout:
    original_size: int
    world_size: int
    rank: int
    local_rows: int
    row_start: int
    valid_rows: int

    @classmethod
    def create(cls, *, original_size: int, world_size: int, rank: int) -> "PairRowLayout":
        if original_size <= 0:
            raise ValueError("original_size must be positive")
        if world_size <= 0:
            raise ValueError("world_size must be positive")
        if rank < 0 or rank >= world_size:
            raise ValueError(f"rank {rank} is outside world size {world_size}")
        local_rows = (original_size + world_size - 1) // world_size
        row_start = rank * local_rows
        valid_rows = max(0, min(local_rows, original_size - row_start))
        return cls(
            original_size=original_size,
            world_size=world_size,
            rank=rank,
            local_rows=local_rows,
            row_start=row_start,
            valid_rows=valid_rows,
        )

    @property
    def row_end(self) -> int:
        return self.row_start + self.valid_rows


@dataclass(frozen=True)
class CompactPairFeatures:
    token_index: Tensor
    residue_index: Tensor
    asym_id: Tensor
    entity_id: Tensor
    sym_id: Tensor
    cyclic_period: Tensor
    token_pad_mask: Tensor
    bond_rows: Tensor
    bond_cols: Tensor
    bond_types: Tensor
    contact_rows: Tensor
    contact_cols: Tensor
    contact_classes: Tensor
    contact_thresholds: Tensor
    contact_default_class: int
    num_contact_classes: int

    @classmethod
    def from_tokenized(
        cls,
        tokenized: Any,
        *,
        pocket_constraints: Optional[list] = None,
        contact_constraints: Optional[list] = None,
    ) -> "CompactPairFeatures":
        """Build stock-equivalent pair sources for unpadded inference features.

        This matches ``process_token_features`` with ``training=False``,
        ``max_tokens=None``, and the random conditioning probabilities disabled.
        """
        from boltz.data import const

        token_data = tokenized.tokens
        token_count = len(token_data)
        token_to_position = {
            int(token["token_idx"]): position
            for position, token in enumerate(token_data)
        }

        bond_values: dict[tuple[int, int], int] = {}
        for bond in tokenized.bonds:
            first = token_to_position[int(bond["token_1"])]
            second = token_to_position[int(bond["token_2"])]
            bond_type = int(bond["type"])
            bond_values[(first, second)] = bond_type
            bond_values[(second, first)] = bond_type
        bond_rows, bond_cols, bond_types = _mapping_tensors(bond_values)

        nonpolymer = const.chain_type_ids["NONPOLYMER"]
        token_lookup: dict[tuple[int, int], int] = {}
        for position, token in enumerate(token_data):
            coordinate = (
                int(token["atom_idx"])
                if int(token["mol_type"]) == nonpolymer
                else int(token["res_idx"])
            )
            token_lookup.setdefault((int(token["asym_id"]), coordinate), position)

        contact_values: dict[tuple[int, int], tuple[int, float]] = {}

        def set_contact(row: int, col: int, contact_class: int, threshold: float) -> None:
            contact_values[(row, col)] = (contact_class, float(threshold))

        for binder, contacts, max_distance, _force in pocket_constraints or []:
            binder_positions = np.flatnonzero(token_data["asym_id"] == binder)
            for contact in contacts:
                target = token_lookup.get((int(contact[0]), int(contact[1])))
                if target is None:
                    continue
                for binder_position in binder_positions:
                    set_contact(
                        int(binder_position),
                        target,
                        const.contact_conditioning_info["BINDER>POCKET"],
                        max_distance,
                    )
                    set_contact(
                        target,
                        int(binder_position),
                        const.contact_conditioning_info["POCKET>BINDER"],
                        max_distance,
                    )

        for first, second, max_distance, _force in contact_constraints or []:
            first_position = token_lookup.get((int(first[0]), int(first[1])))
            second_position = token_lookup.get((int(second[0]), int(second[1])))
            if first_position is None or second_position is None:
                continue
            contact_class = const.contact_conditioning_info["CONTACT"]
            set_contact(first_position, second_position, contact_class, max_distance)
            set_contact(second_position, first_position, contact_class, max_distance)

        if contact_values:
            contact_default_class = const.contact_conditioning_info["UNSELECTED"]
        else:
            contact_default_class = const.contact_conditioning_info["UNSPECIFIED"]
        contact_rows, contact_cols, contact_classes, contact_thresholds = (
            _contact_mapping_tensors(contact_values)
        )

        cyclic_period = torch.from_numpy(token_data["cyclic_period"].copy()).float()
        cyclic_ids: dict[int, int] = {}
        for chain_index, asym_id in enumerate(tokenized.structure.chains["asym_id"]):
            for connection in tokenized.structure.bonds:
                if (
                    chain_index
                    == int(connection["chain_1"])
                    == int(connection["chain_2"])
                    and int(tokenized.structure.chains[chain_index]["res_num"]) > 2
                    and int(connection["res_1"]) != int(connection["res_2"])
                ):
                    residue_count = int(
                        tokenized.structure.chains[int(connection["chain_1"])]["res_num"]
                    )
                    if (
                        residue_count == int(connection["res_2"]) + 1
                        and int(connection["res_1"]) == 0
                    ) or (
                        residue_count == int(connection["res_1"]) + 1
                        and int(connection["res_2"]) == 0
                    ):
                        cyclic_ids[int(asym_id)] = residue_count
        structure_cyclic_period = torch.tensor(
            [cyclic_ids.get(int(asym_id), 0) for asym_id in token_data["asym_id"]],
            dtype=torch.float32,
        )

        return cls(
            token_index=torch.arange(token_count, dtype=torch.long),
            residue_index=torch.from_numpy(token_data["res_idx"].copy()).long(),
            asym_id=torch.from_numpy(token_data["asym_id"].copy()).long(),
            entity_id=torch.from_numpy(token_data["entity_id"].copy()).long(),
            sym_id=torch.from_numpy(token_data["sym_id"].copy()).long(),
            cyclic_period=torch.maximum(cyclic_period, structure_cyclic_period),
            token_pad_mask=torch.ones(token_count, dtype=torch.float32),
            bond_rows=bond_rows,
            bond_cols=bond_cols,
            bond_types=bond_types,
            contact_rows=contact_rows,
            contact_cols=contact_cols,
            contact_classes=contact_classes,
            contact_thresholds=contact_thresholds,
            contact_default_class=contact_default_class,
            num_contact_classes=len(const.contact_conditioning_info),
        )

    @classmethod
    def from_processed_record(
        cls,
        record: Any,
        structures_dir: Any,
    ) -> "CompactPairFeatures":
        from pathlib import Path

        from boltz.data.tokenize.boltz2 import tokenize_structure
        from boltz.data.types import StructureV2

        structure = StructureV2.load(Path(structures_dir) / f"{record.id}.npz")
        tokens, bonds = tokenize_structure(structure, record.affinity)
        tokenized = SimpleNamespace(tokens=tokens, bonds=bonds, structure=structure)
        options = record.inference_options
        return cls.from_tokenized(
            tokenized,
            pocket_constraints=(
                None if options is None else options.pocket_constraints
            ),
            contact_constraints=(
                None if options is None else options.contact_constraints
            ),
        )

    @property
    def token_count(self) -> int:
        return int(self.token_index.numel())

    @property
    def storage_bytes(self) -> int:
        return sum(
            tensor.numel() * tensor.element_size()
            for tensor in (
                self.token_index,
                self.residue_index,
                self.asym_id,
                self.entity_id,
                self.sym_id,
                self.cyclic_period,
                self.token_pad_mask,
                self.bond_rows,
                self.bond_cols,
                self.bond_types,
                self.contact_rows,
                self.contact_cols,
                self.contact_classes,
                self.contact_thresholds,
            )
        )

    def relative_position_features(self, device: torch.device) -> dict[str, Tensor]:
        return {
            "token_index": self.token_index.unsqueeze(0).to(device),
            "residue_index": self.residue_index.unsqueeze(0).to(device),
            "asym_id": self.asym_id.unsqueeze(0).to(device),
            "entity_id": self.entity_id.unsqueeze(0).to(device),
            "sym_id": self.sym_id.unsqueeze(0).to(device),
            "cyclic_period": self.cyclic_period.unsqueeze(0).to(device),
        }

    def materialize_tile(
        self,
        row_start: int,
        row_end: int,
        *,
        device: torch.device,
    ) -> dict[str, Tensor]:
        if row_start < 0 or row_end < row_start or row_end > self.token_count:
            raise ValueError(
                f"invalid pair tile [{row_start}, {row_end}) for {self.token_count} tokens"
            )
        tile_rows = row_end - row_start
        token_mask = self.token_pad_mask.to(device)
        pair_mask = (
            token_mask[row_start:row_end, None] * token_mask[None, :]
        ).unsqueeze(0)
        token_bonds = torch.zeros(
            (1, tile_rows, self.token_count, 1),
            dtype=torch.float32,
            device=device,
        )
        type_bonds = torch.zeros(
            (1, tile_rows, self.token_count),
            dtype=torch.long,
            device=device,
        )
        bond_selection = (self.bond_rows >= row_start) & (self.bond_rows < row_end)
        if torch.any(bond_selection):
            local_rows = (self.bond_rows[bond_selection] - row_start).to(device)
            columns = self.bond_cols[bond_selection].to(device)
            token_bonds[0, local_rows, columns, 0] = 1.0
            type_bonds[0, local_rows, columns] = self.bond_types[bond_selection].to(
                device
            )

        contact_labels = torch.full(
            (1, tile_rows, self.token_count),
            self.contact_default_class,
            dtype=torch.long,
            device=device,
        )
        contact_threshold = torch.zeros(
            (1, tile_rows, self.token_count),
            dtype=torch.float32,
            device=device,
        )
        contact_selection = (self.contact_rows >= row_start) & (
            self.contact_rows < row_end
        )
        if torch.any(contact_selection):
            local_rows = (self.contact_rows[contact_selection] - row_start).to(device)
            columns = self.contact_cols[contact_selection].to(device)
            contact_labels[0, local_rows, columns] = self.contact_classes[
                contact_selection
            ].to(device)
            contact_threshold[0, local_rows, columns] = self.contact_thresholds[
                contact_selection
            ].to(device)
        contact_conditioning = one_hot(
            contact_labels,
            num_classes=self.num_contact_classes,
        )
        return {
            "pair_mask": pair_mask,
            "token_bonds": token_bonds,
            "type_bonds": type_bonds,
            "contact_conditioning": contact_conditioning,
            "contact_threshold": contact_threshold,
        }


def local_dense_pair_view(tensor: Tensor, layout: PairRowLayout) -> Tensor:
    if tensor.ndim < 3:
        raise ValueError("pair tensor must have at least batch, row, and column axes")
    if tensor.shape[1] != layout.original_size or tensor.shape[2] != layout.original_size:
        raise ValueError(
            "pair tensor axes do not match layout: "
            f"{tuple(tensor.shape[:3])} vs {layout.original_size}"
        )
    return _pad_local_rows(tensor[:, layout.row_start : layout.row_end], layout)


def atom_to_token_indices(feats: dict[str, Any]) -> tuple[Tensor, Tensor]:
    if "atom_to_token_idx" in feats:
        indices = feats["atom_to_token_idx"].long()
        return indices, indices >= 0
    dense = feats["atom_to_token"]
    return dense.argmax(dim=-1).long(), dense.sum(dim=-1) > 0


def representative_atom_indices(feats: dict[str, Any]) -> tuple[Tensor, Tensor]:
    if "token_to_rep_atom_idx" in feats:
        indices = feats["token_to_rep_atom_idx"].long()
        return indices, indices >= 0
    dense = feats["token_to_rep_atom"]
    return dense.argmax(dim=-1).long(), dense.sum(dim=-1) > 0


def local_pair_mask(token_mask: Tensor, layout: PairRowLayout) -> Tensor:
    if token_mask.ndim != 2 or token_mask.shape[1] != layout.original_size:
        raise ValueError("token mask shape does not match layout")
    row_mask = token_mask[:, layout.row_start : layout.row_end]
    pair_mask = row_mask[:, :, None] * token_mask[:, None, :]
    return _pad_local_rows(pair_mask, layout)


def local_relative_position_encoding(
    rel_pos: nn.Module,
    feats: dict[str, Tensor],
    layout: PairRowLayout,
) -> Tensor:
    inputs = local_relative_position_inputs(rel_pos, feats, layout)
    valid_output = rel_pos.linear_layer(inputs[:, : layout.valid_rows])
    return _pad_local_rows(valid_output, layout)


def local_relative_position_inputs(
    rel_pos: nn.Module,
    feats: dict[str, Tensor],
    layout: PairRowLayout,
) -> Tensor:
    inputs = relative_position_inputs_for_rows(
        rel_pos,
        feats,
        row_start=layout.row_start,
        row_end=layout.row_end,
    )
    return _pad_local_rows(inputs, layout)


def relative_position_inputs_for_rows(
    rel_pos: nn.Module,
    feats: dict[str, Tensor],
    *,
    row_start: int,
    row_end: int,
) -> Tensor:
    original_size = feats["asym_id"].shape[1]
    required = (
        "asym_id",
        "residue_index",
        "entity_id",
        "token_index",
        "sym_id",
        "cyclic_period",
    )
    for name in required:
        if name not in feats or feats[name].ndim != 2:
            raise ValueError(f"relative-position feature {name!r} is missing or invalid")
        if feats[name].shape[1] != original_size:
            raise ValueError(
                f"relative-position feature {name!r} does not match token count"
            )

    if row_start < 0 or row_end < row_start or row_end > original_size:
        raise ValueError(
            f"invalid relative-position rows [{row_start}, {row_end}) for "
            f"{original_size} tokens"
        )
    row_slice = slice(row_start, row_end)
    same_chain = torch.eq(
        feats["asym_id"][:, row_slice, None], feats["asym_id"][:, None, :]
    )
    same_residue = torch.eq(
        feats["residue_index"][:, row_slice, None],
        feats["residue_index"][:, None, :],
    )
    same_entity = torch.eq(
        feats["entity_id"][:, row_slice, None], feats["entity_id"][:, None, :]
    )

    residue_delta = (
        feats["residue_index"][:, row_slice, None]
        - feats["residue_index"][:, None, :]
    )
    if rel_pos.cyclic_pos_enc and torch.any(feats["cyclic_period"] > 0):
        period = torch.where(
            feats["cyclic_period"] > 0,
            feats["cyclic_period"],
            torch.zeros_like(feats["cyclic_period"]) + 10000,
        )
        residue_delta = (
            residue_delta - period * torch.round(residue_delta / period)
        ).long()
    residue_delta = torch.clip(
        residue_delta + rel_pos.r_max, 0, 2 * rel_pos.r_max
    )
    residue_delta = torch.where(
        same_chain,
        residue_delta,
        torch.zeros_like(residue_delta) + 2 * rel_pos.r_max + 1,
    )
    relative_position = one_hot(residue_delta, 2 * rel_pos.r_max + 2)

    token_delta = torch.clip(
        feats["token_index"][:, row_slice, None]
        - feats["token_index"][:, None, :]
        + rel_pos.r_max,
        0,
        2 * rel_pos.r_max,
    )
    token_delta = torch.where(
        same_chain & same_residue,
        token_delta,
        torch.zeros_like(token_delta) + 2 * rel_pos.r_max + 1,
    )
    relative_token = one_hot(token_delta, 2 * rel_pos.r_max + 2)

    chain_delta = torch.clip(
        feats["sym_id"][:, row_slice, None]
        - feats["sym_id"][:, None, :]
        + rel_pos.s_max,
        0,
        2 * rel_pos.s_max,
    )
    chain_condition = (~same_entity) if rel_pos.fix_sym_check else same_chain
    chain_delta = torch.where(
        chain_condition,
        torch.zeros_like(chain_delta) + 2 * rel_pos.s_max + 1,
        chain_delta,
    )
    relative_chain = one_hot(chain_delta, 2 * rel_pos.s_max + 2)

    inputs = torch.cat(
        [
            relative_position.float(),
            relative_token.float(),
            same_entity.unsqueeze(-1).float(),
            relative_chain.float(),
        ],
        dim=-1,
    )
    return inputs


def _pad_local_rows(tensor: Tensor, layout: PairRowLayout) -> Tensor:
    if tensor.shape[1] != layout.valid_rows:
        raise ValueError(
            f"local tensor has {tensor.shape[1]} rows, expected {layout.valid_rows}"
        )
    padding_rows = layout.local_rows - layout.valid_rows
    if padding_rows == 0:
        return tensor.contiguous()
    padding_shape = list(tensor.shape)
    padding_shape[1] = padding_rows
    padding = torch.zeros(
        padding_shape,
        dtype=tensor.dtype,
        device=tensor.device,
    )
    return torch.cat([tensor, padding], dim=1).contiguous()


def _mapping_tensors(
    values: dict[tuple[int, int], int],
) -> tuple[Tensor, Tensor, Tensor]:
    entries = sorted((row, col, value) for (row, col), value in values.items())
    if not entries:
        empty = torch.empty(0, dtype=torch.long)
        return empty, empty.clone(), empty.clone()
    rows, cols, mapped_values = zip(*entries, strict=True)
    return (
        torch.tensor(rows, dtype=torch.long),
        torch.tensor(cols, dtype=torch.long),
        torch.tensor(mapped_values, dtype=torch.long),
    )


def _contact_mapping_tensors(
    values: dict[tuple[int, int], tuple[int, float]],
) -> tuple[Tensor, Tensor, Tensor, Tensor]:
    entries = sorted(
        (row, col, contact_class, threshold)
        for (row, col), (contact_class, threshold) in values.items()
    )
    if not entries:
        empty_long = torch.empty(0, dtype=torch.long)
        return (
            empty_long,
            empty_long.clone(),
            empty_long.clone(),
            torch.empty(0, dtype=torch.float32),
        )
    rows, cols, classes, thresholds = zip(*entries, strict=True)
    return (
        torch.tensor(rows, dtype=torch.long),
        torch.tensor(cols, dtype=torch.long),
        torch.tensor(classes, dtype=torch.long),
        torch.tensor(thresholds, dtype=torch.float32),
    )
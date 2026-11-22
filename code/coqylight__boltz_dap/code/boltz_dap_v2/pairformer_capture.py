from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

import torch
import torch.distributed as dist
from torch import Tensor


class PairformerCaptureComplete(RuntimeError):
    """Signal that every rank committed a capture and may exit successfully."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _atomic_torch_save(value: Any, path: Path) -> None:
    temporary = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    try:
        torch.save(value, temporary)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _atomic_json_save(value: Any, path: Path) -> None:
    temporary = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    try:
        with temporary.open("w") as handle:
            json.dump(value, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _capture_provenance() -> dict[str, dict[str, Any]]:
    variables = {
        "input": "BOLTZ_PAIRFORMER_CAPTURE_INPUT",
        "manifest": "BOLTZ_PAIRFORMER_CAPTURE_MANIFEST",
        "checkpoint": "BOLTZ_PAIRFORMER_CAPTURE_CHECKPOINT",
        "accepted_memory_timeline": "BOLTZ_PAIRFORMER_CAPTURE_TIMELINE",
    }
    provenance = {}
    for label, variable in variables.items():
        raw_path = os.environ.get(variable, "").strip()
        if not raw_path:
            raise RuntimeError(f"capture requires {variable}")
        path = Path(raw_path).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(f"capture provenance file not found: {path}")
        digest = _sha256(path)
        expected = os.environ.get(f"{variable}_SHA256", "").strip().lower()
        if expected and digest != expected:
            raise RuntimeError(
                f"{label} SHA256 mismatch: expected {expected}, found {digest}"
            )
        provenance[label] = {
            "path": str(path),
            "bytes": path.stat().st_size,
            "sha256": digest,
        }
    return provenance


def _device_barrier() -> None:
    device = torch.cuda.current_device()
    try:
        dist.barrier(device_ids=[device])
    except TypeError:
        dist.barrier()


def maybe_capture_pairformer_entry(
    *,
    recycle_index: int,
    z: Tensor,
    s: Tensor,
    token_mask: Tensor,
    pair_mask: Tensor,
    original_n: int,
) -> None:
    """Atomically save the exact R0 main-Pairformer entry when requested."""
    capture_raw = os.environ.get("BOLTZ_PAIRFORMER_CAPTURE_DIR", "").strip()
    if not capture_raw or recycle_index != 0:
        return
    if not dist.is_initialized():
        raise RuntimeError("Pairformer capture requires initialized torch.distributed")

    capture_dir = Path(capture_raw).expanduser().resolve()
    capture_dir.mkdir(parents=True, exist_ok=True)
    rank = dist.get_rank()
    world_size = dist.get_world_size()
    local_rows = (original_n + world_size - 1) // world_size
    valid_rows = max(0, min(local_rows, original_n - rank * local_rows))

    expected_shapes = {
        "z": (1, local_rows, original_n, 128),
        "s": (1, original_n, 384),
        "token_mask": (1, original_n),
        "pair_mask": (1, local_rows, original_n),
    }
    tensors = {
        "z": z,
        "s": s,
        "token_mask": token_mask,
        "pair_mask": pair_mask,
    }
    for name, tensor in tensors.items():
        if tuple(tensor.shape) != expected_shapes[name]:
            raise RuntimeError(
                f"capture {name} shape {tuple(tensor.shape)} != {expected_shapes[name]}"
            )
    if z.dtype != torch.float32 or s.dtype != torch.float32:
        raise RuntimeError(f"capture requires FP32 z/s, found {z.dtype}/{s.dtype}")

    padded_rows = local_rows - valid_rows
    if padded_rows:
        if torch.count_nonzero(pair_mask[:, valid_rows:]).item() != 0:
            raise RuntimeError(f"rank {rank} pair-mask padding is not zero")
        if torch.count_nonzero(z[:, valid_rows:]).item() != 0:
            raise RuntimeError(f"rank {rank} z padding is not zero")

    free_bytes, total_bytes = torch.cuda.mem_get_info()
    local_metadata = {
        "rank": rank,
        "local_rank": int(os.environ.get("LOCAL_RANK", "0")),
        "cuda_device": torch.cuda.current_device(),
        "valid_rows": valid_rows,
        "padded_rows": padded_rows,
        "entry_memory": {
            "allocated_bytes": torch.cuda.memory_allocated(),
            "reserved_bytes": torch.cuda.memory_reserved(),
            "driver_free_bytes": free_bytes,
            "driver_total_bytes": total_bytes,
        },
    }

    shard_path = capture_dir / f"rank_{rank:03d}.pt"
    _atomic_torch_save(
        {
            "rank": rank,
            "valid_rows": valid_rows,
            "z": z.detach().to(device="cpu"),
            "pair_mask": pair_mask.detach().to(device="cpu"),
        },
        shard_path,
    )
    local_metadata["shard"] = {
        "path": shard_path.name,
        "bytes": shard_path.stat().st_size,
        "sha256": _sha256(shard_path),
    }

    if rank == 0:
        common_path = capture_dir / "common.pt"
        _atomic_torch_save(
            {
                "s": s.detach().to(device="cpu"),
                "token_mask": token_mask.detach().to(device="cpu"),
            },
            common_path,
        )
        local_metadata["common"] = {
            "path": common_path.name,
            "bytes": common_path.stat().st_size,
            "sha256": _sha256(common_path),
        }

    all_rank_metadata: list[dict[str, Any] | None] = [None] * world_size
    dist.all_gather_object(all_rank_metadata, local_metadata)
    _device_barrier()

    metadata_path = capture_dir / "metadata.json"
    if rank == 0:
        rank_zero = all_rank_metadata[0]
        assert rank_zero is not None
        metadata = {
            "format_version": 1,
            "capture_point": "R0/after_msa",
            "complete": True,
            "world_size": world_size,
            "original_n": original_n,
            "local_rows": local_rows,
            "dtypes": {
                name: str(tensor.dtype) for name, tensor in tensors.items()
            },
            "shapes": {
                name: list(shape) for name, shape in expected_shapes.items()
            },
            "common": rank_zero["common"],
            "ranks": all_rank_metadata,
            "provenance": _capture_provenance(),
            "runtime": {
                "torch": torch.__version__,
                "cuda": torch.version.cuda,
                "pytorch_cuda_alloc_conf": os.environ.get(
                    "PYTORCH_CUDA_ALLOC_CONF", ""
                ),
            },
        }
        _atomic_json_save(metadata, metadata_path)

    _device_barrier()
    raise PairformerCaptureComplete(str(metadata_path))
"""Versioned, lossless completed-trunk checkpoints without tensor gathers."""

from dataclasses import fields, is_dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import random

import numpy as np
from omegaconf import OmegaConf
import torch
import torch.distributed as dist

SCHEMA = 1
MIXED_SCHEMA = 2
STATE_KEYS = {"z", "s", "s_inputs"}


def build_context(model, features, forward_options, *, allow_mixed_precision=False):
    if model.training or not model.run_trunk_and_structure:
        raise ValueError("Trunk checkpoints require evaluation with the trunk enabled")
    active = [device for device in ("cuda", "cpu") if torch.is_autocast_enabled(device)]
    mixed = bool(active)
    if (len(active) > 1 or (mixed and (not allow_mixed_precision
            or torch.get_autocast_dtype(active[0]) != torch.bfloat16))
            or torch.backends.cuda.matmul.allow_tf32 or torch.backends.cudnn.allow_tf32):
        raise ValueError("Trunk checkpoints require strict FP32 without autocast or TF32")
    weights = model.state_dict()
    if any(value.is_floating_point() and value.dtype != torch.float32 for value in weights.values() if isinstance(value, torch.Tensor)):
        raise ValueError("Trunk checkpoint model weights must be FP32")
    ignored = {"BOLTZ_TRUNK_CHECKPOINT_SAVE", "BOLTZ_TRUNK_CHECKPOINT_RESUME", "BOLTZ_OUT_DIR"}
    environment = {name: value for name, value in os.environ.items() if name.startswith("BOLTZ_") and name not in ignored}
    if mixed and environment.get("BOLTZ_ORACLE_SOURCE_ROOT"):
        environment["BOLTZ_ORACLE_SOURCE_ROOT"] = str(Path(environment["BOLTZ_ORACLE_SOURCE_ROOT"]).resolve())
    root = Path(__file__).resolve().parents[2]
    sources = {}
    for relative in ("boltz/src/boltz", "boltz_dap/boltz_dap_v2", "boltz_dap/boltz_distributed"):
        for path in sorted((root / relative).rglob("*.py")):
            sources[str(path.relative_to(root))] = file_hash(path)
    configuration = {"forward": forward_options, "environment": environment,
                     "hyperparameters": dict(getattr(model, "hparams", {})),
                     "steering": getattr(model, "steering_args", None),
                     "use_templates": model.use_templates, "use_kernels": model.use_kernels,
                     "torch": str(torch.__version__), "cuda": torch.version.cuda,
                     "matmul_precision": torch.get_float32_matmul_precision(),
                     "deterministic_algorithms": torch.are_deterministic_algorithms_enabled(),
                     "cudnn_benchmark": torch.backends.cudnn.benchmark,
                     "cudnn_deterministic": torch.backends.cudnn.deterministic,
                     "gpu_name": torch.cuda.get_device_name() if torch.cuda.is_available() else None}
    if mixed:
        configuration.update(autocast_device=active[0], autocast_dtype="torch.bfloat16")
    context = {"schema": MIXED_SCHEMA if mixed else SCHEMA,
            "tokens": int(features["token_pad_mask"].shape[1]),
            "world_size": _world()[1], "input_sha256": fingerprint(features),
            "model_sha256": fingerprint(weights), "configuration_sha256": fingerprint(configuration),
            "source_sha256": fingerprint(sources), "dtype": "mixed" if mixed else "torch.float32"}
    if mixed:
        context["precision"] = "bf16-mixed"
    return context


def activation_dtype(name, context, key):
    if name == "torch.float32":
        return torch.float32
    if (name == "torch.bfloat16" and key in ("s", "s_inputs")
            and context.get("schema") == MIXED_SCHEMA and context.get("precision") == "bf16-mixed"):
        return torch.bfloat16
    raise ValueError("Checkpoint activation dtype is incompatible with its precision contract")


def validate_state_geometry(tensors, tokens, world):
    rows = (tokens + world - 1) // world
    pair = tensors["z"]
    if (pair.ndim != 4 or pair.shape[1] != rows or pair.shape[2] not in (tokens, rows * world)
            or any(tensors[name].ndim != 3 or tensors[name].shape[:2] != (pair.shape[0], tokens)
                   for name in ("s", "s_inputs"))):
        raise ValueError("Checkpoint tensor geometry does not match tokens and DAP size")


def file_hash(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def fingerprint(value):
    digest = hashlib.sha256()

    def visit(item):
        if OmegaConf.is_config(item):
            digest.update(b"omegaconf:")
            visit(OmegaConf.to_container(item, resolve=True, throw_on_missing=True))
        elif isinstance(item, torch.Tensor):
            digest.update(f"tensor:{item.dtype}:{list(item.shape)}:".encode())
            if not item.is_contiguous():
                item = item.contiguous()
            flat = item.detach().reshape(-1)
            for start in range(0, flat.numel(), 1024 * 1024):
                digest.update(flat[start:start + 1024 * 1024].cpu().view(torch.uint8).numpy().tobytes())
        elif isinstance(item, np.ndarray):
            digest.update(f"numpy:{item.dtype}:{item.shape}".encode())
            digest.update(item.tobytes())
        elif is_dataclass(item) and not isinstance(item, type):
            visit({field.name: getattr(item, field.name) for field in fields(item)})
        elif isinstance(item, dict):
            for key in sorted(item):
                visit(key)
                visit(item[key])
        elif isinstance(item, (tuple, list)):
            digest.update(f"{type(item).__name__}:{len(item)}".encode())
            for child in item:
                visit(child)
        elif isinstance(item, float) and not math.isfinite(item):
            digest.update(json.dumps([type(item).__name__, repr(float(item))], allow_nan=False).encode())
        elif item is None or isinstance(item, (str, int, float, bool)):
            digest.update(json.dumps([type(item).__name__, item], allow_nan=False).encode())
        else:
            raise TypeError(f"Unsupported checkpoint provenance value: {type(item).__name__}")

    visit(value)
    return digest.hexdigest()


def capture_rng(device):
    device = torch.device(device)
    return {"python": random.getstate(), "numpy": np.random.get_state(),
            "torch_cpu": torch.get_rng_state(),
            "torch_cuda": torch.cuda.get_rng_state(device) if device.type == "cuda" else None}


def restore_rng(state, device):
    device = torch.device(device)
    if (state["torch_cuda"] is None) != (device.type != "cuda"):
        raise ValueError("Checkpoint RNG device mismatch")
    random.setstate(state["python"])
    np.random.set_state(state["numpy"])
    torch.set_rng_state(state["torch_cpu"])
    if device.type == "cuda":
        torch.cuda.set_rng_state(state["torch_cuda"], device)


def _world():
    return (dist.get_rank(), dist.get_world_size()) if dist.is_initialized() else (0, 1)


def _agree(error):
    rank, world = _world()
    errors = [None] * world
    if world > 1:
        dist.all_gather_object(errors, error)
    else:
        errors[rank] = error
    failures = [message for message in errors if message is not None]
    if failures:
        raise RuntimeError("Checkpoint rejected: " + "; ".join(failures))


def _write_json(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("x") as stream:
        json.dump(value, stream, sort_keys=True, allow_nan=False)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def _write_tensor(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("xb") as stream:
        torch.save(value, stream)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def save(directory, tensors, context, chunk_rows=16):
    rank, world = _world()
    directory = Path(directory)
    error = None
    try:
        if set(tensors) != STATE_KEYS or chunk_rows < 1:
            raise ValueError("Expected z, s, s_inputs and positive chunk size")
        for name, value in tensors.items():
            if value.requires_grad or value.dtype != activation_dtype(str(value.dtype), context, name):
                raise ValueError("Checkpoint activations must be inference-only with their original dtype")
        validate_state_geometry(tensors, context["tokens"], world)
        if rank == 0:
            directory.mkdir(parents=True, exist_ok=False)
    except Exception as exception:
        error = repr(exception)
    _agree(error)
    rng = capture_rng(tensors["z"].device)
    schema = context.get("schema", SCHEMA)
    record = {"schema": schema, "rank": rank, "world_size": world, "context": context,
              "context_sha256": fingerprint(context), "state": {}, "files": {}}
    error = None
    try:
        for name in sorted(tensors):
            value = tensors[name]
            chunks = []
            rows_per_file = chunk_rows if name == "z" else value.shape[1]
            for start in range(0, value.shape[1], rows_per_file):
                end = min(start + rows_per_file, value.shape[1])
                filename = f"rank{rank:05d}_{name}_{start:08d}.pt"
                cpu = value[:, start:end].detach().to(device="cpu", copy=True).contiguous()
                if not torch.isfinite(cpu).all():
                    raise ValueError("Cannot checkpoint nonfinite activations")
                _write_tensor(directory / filename, cpu)
                record["files"][filename] = file_hash(directory / filename)
                chunks.append({"file": filename, "start": start, "end": end})
                del cpu
            record["state"][name] = {"shape": list(value.shape), "dtype": str(value.dtype), "chunks": chunks}
        rng_name = f"rank{rank:05d}_rng.pt"
        _write_tensor(directory / rng_name, rng)
        record["files"][rng_name] = file_hash(directory / rng_name)
        record["rng_file"] = rng_name
        _write_json(directory / f"rank{rank:05d}.json", record)
    except Exception as exception:
        error = repr(exception)
    _agree(error)
    error = None
    if rank == 0:
        try:
            rank_files = {}
            for owner in range(world):
                path = directory / f"rank{owner:05d}.json"
                entry = json.loads(path.read_text())
                if entry["rank"] != owner or entry["world_size"] != world or entry["context_sha256"] != fingerprint(context):
                    raise ValueError("Ranks disagree on checkpoint provenance")
                rank_files[path.name] = file_hash(path)
            _write_json(directory / "manifest.json", {"schema": schema, "boundary": "completed_trunk_before_conditioning",
                        "world_size": world, "context_sha256": fingerprint(context), "ranks": rank_files})
            _write_json(directory / "COMMITTED.json", {"manifest_sha256": file_hash(directory / "manifest.json")})
            descriptor = os.open(directory, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        except Exception as exception:
            error = repr(exception)
    _agree(error)


def inspect(directory, context):
    rank, world = _world()
    directory = Path(directory)
    committed = json.loads((directory / "COMMITTED.json").read_text())
    if file_hash(directory / "manifest.json") != committed["manifest_sha256"]:
        raise ValueError("Corrupt checkpoint manifest")
    manifest = json.loads((directory / "manifest.json").read_text())
    if (manifest["schema"] != context.get("schema", SCHEMA) or manifest["world_size"] != world
            or manifest["boundary"] != "completed_trunk_before_conditioning"
            or manifest["context_sha256"] != fingerprint(context)
            or set(manifest["ranks"]) != {f"rank{owner:05d}.json" for owner in range(world)}):
        raise ValueError("Incompatible checkpoint schema, rank count, boundary or provenance")
    for name, expected in manifest["ranks"].items():
        if file_hash(directory / name) != expected:
            raise ValueError("Missing or changed checkpoint rank metadata")
    record = json.loads((directory / f"rank{rank:05d}.json").read_text())
    if record["context"] != context or record["rank"] != rank or record["world_size"] != world or set(record["state"]) != STATE_KEYS:
        raise ValueError("Incompatible local checkpoint state")
    for name, expected in record["files"].items():
        if Path(name).name != name or not (directory / name).is_file():
            raise ValueError(f"Missing or invalid local checkpoint file: {name}")
        if file_hash(directory / name) != expected:
            raise ValueError(f"Corrupt local checkpoint file: {name}")
    for key, entry in record["state"].items():
        next_row = 0
        activation_dtype(entry["dtype"], context, key)
        if len(entry["shape"]) < 2:
            raise ValueError("Invalid checkpoint dtype or shape")
        for chunk in entry["chunks"]:
            if chunk["file"] not in record["files"] or chunk["start"] != next_row or not chunk["start"] < chunk["end"] <= entry["shape"][1]:
                raise ValueError("Incomplete or overlapping checkpoint chunks")
            next_row = chunk["end"]
        if next_row != entry["shape"][1]:
            raise ValueError("Missing checkpoint rows")
    return record


def load(directory, context, device):
    error, record = None, None
    try:
        record = inspect(directory, context)
    except Exception as exception:
        error = repr(exception)
    _agree(error)
    tensors, rng, error = {}, None, None
    try:
        for name, entry in record["state"].items():
            dtype = activation_dtype(entry["dtype"], context, name)
            value = torch.empty(entry["shape"], dtype=dtype, device=device)
            for chunk in entry["chunks"]:
                cpu = torch.load(Path(directory) / chunk["file"], map_location="cpu", weights_only=True)
                target = value[:, chunk["start"]:chunk["end"]]
                if cpu.dtype != dtype or cpu.shape != target.shape or not torch.isfinite(cpu).all():
                    raise ValueError("Invalid checkpoint tensor payload")
                target.copy_(cpu)
                del cpu
            tensors[name] = value
        rng = torch.load(Path(directory) / record["rng_file"], map_location="cpu", weights_only=False)
        validate_state_geometry(tensors, context["tokens"], _world()[1])
    except Exception as exception:
        error = repr(exception)
    _agree(error)
    restore_rng(rng, device)
    return tensors
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path
import random
from typing import Any

import torch
from torch import Tensor, nn


FORMAT_VERSION = 3


@dataclass(frozen=True)
class SnapshotPolicy:
    full_tensor_max_elements: int = 1_000_000
    sampled_elements: int = 4_096
    max_calls_per_boundary: int = 4
    sample_seed: int = 0

    def __post_init__(self) -> None:
        if self.full_tensor_max_elements < 0:
            raise ValueError("full_tensor_max_elements must be non-negative")
        if self.sampled_elements <= 0:
            raise ValueError("sampled_elements must be positive")
        if self.max_calls_per_boundary <= 0:
            raise ValueError("max_calls_per_boundary must be positive")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def file_provenance(path: Path) -> dict[str, Any]:
    resolved = path.expanduser().resolve(strict=True)
    if not resolved.is_file():
        raise FileNotFoundError(f"provenance path is not a file: {resolved}")
    return {
        "path": str(resolved),
        "bytes": resolved.stat().st_size,
        "sha256": sha256_file(resolved),
    }


def seed_all(seed: int) -> None:
    random.seed(seed)
    try:
        import numpy as np

        np.random.seed(seed)
    except ImportError:
        pass
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


def rng_state_hashes() -> dict[str, Any]:
    states: dict[str, Any] = {
        "python": hashlib.sha256(repr(random.getstate()).encode()).hexdigest(),
        "torch_cpu": _tensor_bytes_sha256(torch.get_rng_state()),
    }
    try:
        import numpy as np

        numpy_state = np.random.get_state()
        numpy_digest = hashlib.sha256()
        numpy_digest.update(numpy_state[0].encode())
        numpy_digest.update(numpy_state[1].tobytes())
        numpy_digest.update(str(numpy_state[2:]).encode())
        states["numpy"] = numpy_digest.hexdigest()
    except ImportError:
        states["numpy"] = None
    if torch.cuda.is_available():
        states["torch_cuda"] = [
            _tensor_bytes_sha256(state) for state in torch.cuda.get_rng_state_all()
        ]
    return states


def runtime_metadata() -> dict[str, Any]:
    cuda_device = None
    if torch.cuda.is_available():
        index = torch.cuda.current_device()
        cuda_device = {
            "index": index,
            "name": torch.cuda.get_device_name(index),
            "capability": list(torch.cuda.get_device_capability(index)),
        }
    return {
        "torch": str(torch.__version__),
        "cuda": torch.version.cuda,
        "cudnn": torch.backends.cudnn.version(),
        "cuda_device": cuda_device,
        "float32_matmul_precision": torch.get_float32_matmul_precision(),
        "cuda_matmul_allow_tf32": torch.backends.cuda.matmul.allow_tf32,
        "cudnn_allow_tf32": torch.backends.cudnn.allow_tf32,
        "deterministic_algorithms": torch.are_deterministic_algorithms_enabled(),
    }


class StockOracleRecorder:
    """Observe stock module boundaries without replacing their forward methods."""

    def __init__(
        self,
        output_dir: Path,
        *,
        policy: SnapshotPolicy | None = None,
        run_metadata: Mapping[str, Any] | None = None,
    ) -> None:
        self.output_dir = output_dir.expanduser().resolve()
        self.policy = policy or SnapshotPolicy()
        self.run_metadata = dict(run_metadata or {})
        self.comparison_metadata = {
            "run": dict(self.run_metadata),
            "runtime": runtime_metadata(),
        }
        self._captures: dict[str, list[dict[str, Any]]] = {}
        self._observed_calls: dict[str, int] = {}
        self._records: dict[str, Any] = {}
        self._handles: list[torch.utils.hooks.RemovableHandle] = []

    def register_boundary(
        self,
        name: str,
        module: nn.Module,
        *,
        capture_input: bool = True,
        capture_output: bool = True,
    ) -> None:
        if not name or name in self._captures:
            raise ValueError(f"boundary name must be non-empty and unique: {name!r}")
        self._captures[name] = []
        self._observed_calls[name] = 0

        def hook(
            _module: nn.Module,
            args: tuple[Any, ...],
            kwargs: dict[str, Any],
            output: Any,
        ) -> None:
            calls = self._captures[name]
            call_index = self._observed_calls[name]
            self._observed_calls[name] += 1
            if call_index >= self.policy.max_calls_per_boundary:
                return
            capture: dict[str, Any] = {"call_index": call_index}
            if capture_input:
                capture["args"] = self._snapshot_tree(args, f"{name}/{call_index}/args")
                capture["kwargs"] = self._snapshot_tree(
                    kwargs, f"{name}/{call_index}/kwargs"
                )
            if capture_output:
                capture["output"] = self._snapshot_tree(
                    output, f"{name}/{call_index}/output"
                )
            calls.append(capture)

        self._handles.append(module.register_forward_hook(hook, with_kwargs=True))

    def record(self, name: str, value: Any) -> None:
        if not name or name in self._records:
            raise ValueError(f"record name must be non-empty and unique: {name!r}")
        self._records[name] = self._snapshot_tree(value, f"records/{name}")

    def add_run_metadata(self, name: str, value: Any) -> None:
        if not name or name in self.run_metadata:
            raise ValueError(f"run metadata name must be non-empty and unique: {name!r}")
        self.run_metadata[name] = value

    def truncated_boundaries(self) -> dict[str, dict[str, int]]:
        return {
            name: {
                "observed_calls": self._observed_calls[name],
                "captured_calls": len(calls),
            }
            for name, calls in self._captures.items()
            if self._observed_calls[name] != len(calls)
        }

    def close_hooks(self) -> None:
        for handle in self._handles:
            handle.remove()
        self._handles.clear()

    def finalize(self) -> Path:
        self.close_hooks()
        self.output_dir.mkdir(parents=True, exist_ok=True)
        artifact_path = self.output_dir / "artifact.pt"
        metadata_path = self.output_dir / "metadata.json"
        complete = not self.truncated_boundaries()
        artifact = {
            "format_version": FORMAT_VERSION,
            "complete": complete,
            "comparison_metadata": self.comparison_metadata,
            "captures": self._captures,
            "boundary_observed_calls": dict(self._observed_calls),
            "records": self._records,
        }
        _atomic_torch_save(artifact, artifact_path)
        metadata = {
            "format_version": FORMAT_VERSION,
            "complete": complete,
            "artifact": {
                "path": artifact_path.name,
                "bytes": artifact_path.stat().st_size,
                "sha256": sha256_file(artifact_path),
            },
            "policy": asdict(self.policy),
            "run": self.run_metadata,
            "runtime": runtime_metadata(),
            "boundaries": {
                name: {
                    "observed_calls": self._observed_calls[name],
                    "captured_calls": len(calls),
                    "truncated": self._observed_calls[name] != len(calls),
                }
                for name, calls in self._captures.items()
            },
            "records": sorted(self._records),
        }
        _atomic_json_save(metadata, metadata_path)
        return metadata_path

    def _snapshot_tree(self, value: Any, path: str) -> Any:
        if isinstance(value, Tensor):
            return self._snapshot_tensor(value, path)
        if isinstance(value, Mapping):
            return {
                str(key): self._snapshot_tree(item, f"{path}/{key}")
                for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
            }
        if isinstance(value, tuple):
            return {
                "__sequence_type__": "tuple",
                "items": [
                    self._snapshot_tree(item, f"{path}/{index}")
                    for index, item in enumerate(value)
                ],
            }
        if isinstance(value, list):
            return {
                "__sequence_type__": "list",
                "items": [
                    self._snapshot_tree(item, f"{path}/{index}")
                    for index, item in enumerate(value)
                ],
            }
        if value is None or isinstance(value, (bool, int, float, str)):
            return value
        if isinstance(value, Path):
            return {"__path__": str(value)}
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            return {
                "__sequence_type__": type(value).__qualname__,
                "items": [
                    self._snapshot_tree(item, f"{path}/{index}")
                    for index, item in enumerate(value)
                ],
            }
        return {"__unsupported_type__": _qualified_type_name(value)}

    def _snapshot_tensor(self, tensor: Tensor, path: str) -> dict[str, Any]:
        detached = tensor.detach()
        numel = detached.numel()
        snapshot: dict[str, Any] = {
            "__tensor__": True,
            "shape": list(detached.shape),
            "dtype": str(detached.dtype),
            "source_device": str(detached.device),
            "requires_grad": tensor.requires_grad,
            "numel": numel,
        }
        if numel <= self.policy.full_tensor_max_elements:
            snapshot["storage"] = "full"
            snapshot["values"] = detached.to(device="cpu").clone()
            return snapshot

        count = min(self.policy.sampled_elements, numel)
        indices = _sample_indices(
            numel=numel,
            count=count,
            seed=self.policy.sample_seed,
            path=path,
        )
        coordinates = _flat_indices_to_coordinates(indices, detached.shape)
        device_coordinates = tuple(
            coordinate.to(device=detached.device) for coordinate in coordinates
        )
        snapshot["storage"] = "sampled"
        snapshot["flat_indices"] = indices
        snapshot["values"] = detached[device_coordinates].to(device="cpu").clone()
        return snapshot


def register_stock_boltz2_boundaries(
    recorder: StockOracleRecorder, model: nn.Module
) -> None:
    """Register Phase 0 hooks on an unmodified stock Boltz2 instance."""
    pairformer_module = _unwrap_compiled_module(model.pairformer_module)
    diffusion_conditioning = _unwrap_compiled_module(model.diffusion_conditioning)
    structure_module = _unwrap_compiled_module(model.structure_module)
    score_model = _unwrap_compiled_module(structure_module.score_model)

    recorder.register_boundary("trunk/pairformer", pairformer_module)
    recorder.register_boundary("trunk/distogram", model.distogram_module)
    recorder.register_boundary("diffusion/conditioning", diffusion_conditioning)
    recorder.register_boundary(
        "diffusion/conditioning/pairwise",
        diffusion_conditioning.pairwise_conditioner,
    )
    recorder.register_boundary(
        "diffusion/conditioning/atom_encoder",
        diffusion_conditioning.atom_encoder,
    )
    for index, module in enumerate(diffusion_conditioning.atom_enc_proj_z):
        recorder.register_boundary(
            f"diffusion/conditioning/atom_encoder_bias/{index}", module
        )
    for index, module in enumerate(diffusion_conditioning.atom_dec_proj_z):
        recorder.register_boundary(
            f"diffusion/conditioning/atom_decoder_bias/{index}", module
        )
    for index, module in enumerate(diffusion_conditioning.token_trans_proj_z):
        recorder.register_boundary(
            f"diffusion/conditioning/token_bias/{index}", module
        )

    recorder.register_boundary("diffusion/score_model", score_model)
    recorder.register_boundary(
        "diffusion/atom_encoder", score_model.atom_attention_encoder
    )
    for index, layer in enumerate(score_model.token_transformer.layers):
        recorder.register_boundary(f"diffusion/token_transformer/{index}", layer)
        recorder.register_boundary(
            f"diffusion/token_transformer/{index}/attention",
            layer.pair_bias_attn,
        )
    recorder.register_boundary(
        "diffusion/atom_decoder", score_model.atom_attention_decoder
    )

    if getattr(model, "confidence_module", None) is not None:
        confidence_module = _unwrap_compiled_module(model.confidence_module)
        recorder.register_boundary("confidence/module", confidence_module)
        recorder.register_boundary(
            "confidence/pairformer", confidence_module.pairformer_stack
        )
        recorder.register_boundary(
            "confidence/heads", confidence_module.confidence_heads
        )
        heads = confidence_module.confidence_heads
        for name in (
            "to_pae_logits",
            "to_pae_intra_logits",
            "to_pae_inter_logits",
            "to_pde_logits",
            "to_pde_intra_logits",
            "to_pde_inter_logits",
            "to_plddt_logits",
            "to_resolved_logits",
        ):
            module = getattr(heads, name, None)
            if module is not None:
                recorder.register_boundary(f"confidence/heads/{name}", module)


def compare_oracle_artifacts(reference_path: Path, candidate_path: Path) -> dict[str, Any]:
    reference = _load_artifact(reference_path)
    candidate = _load_artifact(candidate_path)
    reference_tensors = _flatten_tensor_snapshots(reference)
    candidate_tensors = _flatten_tensor_snapshots(candidate)
    reference_paths = set(reference_tensors)
    candidate_paths = set(candidate_tensors)
    common_paths = sorted(reference_paths & candidate_paths)
    comparisons = [
        _compare_tensor_snapshots(
            path,
            reference_tensors[path],
            candidate_tensors[path],
        )
        for path in common_paths
    ]
    reference_scalars = _flatten_scalar_leaves(reference)
    candidate_scalars = _flatten_scalar_leaves(candidate)
    reference_scalar_paths = set(reference_scalars)
    candidate_scalar_paths = set(candidate_scalars)
    common_scalar_paths = sorted(reference_scalar_paths & candidate_scalar_paths)
    unequal_scalars = [
        {
            "path": path,
            "reference": reference_scalars[path],
            "candidate": candidate_scalars[path],
        }
        for path in common_scalar_paths
        if reference_scalars[path] != candidate_scalars[path]
    ]
    return {
        "format_version": FORMAT_VERSION,
        "reference": str(reference_path.expanduser().resolve()),
        "candidate": str(candidate_path.expanduser().resolve()),
        "comparison_metadata_equal": (
            reference["comparison_metadata"] == candidate["comparison_metadata"]
        ),
        "missing_from_candidate": sorted(reference_paths - candidate_paths),
        "unexpected_in_candidate": sorted(candidate_paths - reference_paths),
        "missing_scalar_from_candidate": sorted(
            reference_scalar_paths - candidate_scalar_paths
        ),
        "unexpected_scalar_in_candidate": sorted(
            candidate_scalar_paths - reference_scalar_paths
        ),
        "unequal_scalars": unequal_scalars,
        "tensor_comparisons": comparisons,
        "summary": {
            "reference_tensor_count": len(reference_paths),
            "candidate_tensor_count": len(candidate_paths),
            "compared_tensor_count": len(common_paths),
            "bitwise_equal_count": sum(
                comparison["bitwise_equal"] for comparison in comparisons
            ),
            "full_tensor_comparison_count": sum(
                comparison["reference_storage"] == "full"
                for comparison in comparisons
            ),
            "sampled_tensor_comparison_count": sum(
                comparison["reference_storage"] == "sampled"
                for comparison in comparisons
            ),
            "shape_or_dtype_mismatch_count": sum(
                not comparison["comparable"] for comparison in comparisons
            ),
            "reference_scalar_count": len(reference_scalar_paths),
            "candidate_scalar_count": len(candidate_scalar_paths),
            "unequal_scalar_count": len(unequal_scalars),
        },
    }


def _load_artifact(path: Path) -> dict[str, Any]:
    resolved = path.expanduser().resolve(strict=True)
    if resolved.is_dir():
        resolved = resolved / "artifact.pt"
    artifact = torch.load(resolved, map_location="cpu", weights_only=True)
    if artifact.get("format_version") != FORMAT_VERSION:
        raise ValueError(
            f"unsupported artifact format {artifact.get('format_version')!r}"
        )
    if artifact.get("complete") is not True:
        raise ValueError(f"oracle artifact is incomplete: {resolved}")
    return artifact


def _flatten_tensor_snapshots(value: Any, path: str = "") -> dict[str, dict[str, Any]]:
    if isinstance(value, dict) and value.get("__tensor__") is True:
        return {path: value}
    flattened: dict[str, dict[str, Any]] = {}
    if isinstance(value, dict):
        for key, item in value.items():
            child_path = f"{path}/{key}" if path else str(key)
            flattened.update(_flatten_tensor_snapshots(item, child_path))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            child_path = f"{path}/{index}" if path else str(index)
            flattened.update(_flatten_tensor_snapshots(item, child_path))
    return flattened


def _flatten_scalar_leaves(value: Any, path: str = "") -> dict[str, Any]:
    if isinstance(value, dict) and value.get("__tensor__") is True:
        return {}
    flattened: dict[str, Any] = {}
    if isinstance(value, dict):
        for key, item in value.items():
            child_path = f"{path}/{key}" if path else str(key)
            flattened.update(_flatten_scalar_leaves(item, child_path))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            child_path = f"{path}/{index}" if path else str(index)
            flattened.update(_flatten_scalar_leaves(item, child_path))
    elif value is None or isinstance(value, (bool, int, float, str)):
        flattened[path] = value
    return flattened


def _compare_tensor_snapshots(
    path: str,
    reference: dict[str, Any],
    candidate: dict[str, Any],
) -> dict[str, Any]:
    comparable = all(
        reference[key] == candidate[key] for key in ("shape", "dtype", "storage")
    )
    if comparable and reference["storage"] == "sampled":
        comparable = torch.equal(reference["flat_indices"], candidate["flat_indices"])
    result: dict[str, Any] = {
        "path": path,
        "reference_shape": reference["shape"],
        "candidate_shape": candidate["shape"],
        "reference_dtype": reference["dtype"],
        "candidate_dtype": candidate["dtype"],
        "reference_storage": reference["storage"],
        "candidate_storage": candidate["storage"],
        "comparable": comparable,
        "bitwise_equal": False,
    }
    if not comparable:
        return result

    reference_values = reference["values"]
    candidate_values = candidate["values"]
    result["bitwise_equal"] = _tensor_bitwise_equal(
        reference_values, candidate_values
    )
    if not (reference_values.is_floating_point() or reference_values.is_complex()):
        result["value_equal"] = torch.equal(reference_values, candidate_values)
        return result

    reference_f64 = reference_values.to(torch.float64)
    candidate_f64 = candidate_values.to(torch.float64)
    finite_pair = torch.isfinite(reference_f64) & torch.isfinite(candidate_f64)
    finite_count = int(finite_pair.sum().item())
    result["reference_finite"] = int(torch.isfinite(reference_f64).sum().item())
    result["candidate_finite"] = int(torch.isfinite(candidate_f64).sum().item())
    result["compared_finite"] = finite_count
    if finite_count == 0:
        result.update(
            max_abs_error=None,
            mean_abs_error=None,
            rms_error=None,
            max_relative_error=None,
            mean_relative_error=None,
        )
        return result

    reference_finite = reference_f64[finite_pair]
    candidate_finite = candidate_f64[finite_pair]
    absolute_error = (candidate_finite - reference_finite).abs()
    denominator = reference_finite.abs().clamp_min(torch.finfo(torch.float64).tiny)
    relative_error = absolute_error / denominator
    result.update(
        max_abs_error=float(absolute_error.max().item()),
        mean_abs_error=float(absolute_error.mean().item()),
        rms_error=float(absolute_error.square().mean().sqrt().item()),
        max_relative_error=float(relative_error.max().item()),
        mean_relative_error=float(relative_error.mean().item()),
    )
    return result


def _sample_indices(*, numel: int, count: int, seed: int, path: str) -> Tensor:
    digest = hashlib.sha256(f"{seed}:{path}:{numel}".encode()).digest()
    start = int.from_bytes(digest[:8], "little", signed=False) % numel
    step = int.from_bytes(digest[8:16], "little", signed=False) % numel
    step = max(step, 1)
    while _greatest_common_divisor(step, numel) != 1:
        step = 1 if step + 1 == numel else step + 1
    return torch.tensor(
        [(start + index * step) % numel for index in range(count)],
        dtype=torch.int64,
    )


def _flat_indices_to_coordinates(
    indices: Tensor, shape: torch.Size
) -> tuple[Tensor, ...]:
    coordinates = []
    remaining = indices.clone()
    for size in reversed(shape):
        coordinates.append(remaining.remainder(size))
        remaining = torch.div(remaining, size, rounding_mode="floor")
    return tuple(reversed(coordinates))


def _tensor_bitwise_equal(reference: Tensor, candidate: Tensor) -> bool:
    if reference.shape != candidate.shape or reference.dtype != candidate.dtype:
        return False
    reference_bytes = reference.contiguous().reshape(-1).view(torch.uint8)
    candidate_bytes = candidate.contiguous().reshape(-1).view(torch.uint8)
    return torch.equal(reference_bytes, candidate_bytes)


def _tensor_bytes_sha256(tensor: Tensor) -> str:
    values = tensor.detach().to(device="cpu").contiguous().view(torch.uint8)
    return hashlib.sha256(values.numpy().tobytes()).hexdigest()


def _qualified_type_name(value: Any) -> str:
    value_type = type(value)
    return f"{value_type.__module__}.{value_type.__qualname__}"


def _greatest_common_divisor(left: int, right: int) -> int:
    while right:
        left, right = right, left % right
    return left


def _unwrap_compiled_module(module: nn.Module) -> nn.Module:
    return getattr(module, "_orig_mod", module)


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
"""Fold one protein sequence with a local ESMFold checkpoint."""
import argparse
import json
import math
import os
import warnings
from pathlib import Path

from Bio.PDB import PDBParser
from Bio.SeqUtils import seq1


MODEL_ID = "facebook/esmfold_v1"
MAX_SEQUENCE_LENGTH = 1022


def _find_cached_checkpoint(cache_home):
    cache_root = Path(cache_home) / "hub" / f"models--{MODEL_ID.replace('/', '--')}"
    snapshots = cache_root / "snapshots"
    if not snapshots.is_dir():
        return None

    refs = (cache_root / "refs" / "main",)
    preferred = []
    for ref in refs:
        if ref.is_file():
            preferred.append(snapshots / ref.read_text(encoding="utf-8").strip())
    preferred.extend(sorted(snapshots.iterdir(), key=lambda path: path.name, reverse=True))
    for snapshot in preferred:
        weights = snapshot / "pytorch_model.bin"
        if (
            (snapshot / "config.json").is_file()
            and weights.is_file()
            and weights.stat().st_size > 0
        ):
            return snapshot
    return None


def _install_tm_nan_guard(torch, esm_modeling):
    compute_tm = esm_modeling.compute_tm
    status = {"ptm_score_available": True}

    def compute_tm_for_inference(logits, *args, **kwargs):
        if not torch.isfinite(logits).all().item():
            status["ptm_score_available"] = False
            warnings.warn(
                "ESMFold produced non-finite pTM logits; omitting the optional pTM score. "
                "The protein coordinates will still be checked for finite values.",
                RuntimeWarning,
                stacklevel=2,
            )
            return logits.new_tensor(float("nan"))

        score = compute_tm(logits.float(), *args, **kwargs)
        if not torch.isfinite(score).all().item():
            status["ptm_score_available"] = False
            warnings.warn(
                "ESMFold produced a non-finite pTM score; omitting that optional score.",
                RuntimeWarning,
                stacklevel=2,
            )
            return score.new_tensor(float("nan"))
        return score

    esm_modeling.compute_tm = compute_tm_for_inference
    return status


def _inference_dtype(torch):
    return torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float32


def _infer_pdb_text(model, sequence, torch):
    output = model.infer(sequence)
    output = {
        name: value.float()
        if isinstance(value, torch.Tensor) and value.dtype == torch.bfloat16
        else value
        for name, value in output.items()
    }
    return model.output_to_pdb(output)[0]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--offload", type=Path, required=True)
    args = parser.parse_args()

    sequence = json.loads(args.request.read_text(encoding="utf-8"))["sequence"]
    if not sequence or len(sequence) > MAX_SEQUENCE_LENGTH:
        raise ValueError(f"ESMFold accepts sequences from 1 to {MAX_SEQUENCE_LENGTH} residues.")

    import torch
    from transformers import EsmForProteinFolding
    from transformers.models.esm import modeling_esmfold

    if not torch.cuda.is_available():
        raise RuntimeError("The isolated structure environment cannot access CUDA.")

    cache_home = Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface"))
    cached_checkpoint = _find_cached_checkpoint(cache_home)
    inference_dtype = _inference_dtype(torch)
    model_source = str(cached_checkpoint) if cached_checkpoint else MODEL_ID
    if cached_checkpoint:
        print(f"Using cached ESMFold checkpoint: {cached_checkpoint}", flush=True)
    else:
        print(f"Downloading ESMFold checkpoint for {MODEL_ID}.", flush=True)
    print(f"Using {inference_dtype} inference.", flush=True)

    tm_status = _install_tm_nan_guard(torch, modeling_esmfold)
    args.offload.mkdir(parents=True, exist_ok=True)
    memory = torch.cuda.get_device_properties(0).total_memory
    gpu_limit_gib = max(1, min(3, int((memory - 768 * 1024 * 1024) / (1024 ** 3))))
    model = EsmForProteinFolding.from_pretrained(
        model_source,
        dtype=inference_dtype,
        low_cpu_mem_usage=True,
        device_map="auto",
        max_memory={0: f"{gpu_limit_gib}GiB", "cpu": "2GiB"},
        offload_folder=str(args.offload),
        offload_state_dict=True,
        use_safetensors=False,
        local_files_only=cached_checkpoint is not None,
        cache_dir=str(cache_home),
    )
    model.eval()
    trunk = getattr(model, "trunk", None)
    if trunk is not None and hasattr(trunk, "set_chunk_size"):
        trunk.set_chunk_size(64)

    with torch.inference_mode():
        pdb_text = _infer_pdb_text(model, sequence, torch)
    if not isinstance(pdb_text, str) or "ATOM" not in pdb_text:
        raise RuntimeError("ESMFold returned no protein coordinates.")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(pdb_text, encoding="utf-8")
    structure = PDBParser(QUIET=True).get_structure("esmfold", str(args.output))
    atoms = list(structure.get_atoms())
    if not atoms or any(
        not all(math.isfinite(float(value)) for value in atom.coord)
        or not math.isfinite(float(atom.bfactor))
        for atom in atoms
    ):
        args.output.unlink(missing_ok=True)
        raise RuntimeError("ESMFold produced non-finite atom coordinates or confidence values.")
    chains = list(structure.get_chains())
    residues = [residue for chain in chains for residue in chain.get_residues()]
    predicted_sequence = "".join(seq1(residue.resname, custom_map={"UNK": "X"}) for residue in residues)
    if predicted_sequence != sequence:
        args.output.unlink(missing_ok=True)
        raise RuntimeError("The predicted coordinates do not contain the complete input sequence in order.")

    ca_confidence = [residue["CA"].get_bfactor() for residue in residues if "CA" in residue]
    if not ca_confidence or not all(math.isfinite(value) for value in ca_confidence):
        args.output.unlink(missing_ok=True)
        raise RuntimeError("ESMFold did not produce finite per-residue confidence values.")
    device_map = getattr(model, "hf_device_map", {})
    metadata = {
        "model": MODEL_ID,
        "checkpoint": str(cached_checkpoint) if cached_checkpoint else MODEL_ID,
        "sequence_length": len(sequence),
        "mean_plddt": sum(ca_confidence) / len(ca_confidence),
        "ptm_score_available": tm_status["ptm_score_available"],
        "gpu": torch.cuda.get_device_name(0),
        "torch": torch.__version__,
        "cuda_runtime": torch.version.cuda,
        "inference_dtype": str(inference_dtype),
        "device_map": {str(key): str(value) for key, value in device_map.items()},
    }
    args.metadata.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    print(json.dumps(metadata), flush=True)


if __name__ == "__main__":
    main()

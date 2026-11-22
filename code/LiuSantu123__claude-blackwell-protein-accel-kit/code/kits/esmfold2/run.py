"""Run ESMFold2 on a directory of protein-only inputs, sharing one model load."""

import argparse
import csv
import gc
import hashlib
import json
import os
import re
import time
from importlib.metadata import version
from pathlib import Path


SETTINGS = {
    'num_diffusion_samples': 1, 'num_loops': 20, 'num_sampling_steps': 200,
    'msa_max_depth': 1024, 'msa_column_mask_rate': 0.1, 'lm_dropout': 0.3,
}


def dump(path, value):
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(value, indent=2, allow_nan=False) + '\n')
    temp.replace(path)


def read_design(path):
    specs = json.loads(path.read_text())['proteins']
    if not isinstance(specs, list) or not specs:
        raise ValueError(f'{path}: proteins must be a non-empty list')
    seen = set()
    proteins = []
    for spec in specs:
        chains = spec['chains']
        sequence = spec['sequence'].strip().upper()
        if (not isinstance(chains, list) or not chains or len(set(chains)) != len(chains)
            or any(not isinstance(chain, str) or not re.fullmatch(r'[A-Z]+', chain) for chain in chains)
            or seen.intersection(chains)):
            raise ValueError(f'{path}: expected unique uppercase chain IDs')
        if not re.fullmatch(r'[ACDEFGHIKLMNPQRSTVWYX]+', sequence):
            raise ValueError(f'{path}: expected an ungapped amino acid sequence')
        seen.update(chains)
        msa = (path.parent / spec['msa']).resolve(strict=True) if 'msa' in spec else None
        proteins.append((chains, sequence, msa))
    return proteins


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input_dir', type=Path, nargs='?')
    parser.add_argument('out', type=Path, nargs='?')
    parser.add_argument('--check', action='store_true', help='Run synthetic TriMul checks without model weights')
    parser.add_argument('--mode', choices=['blackwell', 'tiled', 'stock'], default='blackwell')
    parser.add_argument('--model', default=os.getenv('ESMFOLD2_WEIGHTS'), help='ESMFold2 checkpoint directory')
    parser.add_argument('--esmc', default=os.getenv('ESMFOLD2_ESMC'), help='ESMC-6B checkpoint directory')
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--loops', type=int, default=20)
    parser.add_argument('--steps', type=int, default=200)
    args = parser.parse_args()
    if args.check:
        if args.input_dir or args.out or args.mode != 'blackwell':
            parser.error('--check is a standalone Blackwell operator check')
    else:
        if not (args.input_dir and args.out and args.model and args.esmc):
            parser.error('provide INPUT_DIR, OUTPUT_DIR, and both checkpoint locations')
        sources = sorted(args.input_dir.glob('*.json'))
        if not sources:
            parser.error('no .json inputs found')
        if args.out.exists():
            parser.error('output directory already exists')
        if min(args.loops, args.steps) < 1:
            parser.error('--loops and --steps must be positive')
        designs = [(path.stem, read_design(path)) for path in sources]

    import numpy as np
    import torch
    from esm.models.esmfold2 import ESMFold2InputBuilder, EsmFold2Model, ProteinInput, StructurePredictionInput
    from esm.utils.msa import MSA

    if torch.cuda.device_count() != 1:
        parser.error('make exactly one allocated CUDA device visible before running')
    safe, checks = None, []
    if args.mode == 'blackwell':
        import blackwell_trimul as bw
        from preflight import select_tile

        if torch.cuda.get_device_capability() != (12, 0):
            parser.error('Blackwell mode requires compute capability 12.0')
        safe, checks = select_tile()
        torch.cuda.empty_cache()
    if args.check:
        print(json.dumps({'gpu': torch.cuda.get_device_name(), 'tile': safe, 'checks': checks}, indent=2))
        return 0

    class RecordingBuilder(ESMFold2InputBuilder):
        def prepare_input(self, input, seed=None, device=None):
            features, chains = super().prepare_input(input, seed=seed, device=device)
            asym = features['asym_id'][0].cpu().numpy()
            self.asym_ids = asym
            self.chain_map = {chain.asym_id: chain.chain_id for chain in chains}
            self.token_chains = np.array([self.chain_map[index] for index in asym])
            self.residue_indices = features['residue_index'][0].cpu().numpy()
            self.msa_rows = features['msa'].shape[1]
            return features, chains

    args.out.mkdir(parents=True)
    for name in ('structures', 'confidences'):
        (args.out / name).mkdir()
    settings = dict(SETTINGS, seed=args.seed, num_loops=args.loops, num_sampling_steps=args.steps)
    start = time.monotonic()
    model = EsmFold2Model.from_pretrained(args.model, device='cuda', load_esmc=False)
    model.load_esmc(args.esmc, precision='bf16')
    model.eval()
    hits, disabled = {}, set()
    if args.mode != 'stock':
        from tile_triangle import enable_esmc_offload, enable_row_tiling

        model.set_chunk_size(32)
        enable_esmc_offload(model)
        enable_row_tiling(model, tile_rows=64)
        if args.mode == 'blackwell':
            _, hits, disabled = bw.enable(model, safe=safe, row_block=128)
    summary = dict(mode=args.mode, gpu=torch.cuda.get_device_name(), esm=version('esm'),
                   torch=torch.__version__, triton=version('triton'), settings=settings,
                   model=args.model, esmc=args.esmc, esmc_precision='bf16',
                   load_seconds=time.monotonic() - start, results=[])
    if checks:
        dump(args.out / 'preflight.json', {'tile': safe, 'checks': checks})
    builder = RecordingBuilder()
    msa_cache = {}
    for name, proteins in designs:
        inputs = []
        fingerprints = []
        for chains, sequence, msa_path in proteins:
            if msa_path is not None and msa_path not in msa_cache:
                msa_cache[msa_path] = (MSA.from_a3m(msa_path), hashlib.sha256(msa_path.read_bytes()).hexdigest())
            msa, msa_hash = msa_cache[msa_path] if msa_path is not None else (None, None)
            if msa is not None and (msa.depth < 2 or msa.sequences[0] != sequence):
                raise ValueError(f'{name}: A3M needs a matching query and at least one homolog')
            inputs.append(ProteinInput(id=chains if len(chains) > 1 else chains[0], sequence=sequence, msa=msa))
            fingerprints.append({'chains': chains, 'sequence_sha256': hashlib.sha256(sequence.encode()).hexdigest(),
                                 'msa_sha256': msa_hash})
        design = StructurePredictionInput(sequences=inputs)
        torch.cuda.empty_cache()
        torch.cuda.reset_peak_memory_stats()
        start = time.monotonic()
        previous_hits = dict(hits)
        row = {'design': name, 'inputs': fingerprints}
        try:
            with torch.inference_mode():
                result = builder.fold(model, design, complex_id=name, **settings)
            torch.cuda.synchronize()
        except torch.cuda.OutOfMemoryError as error:
            row.update(status='oom', error=str(error))
        else:
            row['status'] = 'ok'
        row.update(seconds=time.monotonic() - start,
                   peak_allocated_mib=torch.cuda.max_memory_allocated() / 2**20,
                   peak_reserved_mib=torch.cuda.max_memory_reserved() / 2**20,
                   trimul_calls={key: value - previous_hits.get(key, 0) for key, value in hits.items()})
        if row['status'] == 'ok':
            pae = result.pae.float().cpu().numpy()
            plddt = result.plddt.float().cpu().numpy()
            iptm = result.pair_chains_iptm.float().cpu().numpy()
            tokens, chains = len(builder.token_chains), len(builder.chain_map)
            if (pae.shape != (tokens, tokens) or plddt.shape != (tokens,) or iptm.shape != (chains, chains)
                or not all(np.isfinite(array).all() for array in (pae, plddt, iptm))):
                raise ValueError(f'{name}: invalid confidence array')
            structure = f'structures/{name}_model.cif'
            confidence = f'confidences/{name}_confidences.npz'
            (args.out / structure).write_text(result.complex.to_mmcif())
            np.savez_compressed(args.out / confidence, pae=pae, plddt=plddt, pair_chains_iptm=iptm,
                                token_chain_ids=builder.token_chains, residue_index=builder.residue_indices)
            row.update(structure=structure, confidence=confidence, feature_msa_rows=builder.msa_rows,
                       ptm=None if result.ptm is None else float(result.ptm),
                       iptm=None if result.iptm is None else float(result.iptm),
                       chain_order=[builder.chain_map[index] for index in range(chains)])
            del result
        else:
            gc.collect()
            torch.cuda.empty_cache()
        summary['results'].append(row)
        summary.update(finished=False, fallback_modules=sorted(disabled))
        dump(args.out / 'summary.json', summary)
        print(f'{name}: {row["status"]}; {row["seconds"]:.3f} s; {row["trimul_calls"]}', flush=True)
    fields = ('design', 'status', 'ptm', 'iptm', 'seconds', 'peak_allocated_mib', 'peak_reserved_mib')
    with (args.out / 'ranking.csv').open('w', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(sorted(summary['results'], key=lambda row: -(row.get('iptm') or row.get('ptm') or 0)))
    dump(args.out / 'index.json', {row['design']: {key: row[key] for key in ('structure', 'confidence')}
                                 for row in summary['results'] if row['status'] == 'ok'})
    summary['finished'] = True
    dump(args.out / 'summary.json', summary)
    return int(any(row['status'] != 'ok' for row in summary['results']))


if __name__ == '__main__':
    raise SystemExit(main())

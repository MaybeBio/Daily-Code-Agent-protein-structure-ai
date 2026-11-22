"""Run an exported CPI pair in a separate Linux BioEmu2 GPU environment.

This file is included in the site's request ZIP; it has no local-app imports.
"""
import argparse
import hashlib
import importlib.metadata
import json
import platform
from pathlib import Path
import traceback
import zipfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--request', type=Path, default=Path('request.json'))
    parser.add_argument('--out', type=Path, default=Path('bioemu2_output'))
    parser.add_argument('--steps', type=int, default=10,
                        help='Successive motion steps; 0 means one predicted pose.')
    parser.add_argument('--lag-ns', type=float, default=1.0)
    parser.add_argument('--seed', type=int, default=42)
    args = parser.parse_args()
    if not 0 <= args.steps <= 100 or not 1 <= args.lag_ns <= 1000:
        parser.error('Use 0 to 100 steps and a lag of 1 to 1000 nanoseconds.')
    if platform.system() != 'Linux':
        parser.error('BioEmu-2 needs a Linux GPU machine. Run this in your remote Linux terminal.')
    if args.out.exists():
        parser.error('This output folder already exists. Choose a new --out folder to preserve earlier results.')
    request = json.loads(args.request.read_text(encoding='utf-8'))
    expected = hashlib.sha256((request['smiles'] + '|' + request['sequence']).encode()).hexdigest()
    if request['pair_id'] != expected or request['schema'] != 'cpi-bioemu2-request-v1':
        parser.error('The pair request was changed or is invalid. Download it again from the CPI site.')
    args.out.mkdir(parents=True)
    status_path = args.out / 'status.json'

    def status(stage, **extra):
        status_path.write_text(json.dumps(dict(stage=stage, **extra), indent=2), encoding='utf-8')
        print(stage, flush=True)

    try:
        status('Checking GPU and packages')
        import torch
        import numpy as np
        from bioemu2 import (load_system_and_contacts, load_model, predict_structure,
                            simulate_trajectory, check_physicality, save_frames)
        if not torch.cuda.is_available():
            raise RuntimeError('No usable NVIDIA GPU was found. Enable the remote GPU and check its driver.')
        system_data = dict(entities=[
            dict(entity_type='protein', asym_ids=['A'], sequence=request['sequence'], mods=[]),
            dict(entity_type='ligand', asym_ids=['L'], smiles=request['smiles'])],
            bonds=[], asym_id_to_author_id={})
        # JSON is a YAML subset; writing JSON avoids quoting errors in SMILES.
        system_path = args.out / 'system.yaml'
        system_path.write_text(json.dumps(system_data, indent=2), encoding='utf-8')
        system, contacts = load_system_and_contacts(system_path)
        status('Loading model; first run may download model resources and sequence alignments')
        model = load_model()
        status('Predicting this protein-compound pair')
        start = predict_structure(system, model=model, contacts=contacts,
                                  num_samples=1, batch_size=1, seed=args.seed,
                                  output_dir=args.out / 'starting_pose')
        if args.steps:
            status('Generating successive motion frames')
            trajectory = simulate_trajectory(
                system, model=model, contacts=contacts, x0=start,
                lag_time_ns=args.lag_ns, num_trajectory_steps=args.steps,
                batch_size=1, seed=args.seed + 1)[0]
        else:
            trajectory = start
        status('Checking geometry and preparing the site result')
        physicality = check_physicality(trajectory, system=system)
        save_frames(trajectory, args.out / 'frames', physicality=physicality)
        # Preserve BioEmu atom ordering. Display heavy atoms; retain full CIF/XTC.
        heavy = [a for a in trajectory.topology.atoms if a.element.symbol not in ('H', 'D')]
        index_map = {a.index: i for i, a in enumerate(heavy)}
        chains = list(trajectory.topology.chains)
        if len(chains) != 2:
            raise RuntimeError('Expected one protein chain and one compound chain; cannot safely label this output.')
        protein_chain, ligand_chain = chains
        atoms = [dict(elem=a.element.symbol, atom=a.name, resn=a.residue.name,
                      resi=a.residue.index + 1, chain='A' if a.residue.chain == protein_chain else 'L',
                      role='protein' if a.residue.chain == protein_chain else 'ligand') for a in heavy]
        bonds = [[index_map[a.index], index_map[b.index]] for a, b in trajectory.topology.bonds
                 if a.index in index_map and b.index in index_map]
        xyz = np.asarray(trajectory.xyz[:, [a.index for a in heavy], :], dtype=float) * 10.0
        if not np.isfinite(xyz).all():
            raise RuntimeError('The model produced invalid coordinates. No site result was created.')
        times = (np.asarray(trajectory.time, dtype=float) / 1000).tolist() if args.steps else [0.0]
        payload = dict(schema='cpi-bioemu2-result-v1', pair_id=request['pair_id'],
                       smiles=request['smiles'], sequence=request['sequence'],
                       source='BioEmu-2', kind='trajectory' if args.steps else 'pose',
                       units='angstrom', time_units='ns', times_ns=times,
                       atoms=atoms, bonds=bonds, frames=np.round(xyz, 5).tolist(),
                       physicality=dict(checked=bool(physicality.checked),
                                        passed=[bool(p) for p in physicality.passed],
                                        reasons=[str(r) for r in physicality.reasons]),
                       settings=dict(steps=args.steps, lag_ns=args.lag_ns, seed=args.seed),
                       environment=dict(python=platform.python_version(),
                                        bioemu2=importlib.metadata.version('bioemu2'),
                                        torch=torch.__version__, gpu=torch.cuda.get_device_name(0)))
        (args.out / 'result.json').write_text(json.dumps(payload, allow_nan=False), encoding='utf-8')
        (args.out / 'request.json').write_text(json.dumps(request, indent=2), encoding='utf-8')
        archive = args.out / 'cpi_bioemu2_result.zip'
        with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as z:
            for name in ('result.json', 'request.json', 'system.yaml'):
                z.write(args.out / name, name)
            for name in ('topology.cif', 'samples.xtc', 'physicality.json'):
                z.write(args.out / 'frames' / name, name)
        status('Completed', result_zip=str(archive.resolve()), frames=len(times),
               passing_frames=sum(payload['physicality']['passed']))
        print('Download this ZIP and import it in the CPI site:', archive, flush=True)
    except Exception as exc:
        text = str(exc)
        if 'out of memory' in text.lower():
            simple = 'The GPU ran out of memory. Use a GPU with more memory; the full protein was not shortened.'
        elif 'No module named' in text:
            simple = 'A required package is missing. Activate the BioEmu-2 environment and complete installation.'
        else:
            simple = 'BioEmu-2 could not finish. Read error.txt for the exact cause; no successful result is claimed.'
        (args.out / 'error.txt').write_text(traceback.format_exc(), encoding='utf-8')
        status('Failed', message=simple, detail=text)
        raise SystemExit(simple) from exc


if __name__ == '__main__':
    main()

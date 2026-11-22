"""Portable, once-only BF16 full60 preparation and Slurm execution controls."""

import argparse
from contextlib import contextmanager
import hashlib
import inspect
import json
import os
from pathlib import Path
import runpy
import socket
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch


RELEASE = Path(__file__).resolve().parents[1]
STEERING = dict(fk_steering=True, num_particles=3, fk_lambda=4.0,
    fk_resampling_interval=3, physical_guidance_update=True,
    contact_guidance_update=True, num_gd_steps=20)


def digest(path):
    with Path(path).open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x') as handle:
        json.dump(value, handle, indent=2, allow_nan=False)
        handle.write('\n')


def load_profile():
    return json.loads((RELEASE / 'repro/full60_bf16.json').read_text())


def cache_files(cache, canonical_tokens):
    return [cache / 'boltz2_conf.ckpt', *(cache / 'mols' / (token + '.pkl') for token in canonical_tokens)]


def validate_document(document):
    sequences = document.get('sequences', [])
    if not sequences or document.get('constraints'):
        raise ValueError('A protein-only capsid without explicit restraints is required')
    chains, lengths = [], set()
    for entry in sequences:
        if set(entry) != {'protein'}:
            raise ValueError('Only protein sequences are supported by this profile')
        protein = entry['protein']
        identifiers = protein['id'] if isinstance(protein['id'], list) else [protein['id']]
        chains.extend(identifiers)
        sequence = protein['sequence']
        if not sequence or not sequence.isalpha() or sequence != sequence.upper():
            raise ValueError('Expected an uppercase protein sequence')
        lengths.add(len(sequence))
        if not isinstance(protein.get('msa'), str) or protein['msa'] == 'empty':
            raise ValueError('An explicit local MSA is required; no automatic MSA requests')
    if len(chains) != 60 or len(set(chains)) != 60 or len(lengths) != 1:
        raise ValueError('Exactly 60 unique, equally sized protein chains are required')
    templates = document.get('templates', [])
    if not templates or any(not item.get('cif') or item.get('force', False)
                            or item.get('freeze', False) for item in templates):
        raise ValueError('Local, soft, unfrozen CIF templates are required')
    return dict(chains=chains, residues_per_chain=next(iter(lengths)), tokens=60 * next(iter(lengths)))


def environment(profile, native_source):
    values = {key: value for key, value in os.environ.items() if not key.startswith('BOLTZ_')}
    values.update(profile['environment'])
    values.update(PYTHONNOUSERSITE='1', PYTHONDONTWRITEBYTECODE='1',
        PYTHONPATH=os.pathsep.join(map(str, (native_source, RELEASE, RELEASE / 'boltz_dap_v2'))),
        BOLTZ_ORACLE_SOURCE_ROOT=str(native_source), CUBLAS_WORKSPACE_CONFIG=':4096:8',
        OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1')
    return values


def runner_arguments(run, binding):
    return [str(run / 'input.yaml'), '--out_dir', str(run / 'work'),
        '--cache', binding['cache'], '--skip_processing',
        '--execution-mode', 'candidate_sharded_fp32', '--compact-feature-ingress',
        '--num-workers', '0', '--candidate-token-query-rows', '128',
        '--candidate-atom-window-rows', '32', '--recycling_steps', '3',
        '--sampling_steps', '200', '--diffusion_samples', '1', '--seed', str(binding['seed']),
        '--write_full_pae', '--write_full_pde', '--no_save_zs_tensors',
        '--dc_pairwise_chunk_size', '32', '--dc_token_bias_chunk_size', '32',
        '--dc_atom_encoder_chunk_size', '64', '--dc_atom_window_chunk_size', '8',
        '--template-t-chunk-size', '1', '--nccl-timeout-seconds', '43200',
        '--precision', 'bf16-mixed', '--use_potentials']


def verify_release(native_source):
    listing = json.loads((RELEASE / 'release_allowlist.json').read_text())
    for entry in listing['files']:
        if digest(RELEASE / entry['destination']) != entry['sha256']:
            raise ValueError('Release file changed: ' + entry['destination'])
    native = json.loads((RELEASE / 'patches/boltz-2.2.1/manifest.json').read_text())
    for entry in native['files']:
        path = native_source / entry['path'].removeprefix('src/')
        if not path.is_file() or digest(path) != entry['after_sha256']:
            raise ValueError('Native Boltz source is not the qualified patched source: ' + entry['path'])


def verify_run(run, expected, *, external=False):
    path = run / 'binding.json'
    if digest(path) != expected:
        raise ValueError('Run binding hash changed')
    binding = json.loads(path.read_text())
    if digest(RELEASE / 'release_allowlist.json') != binding['release_allowlist_sha256']:
        raise ValueError('Prepared run belongs to a different release allowlist')
    verify_release(Path(binding['native_source']))
    for relative, expected_hash in binding['files'].items():
        if digest(run / relative) != expected_hash:
            raise ValueError('Prepared input changed: ' + relative)
    if external:
        for path, expected_hash in binding['external_files'].items():
            if digest(Path(path)) != expected_hash:
                raise ValueError('External cache, template, or MSA changed: ' + path)
    return binding


def prepare(args):
    import yaml

    if args.run.exists():
        raise FileExistsError(args.run)
    if not 0 <= args.seed < 2**31:
        raise ValueError('An explicit seed in [0, 2**31) is required')
    document = yaml.safe_load(args.input.read_text())
    dimensions = validate_document(document)
    external = {}
    for item in document['sequences']:
        path = (args.input.parent / item['protein']['msa']).resolve()
        item['protein']['msa'] = str(path)
        external[str(path)] = digest(path)
    for item in document['templates']:
        path = (args.input.parent / item['cif']).resolve()
        item['cif'] = str(path)
        external[str(path)] = digest(path)
    cache, native_source = args.cache.resolve(), args.native_source.resolve()
    verify_release(native_source)
    sys.path.insert(0, str(native_source))
    try:
        from boltz.data.const import canonical_tokens
    finally:
        sys.path.pop(0)
    for path in cache_files(cache, canonical_tokens):
        external[str(path)] = digest(path)
    args.run.mkdir(parents=True)
    source = args.run / 'input.yaml'
    source.write_text(yaml.safe_dump(document, sort_keys=False))
    preprocessing = (
        'from pathlib import Path; from boltz.main import process_inputs; '
        'process_inputs(data=[Path(__import__("sys").argv[1])], '
        'out_dir=Path(__import__("sys").argv[2]), '
        'ccd_path=Path(__import__("sys").argv[3])/"ccd.pkl", '
        'mol_dir=Path(__import__("sys").argv[3])/"mols", '
        'use_msa_server=False, msa_server_url="", msa_pairing_strategy="greedy", '
        'boltz2=True, preprocessing_threads=1, max_msa_seqs=8192)')
    subprocess.run([sys.executable, '-c', preprocessing, str(source), str(args.run / 'work'), str(cache)],
        env=dict(environment(load_profile(), native_source), CUDA_VISIBLE_DEVICES=''), check=True)
    records = list((args.run / 'work/processed/records').glob('*.json'))
    if len(records) != 1:
        raise ValueError('Exactly one processed record is required')
    record = json.loads(records[0].read_text())
    if (len(record['chains']) != 60
            or any(not chain['valid'] or chain['num_residues'] != dimensions['residues_per_chain']
                   for chain in record['chains'])
            or len(record['templates']) != 60
            or any(item['force'] or item['freeze'] for item in record['templates'])):
        raise ValueError('Processed topology/template admission failed')
    files = {str(path.relative_to(args.run)): digest(path)
             for path in args.run.rglob('*') if path.is_file()}
    write_json(args.run / 'binding.json', dict(seed=args.seed, cache=str(cache),
        native_source=str(native_source), profile=load_profile(), dimensions=dimensions,
        record_id=record['id'], files=files, external_files=external,
        release_allowlist_sha256=digest(RELEASE / 'release_allowlist.json'),
        automatic_retry=False, activation_resume=False, archives_enabled=False))
    print(json.dumps(dict(run=str(args.run), binding_sha256=digest(args.run / 'binding.json'))))


def node_preflight(args):
    binding = verify_run(args.run, args.expected_sha, external=True)
    memory = {line.split(':', 1)[0]: int(line.split()[1]) * 1024
              for line in Path('/proc/meminfo').read_text().splitlines() if line.split()[1].isdigit()}
    required = binding['profile']['maximum_node_host_gib'] * 2**30
    if memory['MemAvailable'] < required:
        raise ValueError('Insufficient allocated-node available host memory')
    write_json(args.run / 'admission' / f'node_{os.environ["SLURM_NODEID"]}.json',
        dict(host=socket.gethostname(), node=int(os.environ['SLURM_NODEID']),
            binding_sha256=args.expected_sha, job_id=os.environ['SLURM_JOB_ID'],
            shared_marker_sha256=digest(args.run / 'binding.json'), available_host_bytes=memory['MemAvailable']))


def gate(args, gpu=False):
    binding = verify_run(args.run, args.expected_sha)
    count = 32 if gpu else 4
    kind = 'gpu' if gpu else 'node'
    records = [json.loads((args.run / 'admission' / f'{kind}_{rank}.json').read_text()) for rank in range(count)]
    if len({record['host'] for record in records}) != 4:
        raise ValueError('Admission did not cover exactly four shared-storage nodes')
    for rank, record in enumerate(records):
        if (record['binding_sha256'] != args.expected_sha
                or record['job_id'] != os.environ['SLURM_JOB_ID']
                or record['rank' if gpu else 'node'] != rank
                or (gpu and (not record['passed'] or record['world_size'] != 32))):
            raise ValueError('Incomplete, stale, or mismatched allocated-node admission')
    write_json(args.run / 'admission' / f'{kind}_gate.json', dict(passed=True,
        binding_sha256=args.expected_sha, job_id=os.environ['SLURM_JOB_ID'], records=count))
    return binding


def launch_node(args):
    binding = verify_run(args.run, args.expected_sha)
    output = args.run / args.phase
    output.mkdir(exist_ok=True)
    command = [sys.executable, str(RELEASE / 'repro/held_port_launch.py'), str(output),
        '--nnodes=4', '--nproc_per_node=8', '--node_rank=' + os.environ['SLURM_NODEID'],
        '--master_addr=' + args.master, '--rdzv_backend=static', '--max_restarts=0',
        str(Path(__file__)), args.phase, '--run', str(args.run), '--expected-sha', args.expected_sha]
    subprocess.run(command, env=environment(binding['profile'], Path(binding['native_source'])), check=True)


def gpu_preflight(args):
    import torch
    import torch.distributed as distributed
    from boltz_distributed import init_dap
    from boltz_distributed.comm import row_to_col_destructive, col_to_row_streamed

    binding = verify_run(args.run, args.expected_sha)
    node_gate = json.loads((args.run / 'admission/node_gate.json').read_text())
    if node_gate['job_id'] != os.environ['SLURM_JOB_ID'] or node_gate['binding_sha256'] != args.expected_sha:
        raise ValueError('Missing current-job host admission')
    if int(os.environ['WORLD_SIZE']) != 32:
        raise ValueError('The qualified resource profile requires 32 ranks')
    init_dap()
    rank = distributed.get_rank()
    device = torch.device('cuda', int(os.environ['LOCAL_RANK']))
    properties = torch.cuda.get_device_properties(device)
    if not torch.cuda.is_bf16_supported() or properties.total_memory < 80000 * 2**20:
        raise ValueError('Device does not satisfy the BF16 full60 profile')
    with torch.no_grad():
        for dtype in (torch.float32, torch.bfloat16):
            full = torch.arange(64 * 33 * 2, dtype=torch.float32, device=device).reshape(1, 64, 33, 2).to(dtype)
            expected = full[:, rank * 2:(rank + 1) * 2].clone()
            source = expected.clone()
            column = row_to_col_destructive(source, host_staging=True)
            restored = col_to_row_streamed(column, 33, host_staging=True)
            torch.testing.assert_close(restored, expected, rtol=0, atol=0)
    write_json(args.run / 'admission' / f'gpu_{rank}.json', dict(rank=rank, world_size=32,
        host=socket.gethostname(), job_id=os.environ['SLURM_JOB_ID'], binding_sha256=args.expected_sha,
        passed=True, device=properties.name, gpu_total_bytes=properties.total_memory,
        scope='Small CUDA/NCCL FP32/BF16 staged-transport round trips; not full60 inference'))
    distributed.barrier()
    distributed.destroy_process_group()


def validate_execution(record):
    if (record['trunk_layers'] != 256 or record['confidence_layers'] != 8
            or record['confidence_calls'] != 1 or record['sampling_calls'] != 1
            or record['resampling_events'] < 1 or record['fused_attention_calls'] < 512
            or len(record['cache_receipts']) != 1 or not record['cache_receipts'][0]['closed']
            or record['cache_receipts'][0]['projection_precision'] != 'bf16-mixed'):
        raise ValueError('Incomplete fresh trunk, diffusion cache, sampling, or confidence execution')


@contextmanager
def execution_checks(binding, record):
    import torch
    import dap_trunk
    import dap_tri_att
    import dap_cached_token_attention
    from dap_pairformer import DAPPairformerLayer

    phase = 'trunk_layers'
    original_inject = dap_trunk.inject_dap_into_model
    original_confidence = dap_trunk.run_confidence_dap
    original_cache = dap_cached_token_attention.run_cached_diffusion_sampling
    original_fused = dap_tri_att._mha_q_chunked_fused
    original_multinomial = torch.multinomial
    original_reset = torch.cuda.reset_peak_memory_stats

    def layer_completed(module, arguments, output):
        if isinstance(module, DAPPairformerLayer):
            record[phase] += 1

    def cached(structure, *arguments, **keywords):
        output = original_cache(structure, *arguments, **keywords)
        record['cache_receipts'].append(dict(structure._dap_cache_receipt))
        return output

    def confidence(*arguments, **keywords):
        nonlocal phase
        if record['trunk_layers'] != 256 or len(record['cache_receipts']) != 1 or not record['cache_receipts'][0]['closed']:
            raise ValueError('Confidence requires a complete trunk and closed diffusion cache')
        record['confidence_calls'] += 1
        phase = 'confidence_layers'
        try:
            return original_confidence(*arguments, **keywords)
        finally:
            phase = 'trunk_layers'

    def fused(*arguments, **keywords):
        output = original_fused(*arguments, **keywords)
        record['fused_attention_calls'] += 1
        return output

    def multinomial(*arguments, **keywords):
        output = original_multinomial(*arguments, **keywords)
        step = inspect.currentframe().f_back.f_locals.get('step_idx')
        if isinstance(step, int) and 0 <= step < 199:
            record['resampling_events'] += 1
        return output

    def inject(model):
        model = original_inject(model)
        original_sample = model.structure_module.sample

        def sample(*arguments, **keywords):
            feats = keywords['feats']
            if (any(keywords['steering_args'].get(key) != value for key, value in STEERING.items())
                    or keywords['num_sampling_steps'] != 200 or keywords['multiplicity'] != 1
                    or feats['token_pad_mask'].shape[-1] != binding['dimensions']['tokens']
                    or feats['template_force'].any() or model.structure_module.step_scale != 1.5
                    or torch.is_autocast_enabled('cuda') or torch.backends.cuda.matmul.allow_tf32
                    or torch.backends.cudnn.allow_tf32):
                raise ValueError('Native sampling, precision, template, or steering contract changed')
            fixed = keywords.get('fixed_atom_mask')
            if fixed is not None and fixed.any():
                raise ValueError('Frozen atoms are forbidden')
            record['sampling_calls'] += 1
            return original_sample(*arguments, **keywords)

        model.structure_module.sample = sample
        return model

    def reset(device=None):
        record['peak_allocated_bytes'] = max(record['peak_allocated_bytes'], torch.cuda.max_memory_allocated(device))
        record['peak_reserved_bytes'] = max(record['peak_reserved_bytes'], torch.cuda.max_memory_reserved(device))
        return original_reset(device)

    hook = torch.nn.modules.module.register_module_forward_hook(layer_completed)
    try:
        with patch.object(dap_trunk, 'inject_dap_into_model', inject), \
                patch.object(dap_trunk, 'run_confidence_dap', confidence), \
                patch.object(dap_cached_token_attention, 'run_cached_diffusion_sampling', cached), \
                patch.object(dap_tri_att, '_mha_q_chunked_fused', fused), \
                patch.object(torch, 'multinomial', multinomial), \
                patch.object(torch.cuda, 'reset_peak_memory_stats', reset):
            yield
    finally:
        hook.remove()


def inference(args):
    import torch

    binding = verify_run(args.run, args.expected_sha)
    admission = json.loads((args.run / 'admission/gpu_gate.json').read_text())
    if admission['job_id'] != os.environ['SLURM_JOB_ID'] or admission['binding_sha256'] != args.expected_sha:
        raise ValueError('Missing current-job device admission')
    record = dict(rank=int(os.environ['RANK']), job_id=os.environ['SLURM_JOB_ID'],
        binding_sha256=args.expected_sha, trunk_layers=0, confidence_layers=0, confidence_calls=0,
        sampling_calls=0, resampling_events=0, fused_attention_calls=0, cache_receipts=[],
        peak_allocated_bytes=0, peak_reserved_bytes=0, passed=False)
    started = time.monotonic()
    runner = RELEASE / 'boltz_dap_v2/run_boltz_dap_v2.py'
    sys.argv = [str(runner), *runner_arguments(args.run, binding)]
    try:
        with execution_checks(binding, record):
            try:
                runpy.run_path(str(runner), run_name='__main__')
            except SystemExit as error:
                if error.code not in (0, None):
                    raise
        validate_execution(record)
        record['peak_allocated_bytes'] = max(record['peak_allocated_bytes'], torch.cuda.max_memory_allocated())
        record['peak_reserved_bytes'] = max(record['peak_reserved_bytes'], torch.cuda.max_memory_reserved())
        if record['peak_allocated_bytes'] > 80000 * 2**20:
            raise ValueError('Peak GPU allocation exceeded 80000 MiB')
        record['passed'] = True
    finally:
        record['elapsed_seconds'] = time.monotonic() - started
        write_json(args.run / 'execution' / f'rank_{record["rank"]}.json', record)


def postflight(args):
    import gemmi

    binding = verify_run(args.run, args.expected_sha)
    records = [json.loads((args.run / 'execution' / f'rank_{rank}.json').read_text()) for rank in range(32)]
    for rank, record in enumerate(records):
        validate_execution(record)
        if (record['rank'] != rank or not record['passed'] or record['binding_sha256'] != args.expected_sha
                or record['job_id'] != os.environ['SLURM_JOB_ID']):
            raise ValueError('Missing or inconsistent final rank receipt')
    output = args.run / 'work/predictions' / binding['record_id']
    name = binding['record_id']
    required = [output / f'{name}_model_0.cif', output / f'confidence_{name}_model_0.json',
        output / f'plddt_{name}_model_0.npz', output / f'pae_{name}_model_0.npz', output / f'pde_{name}_model_0.npz']
    for path in required:
        if not path.is_file() or path.stat().st_size == 0:
            raise ValueError('Missing final prediction output: ' + path.name)
    structure = gemmi.read_structure(str(required[0]))
    if len(structure) != 1 or len(structure[0]) != 60 or any(
            len(chain) != binding['dimensions']['residues_per_chain'] for chain in structure[0]):
        raise ValueError('Prediction does not contain the complete admitted capsid')
    write_json(args.run / 'full60_report.json', dict(operational_passed=True,
        resource_passed=False, host_memory_peak_verified=False,
        host_telemetry_note='Portable simultaneous node-peak telemetry remains unqualified; do not infer it from process RSS.',
        files={path.name: dict(sha256=digest(path), bytes=path.stat().st_size) for path in required},
        scope='Operational completion does not establish structural or biological accuracy.'))


def self_test():
    document = dict(sequences=[dict(protein=dict(id=[f'C{rank}' for rank in range(60)],
        sequence='ACDE', msa='local.csv'))], templates=[dict(cif='public.cif')])
    assert validate_document(document)['tokens'] == 240
    for key in ('force', 'freeze'):
        altered = json.loads(json.dumps(document))
        altered['templates'][0][key] = True
        try:
            validate_document(altered)
        except ValueError:
            pass
        else:
            raise AssertionError('Hard/frozen template was accepted')
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / 'receipt.json'
        write_json(path, dict(passed=True))
        try:
            write_json(path, dict(passed=False))
        except FileExistsError:
            pass
        else:
            raise AssertionError('Existing receipt was overwritten')
        arguments = runner_arguments(Path(directory), dict(cache='cache', seed=101))
        assert arguments[arguments.index('--seed') + 1] == '101'
        assert arguments[arguments.index('--sampling_steps') + 1] == '200'
        assert '--use_potentials' in arguments and '--no_save_zs_tensors' in arguments
        assert '--save-trunk-checkpoints' not in arguments
        assert cache_files(Path(directory), ['ALA']) == [Path(directory) / 'boltz2_conf.ckpt', Path(directory) / 'mols/ALA.pkl']
        profile = dict(environment={'BOLTZ_DAP_FUSED_TRI_ATT': '1'})
        with patch.dict(os.environ, {'BOLTZ_UNREVIEWED': 'reject'}):
            result = environment(profile, Path(directory))
        assert 'BOLTZ_UNREVIEWED' not in result
        assert result['BOLTZ_DAP_FUSED_TRI_ATT'] == '1'
    record = dict(trunk_layers=256, confidence_layers=8, confidence_calls=1, sampling_calls=1,
        resampling_events=1, fused_attention_calls=512,
        cache_receipts=[dict(closed=True, projection_precision='bf16-mixed')])
    validate_execution(record)
    for name in ('trunk_layers', 'confidence_layers', 'confidence_calls', 'sampling_calls', 'resampling_events', 'fused_attention_calls'):
        try:
            validate_execution(dict(record, **{name: 0}))
        except ValueError:
            pass
        else:
            raise AssertionError('Incomplete execution was accepted: ' + name)
    print('PASS: input contract, explicit seed/protocol, clean environment, and create-only receipts')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--self-test', action='store_true')
    subparsers = parser.add_subparsers(dest='action')
    preparing = subparsers.add_parser('prepare')
    preparing.add_argument('--input', type=Path, required=True)
    preparing.add_argument('--cache', type=Path, required=True)
    preparing.add_argument('--native-source', type=Path, required=True)
    preparing.add_argument('--seed', type=int, required=True)
    preparing.add_argument('--run', type=Path, required=True)
    for name in ('node-preflight', 'node-gate', 'gpu-gate', 'launch-node', 'gpu-preflight', 'inference', 'postflight'):
        command = subparsers.add_parser(name)
        command.add_argument('--run', type=lambda value: Path(value).resolve(), required=True)
        command.add_argument('--expected-sha', required=True)
        if name == 'launch-node':
            command.add_argument('--master', required=True)
            command.add_argument('--phase', choices=('gpu-preflight', 'inference'), required=True)
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    if args.action == 'prepare':
        args.input, args.run = args.input.resolve(), args.run.resolve()
        return prepare(args)
    actions = {'node-preflight': node_preflight, 'node-gate': gate,
        'gpu-gate': lambda selected: gate(selected, gpu=True), 'launch-node': launch_node}
    if args.action in actions:
        return actions[args.action](args)
    execution = {'gpu-preflight': gpu_preflight, 'inference': inference, 'postflight': postflight}
    if args.action in execution:
        return execution[args.action](args)
    parser.print_help()


if __name__ == '__main__':
    main()
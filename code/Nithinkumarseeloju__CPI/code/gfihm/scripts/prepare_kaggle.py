"""Package only score-training source/splits and a two-GPU Kaggle notebook."""
import ast,hashlib,json,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'kaggle';OUT.mkdir(exist_ok=True)
cells=[]
def md(text):cells.append(dict(cell_type='markdown',metadata={},source=text.splitlines(keepends=True)))
def code(text):
 ast.parse(text)
 cells.append(dict(cell_type='code',metadata={},execution_count=None,outputs=[],source=text.splitlines(keepends=True)))

md('''# CPI score training on Kaggle T4 x2
Upload `cpi_kaggle.zip` as a **private Kaggle Dataset**, attach that dataset to this notebook, and select **GPU T4 x2** and **Internet on** in notebook settings.

This notebook trains the recovered score architecture, not 3D coordinates or binding motion. Each training process uses one GPU: KIBA on GPU 0; Davis then Metz on GPU 1. The two GPUs do not automatically combine their memory or train one model twice as fast.

Full training is enabled by default. Run all cells in order: the notebook first measures two full-data epochs per dataset, prints runtime estimates, then automatically continues to **30 total epochs per dataset**. Change `TARGET_EPOCHS` in the first code cell if you want a different total. The final cell uses that configuration without resetting it.

Kaggle execution and T4 compatibility have not been verified from the local Windows environment. The notebook checks CUDA before training. Do not install the project's Windows/CPU requirements on Kaggle; keep its supplied PyTorch build.
''')
code('''from pathlib import Path
import os, sys, json, shutil, zipfile, subprocess, statistics, time
from concurrent.futures import ThreadPoolExecutor

ROOT = Path('/kaggle/working/cpi_project')
INPUT = Path('/kaggle/input')
TARGET_EPOCHS = 30             # Change to 150 if that is your intended experiment.
BATCH_SIZE = 16               # Keep unchanged when resuming this run.
RUN_FULL_TRAINING = True      # Run all cells to continue automatically to TARGET_EPOCHS.
RESTORE_ZIP = None            # Optional uploaded cpi_training_checkpoints.zip path.

def safe_extract(archive, destination, required_prefix=None):
    destination = destination.resolve()
    with zipfile.ZipFile(archive) as z:
        for member in z.infolist():
            target = (destination / member.filename).resolve()
            if not target.is_relative_to(destination):
                raise ValueError('Archive contains an unsafe path')
            if required_prefix and not member.filename.startswith(required_prefix):
                raise ValueError('Restore archive must contain only training_runs/')
        z.extractall(destination)

if not (ROOT / 'scripts/train_cpi.py').exists():
    archives = list(INPUT.rglob('cpi_kaggle.zip'))
    if len(archives) == 1:
        ROOT.mkdir(parents=True, exist_ok=True)
        safe_extract(archives[0], ROOT)
    else:
        # Kaggle may unpack an uploaded ZIP into its dataset directory.
        sources = [p.parent.parent for p in INPUT.rglob('train_cpi.py')
                   if p.parent.name == 'scripts' and
                   (p.parent.parent / 'model_source/chemprop').is_dir()]
        if len(sources) != 1:
            raise RuntimeError('Attach exactly one CPI training dataset, or specify its path in this cell.')
        shutil.copytree(sources[0], ROOT, dirs_exist_ok=True)

if RESTORE_ZIP:
    if (ROOT / 'training_runs').exists() and any((ROOT / 'training_runs').iterdir()):
        raise RuntimeError('Training outputs already exist; leave RESTORE_ZIP=None to continue those files.')
    safe_extract(Path(RESTORE_ZIP), ROOT, 'training_runs/')
print('Project copied to writable folder:', ROOT)
''')
code('''import torch
print('PyTorch:', torch.__version__, 'CUDA runtime:', torch.version.cuda)
assert torch.cuda.is_available(), 'Enable a GPU accelerator before continuing.'
assert torch.cuda.device_count() >= 2, 'This notebook schedule needs GPU T4 x2.'
for gpu in range(2):
    x = torch.ones((32, 32), device=f'cuda:{gpu}')
    assert (x @ x).sum().item() == 32768
    del x
    print(gpu, torch.cuda.get_device_name(gpu))
# Install only the additional training packages, preserving Kaggle's Torch.
subprocess.run([sys.executable, '-m', 'pip', 'install', '-r',
                str(ROOT / 'requirements-kaggle.txt')], check=True)
import importlib.metadata
versions = {name: importlib.metadata.version(name) for name in
            ['torch', 'rdkit', 'numpy', 'pandas', 'scipy', 'scikit-learn',
             'tape-proteins', 'typed-argument-parser', 'tensorboardX', 'lifelines']}
(ROOT / 'kaggle_environment.json').write_text(json.dumps(versions, indent=2))
print(versions)
''')
code('''LOGS = ROOT / 'kaggle_logs'
LOGS.mkdir(exist_ok=True)

def run_dataset(dataset, gpu, epochs):
    output = ROOT / 'training_runs' / dataset
    command = [sys.executable, '-u', str(ROOT / 'scripts/train_cpi.py'),
               '--dataset', dataset, '--device', 'cuda', '--epochs', str(epochs),
               '--batch-size', str(BATCH_SIZE), '--threads', '2']
    if (output / 'run_manifest.json').exists():
        command.append('--resume')
    env = dict(os.environ, CUDA_VISIBLE_DEVICES=str(gpu), PYTHONUNBUFFERED='1')
    log_path = LOGS / f'{dataset}.log'
    print(f'Starting/resuming {dataset} on physical GPU {gpu}; target {epochs} total epochs.', flush=True)
    print('Progress log:', log_path, flush=True)
    with log_path.open('a') as log:
        result = subprocess.run(command, cwd=ROOT, env=env,
                                stdout=log, stderr=subprocess.STDOUT)
    if result.returncode:
        tail = log_path.read_text(errors='replace')[-6000:]
        raise RuntimeError(f'{dataset} failed. Check the log before retrying.\\n{tail}')
    assert (output / 'fold_0/model_0/model.pt').is_file()
    assert (output / 'fold_0/model_0/resume.pt').is_file()
    print(dataset, 'finished this stage.', flush=True)

def run_two_gpus(epochs):
    def second_gpu():
        run_dataset('davis', 1, epochs)
        run_dataset('metz', 1, epochs)
    with ThreadPoolExecutor(max_workers=2) as executor:
        tasks = [executor.submit(run_dataset, 'kiba', 0, epochs),
                 executor.submit(second_gpu)]
        for task in tasks:
            task.result()

def save_snapshot():
    archive = Path('/kaggle/working/cpi_training_checkpoints.zip')
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as z:
        for path in (ROOT / 'training_runs').rglob('*'):
            if path.is_file():
                z.write(path, path.relative_to(ROOT).as_posix())
    print('Download/preserve this file from notebook output:', archive)
    return archive

run_two_gpus(2)
save_snapshot()
''')
md('''## Estimate from the actual GPUs
These are measured full-dataset epoch timings from this Kaggle session, not conversions from the earlier CPU benchmark. Remaining wall time assumes the same two-GPU schedule and batch size. Data loading, final testing and checkpoint writes add overhead. Performance and Kaggle session availability can change.
''')
code('''estimate = {}
for dataset in ['davis', 'kiba', 'metz']:
    output = ROOT / 'training_runs' / dataset
    timings = [json.loads(line) for line in (output / 'timings.jsonl').read_text().splitlines()]
    train = [r['seconds'] for r in timings if r['phase'] == 'training_epoch'][-2:]
    validation = [r['seconds'] for r in timings if r['phase'] == 'validation_epoch'][-2:]
    epoch_seconds = statistics.mean(train) + statistics.mean(validation)
    # This is a checkpoint just created by our own training run.
    state = torch.load(output / 'fold_0/model_0/resume.pt', map_location='cpu', weights_only=False)
    completed = int(state['epoch']) + 1
    del state
    estimate[dataset] = dict(measured_epoch_minutes=epoch_seconds / 60,
        completed_epochs=completed,
        hours_for_30_epochs=epoch_seconds * 30 / 3600,
        hours_for_150_epochs=epoch_seconds * 150 / 3600,
        remaining_hours=max(0, TARGET_EPOCHS - completed) * epoch_seconds / 3600)
    print(dataset, estimate[dataset])
remaining = max(estimate['kiba']['remaining_hours'],
                estimate['davis']['remaining_hours'] + estimate['metz']['remaining_hours'])
print(f'Estimated remaining wall time for all three with this T4 x2 schedule: {remaining:.2f} hours, plus overhead.')
(ROOT / 'kaggle_time_estimate.json').write_text(json.dumps(estimate, indent=2))
''')
md('''## Continue full training
This cell automatically continues to `TARGET_EPOCHS` using `RUN_FULL_TRAINING=True` from the first code cell. The default is 30 total epochs for each dataset, including the two calibration epochs. Check Kaggle's displayed session time/quota first; do not assume a fixed allowance. Keep the output ZIP and logs. Local notebook files and epoch checkpoints alone are not a guarantee that files will survive the end of a session.

To resume in a new session, attach the preserved checkpoint ZIP as a private dataset, set `RESTORE_ZIP` in the first code cell to its exact `/kaggle/input/...` path, and keep the same source data and batch size. The archive includes the run manifest, best checkpoint and optimizer/RNG resume state.
''')
code('''# Use the configuration from the first code cell; do not reset it here.
if RUN_FULL_TRAINING:
    try:
        run_two_gpus(TARGET_EPOCHS)
        print(f'Full training finished: {TARGET_EPOCHS} total epochs per dataset.', flush=True)
    finally:
        # Writes currently completed outputs if a process raises an error.
        # A forced session termination may prevent this cell from executing.
        save_snapshot()
else:
    print('Only the two-epoch calibration is complete. Full training has not been launched.')
''')
md('''## Download results
Download `/kaggle/working/cpi_training_checkpoints.zip`, plus `kaggle_environment.json`, `kaggle_time_estimate.json` and the logs under `/kaggle/working/cpi_project/`. Best models are `training_runs/<dataset>/fold_0/model_0/model.pt`; continuing training needs `resume.pt` and `run_manifest.json` too.

These are new score models on the prepared pair splits. Source proteins/compounds can occur individually on both sides of a split. Do not treat these results as a strict unseen-target benchmark or claim these models generate protein structures. Validate the new checkpoints before selecting them for the local app.
''')
for index,cell in enumerate(cells):cell['id']=f'cpi-{index:02d}'
notebook=dict(cells=cells,metadata=dict(kernelspec=dict(display_name='Python 3',language='python',name='python3'),language_info=dict(name='python',version='3.11')),nbformat=4,nbformat_minor=5)
(OUT/'CPI_T4x2.ipynb').write_text(json.dumps(notebook,indent=2),encoding='utf-8')
files=[ROOT/'scripts/train_cpi.py',ROOT/'requirements-kaggle.txt']
files+=list((ROOT/'model_source/chemprop').rglob('*.py'))
files+=[ROOT/'model_source/LICENSE.txt']
files+=[ROOT/f'processed/{dataset}/{split}.csv' for dataset in ('davis','kiba','metz') for split in ('train','val','test')]
with zipfile.ZipFile(OUT/'cpi_kaggle.zip','w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
 for path in sorted(files):z.write(path,path.relative_to(ROOT).as_posix())
with zipfile.ZipFile(OUT/'cpi_kaggle.zip') as z:
 assert z.testzip() is None
 assert all(not n.startswith(('.venv/','models/','processed/pdbbind/')) for n in z.namelist())
report=dict(bundle=str(OUT/'cpi_kaggle.zip'),bytes=(OUT/'cpi_kaggle.zip').stat().st_size,files=len(files),notebook_cells=len(cells),python_cells_syntax='PASS',zip_integrity='PASS',kaggle_gpu_execution='Not performed; requires the user Kaggle session',sha256=hashlib.sha256((OUT/'cpi_kaggle.zip').read_bytes()).hexdigest())
(OUT/'package_validation.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))

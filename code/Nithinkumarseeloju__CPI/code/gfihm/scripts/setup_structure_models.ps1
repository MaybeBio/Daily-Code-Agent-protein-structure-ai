$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$structureHome = Join-Path $env:LOCALAPPDATA 'cpi-fold-gpu'
$python = Join-Path $structureHome 'Scripts\python.exe'
$p2rank = Join-Path $structureHome 'p2rank_2.5.1'

if (-not (Test-Path $python)) {
    $basePython = Join-Path $root '.venv\Scripts\python.exe'
    if (-not (Test-Path $basePython)) { throw "Project Python was not found: $basePython" }
    & $basePython -m venv $structureHome
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the isolated structure environment.' }
}

& $python -m pip install --no-cache-dir -r (Join-Path $root 'model_source\requirements-gpu.txt')
if ($LASTEXITCODE -ne 0) { throw 'CUDA PyTorch installation failed.' }
& $python -m pip install --no-cache-dir -r (Join-Path $PSScriptRoot 'requirements-folding-gpu.txt')
if ($LASTEXITCODE -ne 0) { throw 'ESMFold Python dependencies failed to install.' }

$archive = Join-Path $structureHome 'p2rank_2.5.1.tar.gz'
if (-not (Test-Path $p2rank)) {
    curl.exe -L --fail --retry 3 -o $archive 'https://github.com/rdk/p2rank/releases/download/2.5.1/p2rank_2.5.1.tar.gz'
    if ($LASTEXITCODE -ne 0) { throw 'Could not download the official P2Rank release.' }
    tar.exe -xzf $archive -C $structureHome
    if ($LASTEXITCODE -ne 0) { throw 'Could not extract P2Rank.' }
}

& $python -c "import torch; from transformers import EsmForProteinFolding; print('PyTorch', torch.__version__, 'CUDA runtime', torch.version.cuda); assert torch.cuda.is_available(), 'CUDA is unavailable'; assert hasattr(EsmForProteinFolding, 'infer_pdb'), 'ESMFold inference is unavailable'"
if ($LASTEXITCODE -ne 0) { throw 'CUDA verification failed. Check the NVIDIA driver and CUDA wheel compatibility.' }

$java = Get-Command java -ErrorAction SilentlyContinue
if (-not $java) { throw 'Java 17 or newer is required for P2Rank.' }
& $java.Source -Xmx2048m -cp "$(Join-Path $p2rank 'bin\p2rank.jar');$(Join-Path $p2rank 'bin\lib')\*" cz.siret.prank.program.Main -v
if ($LASTEXITCODE -ne 0) { throw 'P2Rank verification failed.' }

Write-Output "Local structure environment ready: $structureHome"
Write-Output 'ESMFold model weights (~16.9 GB) download on the first sequence-docking request.'

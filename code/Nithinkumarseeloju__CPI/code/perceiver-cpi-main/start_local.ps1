param(
    [string]$Python = (Join-Path $PSScriptRoot ".venv\Scripts\python.exe"),
    [int]$AppPort = 8000,
    [int]$DockPort = 8010
)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
if (!(Test-Path $Python -PathType Leaf)) { throw "Missing project interpreter at $Python. See docs/LOCAL_SETUP.md." }
New-Item -ItemType Directory -Force ".runtime" | Out-Null
$config = ".runtime/local_servers.json"
if (Test-Path $config) {
    $saved = Get-Content $config -Raw | ConvertFrom-Json
    $active = @($saved.services | Where-Object {
        $owner = Get-NetTCPConnection -State Listen -LocalPort $_.port -ErrorAction SilentlyContinue
        $child = if ($owner) { Get-CimInstance Win32_Process -Filter "ProcessId=$($owner.OwningProcess)" }
        $child -and ($child.ProcessId -eq $_.pid -or $child.ParentProcessId -eq $_.pid)
    })
    if ($active.Count -eq 2) { Write-Output "Open $($saved.app_url)/"; return }
    if ($active.Count) { throw "Only one project service is running. Check .runtime logs and local_servers.json." }
}
function PortBusy([int]$Port) { [bool](Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) }
while (PortBusy $AppPort) { $AppPort++ }
while ((PortBusy $DockPort) -or $DockPort -eq $AppPort) { $DockPort++ }
$env:PERCEIVER_DOCKING_URL = "http://127.0.0.1:$DockPort"
$env:PERCEIVER_APP_URL = "http://127.0.0.1:$AppPort"
$env:PYTHONPATH = Join-Path $PSScriptRoot ".runtime\api-deps"
$env:PERCEIVER_PRELOAD = "0"
if (Test-Path ".runtime/assist-key.dpapi") {
    $encrypted = (Get-Content ".runtime/assist-key.dpapi" -Raw).Trim() | ConvertTo-SecureString
    $env:GEMINI_API_KEY = (New-Object System.Net.NetworkCredential("", $encrypted)).Password
}
$env:OMP_NUM_THREADS = "2"
$env:MKL_NUM_THREADS = "2"
$started = @()
try {
    foreach ($svc in @(@("docking", $DockPort, "local_service:app --app-dir docking/scripts", "/api/complexes"), @("affinity", $AppPort, "backend.app:app", "/"))) {
        $name, $port, $module, $health = $svc
        $child = Start-Process $Python -ArgumentList "-m uvicorn $module --host 127.0.0.1 --port $port" -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput ".runtime/$name.out.log" -RedirectStandardError ".runtime/$name.err.log"
        $started += @{ pid=$child.Id; port=$port }
        $ready = $false
        for ($i=0; $i -lt 120 -and !$child.HasExited; $i++) {
            try { $ready = (Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:$port$health" -TimeoutSec 2).StatusCode -eq 200 } catch {}
            if ($ready) { break }
            Start-Sleep -Milliseconds 500
        }
        if (!$ready) { throw "$name failed startup. See .runtime/$name.err.log." }
    }
    @{ app_url=$env:PERCEIVER_APP_URL; docking_url=$env:PERCEIVER_DOCKING_URL; services=$started } | ConvertTo-Json -Depth 3 | Set-Content -Encoding ASCII $config
} catch {
    foreach ($svc in $started) {
        if (Get-Process -Id $svc.pid -ErrorAction SilentlyContinue) { taskkill.exe /PID $svc.pid /T /F | Out-Null }
    }
    throw
}
Write-Output "Open $env:PERCEIVER_APP_URL/"

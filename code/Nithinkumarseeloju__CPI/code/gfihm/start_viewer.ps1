$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
& "$PSScriptRoot\.venv\Scripts\python.exe" "$PSScriptRoot\scripts\serve_viewer.py" --port 8765

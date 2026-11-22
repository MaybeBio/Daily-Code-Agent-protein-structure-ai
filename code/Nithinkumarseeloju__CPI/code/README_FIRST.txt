Bindsight local project
=======================

The active application is in perceiver-cpi-main. The gfihm folder is retained as
the 3D reference and source-data workspace.

Run on Windows PowerShell:

  Set-Location .\perceiver-cpi-main
  powershell -NoProfile -ExecutionPolicy Bypass -File .\start_local.ps1

Open the URL printed by the launcher. Detailed setup, model locations, docking
tools and validation commands are in perceiver-cpi-main\docs\LOCAL_SETUP.md.

Large generated runtime data, virtual environments, cached PDB structures and
the 3.7 GB P-L.zip archive are intentionally local because GitHub rejects files
over 100 MB. The trained affinity checkpoints required by the app are included.

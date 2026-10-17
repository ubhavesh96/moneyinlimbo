# Run the agent unit + smoke tests
Set-Location (Join-Path $PSScriptRoot "..")
.\.venv\Scripts\python.exe -m pytest -q

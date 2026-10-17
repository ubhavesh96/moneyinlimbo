# Start the ADK agent service on http://127.0.0.1:8001 (localhost only)
Set-Location (Join-Path $PSScriptRoot "..")
.\.venv\Scripts\python.exe -m uvicorn mil_agent.main:app --host 127.0.0.1 --port 8001

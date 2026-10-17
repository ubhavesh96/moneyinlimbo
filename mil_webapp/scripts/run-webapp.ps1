# Start the Django web app on http://127.0.0.1:8000 (needs the agent service on :8001)
Set-Location (Join-Path $PSScriptRoot "..")
.\.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8000

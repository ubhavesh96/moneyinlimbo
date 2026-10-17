# Start both services in two windows, then open http://127.0.0.1:8000
$root = $PSScriptRoot
Start-Process powershell -ArgumentList "-NoExit","-File","$root\mil_adk_agent\scripts\run-agent.ps1"
Start-Process powershell -ArgumentList "-NoExit","-File","$root\mil_webapp\scripts\run-webapp.ps1"
Start-Sleep 6; Start-Process "http://127.0.0.1:8000"

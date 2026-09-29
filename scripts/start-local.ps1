$ErrorActionPreference = 'Stop'
$projectDir = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $projectDir '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    python -m venv (Join-Path $projectDir '.venv')
    & $pythonPath -m pip install -r (Join-Path $projectDir 'backend\requirements.txt')
}
$outputDir = Join-Path $projectDir 'output'
New-Item -ItemType Directory -Force -Path $outputDir | Out-Null
$backendDir = Join-Path $projectDir 'backend'
$backend = Start-Process -FilePath $pythonPath -ArgumentList '-m','uvicorn','app.main:app','--host','127.0.0.1','--port','8000' -WorkingDirectory $backendDir -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $outputDir 'api.stdout.log') -RedirectStandardError (Join-Path $outputDir 'api.stderr.log')
Write-Output "API PID: $($backend.Id). Stop-Process -Id $($backend.Id) stops this API."
Push-Location (Join-Path $projectDir 'frontend')
try {
    if (-not (Test-Path -LiteralPath 'node_modules')) { npm ci }
    npm run dev
} finally { Pop-Location }

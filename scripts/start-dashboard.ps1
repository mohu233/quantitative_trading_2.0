$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot
$config = Get-Content -LiteralPath (Join-Path $projectRoot '.local.json') -Raw | ConvertFrom-Json
if (Get-NetTCPConnection -LocalPort $config.web_port -State Listen -ErrorAction SilentlyContinue) {
    Write-Host "Port $($config.web_port) is already in use. Check http://127.0.0.1:$($config.web_port)"
    exit 1
}
$logDir = Join-Path $projectRoot 'logs'
New-Item -ItemType Directory -Path $logDir -Force | Out-Null
$venvPython = Join-Path $projectRoot '.venv\Scripts\python.exe'
$pythonPath = if (Test-Path -LiteralPath $venvPython) { $venvPython } else { (Get-Command python).Source }
$process = Start-Process -FilePath $pythonPath -ArgumentList @('-m', 'quantitative_trading.dashboard') -WorkingDirectory $projectRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logDir 'server.out.log') -RedirectStandardError (Join-Path $logDir 'server.err.log') -PassThru
$process.Id | Set-Content -LiteralPath (Join-Path $projectRoot 'dashboard.pid')
Write-Host "Started PID $($process.Id): http://127.0.0.1:$($config.web_port)"

$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$config = Get-Content -LiteralPath (Join-Path $PSScriptRoot '.local.json') -Raw | ConvertFrom-Json
if (Get-NetTCPConnection -LocalPort $config.web_port -State Listen -ErrorAction SilentlyContinue) {
    Write-Host "Port $($config.web_port) is already in use. Check http://127.0.0.1:$($config.web_port)"
    exit 1
}
$logDir = Join-Path $PSScriptRoot 'logs'
New-Item -ItemType Directory -Path $logDir -Force | Out-Null
$pythonPath = (Get-Command python).Source
$process = Start-Process -FilePath $pythonPath -ArgumentList @('dashboard.py') -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logDir 'server.out.log') -RedirectStandardError (Join-Path $logDir 'server.err.log') -PassThru
$process.Id | Set-Content -LiteralPath (Join-Path $PSScriptRoot 'dashboard.pid')
Write-Host "Started PID $($process.Id): http://127.0.0.1:$($config.web_port)"

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$pidFile = Join-Path $projectRoot 'dashboard.pid'
if (Test-Path -LiteralPath $pidFile) {
    $taskPid = [int](Get-Content -LiteralPath $pidFile)
    $process = Get-CimInstance Win32_Process -Filter "ProcessId=$taskPid"
    if ($process -and $process.CommandLine -match '(dashboard\.py|-m\s+quantitative_trading\.dashboard)' -and $process.ExecutablePath -match 'python') {
        Stop-Process -Id $taskPid
        Remove-Item -LiteralPath $pidFile
        Write-Host 'Dashboard and collector stopped.'
    } else { Write-Host 'No matching dashboard process; nothing stopped.' }
}

$ErrorActionPreference = 'Stop'
$pidFile = Join-Path $PSScriptRoot 'dashboard.pid'
if (Test-Path -LiteralPath $pidFile) {
    $taskPid = [int](Get-Content -LiteralPath $pidFile)
    $process = Get-CimInstance Win32_Process -Filter "ProcessId=$taskPid"
    if ($process -and $process.CommandLine -match 'dashboard\.py' -and $process.ExecutablePath -match 'python') {
        Stop-Process -Id $taskPid
        Remove-Item -LiteralPath $pidFile
        Write-Host 'Dashboard and collector stopped.'
    } else { Write-Host 'No matching dashboard process; nothing stopped.' }
}

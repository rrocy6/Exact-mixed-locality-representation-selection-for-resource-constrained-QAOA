[CmdletBinding()]
param(
    [ValidateSet('verify','run','analyse')][string]$Command = 'verify',
    [string]$ProjectRoot = (Get-Location).Path,
    [string]$RunDirectory,
    [string]$OutputPath,
    [int]$Workers = 4,
    [switch]$Resume
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$env:PYTHONUTF8 = '1'
$env:QISKIT_PARALLEL = 'FALSE'
foreach ($name in @('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','RAYON_NUM_THREADS')) {
    [Environment]::SetEnvironmentVariable($name, '1', 'Process')
}
$python = Join-Path $ProjectRoot 'revisions\URSS_20260917_verified_v1\.venv_revision\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw 'Existing verified Python environment not found. Set -ProjectRoot to the original project root.' }
$stamp = Get-Date -Format 'yyyyMMdd_HHmmss_fff'
$baseOutput = Join-Path $ProjectRoot 'revisions\URSS_feedback_2_6_v3'
if ($Command -eq 'run') {
    if ($Resume -and -not $RunDirectory) { throw '-Resume requires the original -RunDirectory.' }
    if (-not $RunDirectory) { $RunDirectory = Join-Path $baseOutput "runs\$stamp" }
    $arguments = @((Join-Path $PSScriptRoot 'study.py'), 'run', '--output', $RunDirectory, '--workers', "$Workers")
    if ($Resume) { $arguments += '--resume' }
} else {
    if ($Resume) { throw '-Resume applies to run only.' }
    if (-not $RunDirectory) { $RunDirectory = Join-Path $PSScriptRoot 'execution' }
    if (-not $OutputPath) { $OutputPath = Join-Path $baseOutput "checks\${Command}_$stamp.json" }
    $script = if ($Command -eq 'verify') { 'audit.py' } else { 'analyse.py' }
    $arguments = @((Join-Path $PSScriptRoot $script), '--run', $RunDirectory, '--output', $OutputPath)
}
& $python @arguments
if ($LASTEXITCODE -ne 0) { throw "Iteration command failed (exit $LASTEXITCODE)." }
Write-Output "ITERATION_COMMAND: PASS ($Command)"
if ($Command -eq 'run') { Write-Output "RUN_DIRECTORY: $RunDirectory" } else { Write-Output "REPORT: $OutputPath" }

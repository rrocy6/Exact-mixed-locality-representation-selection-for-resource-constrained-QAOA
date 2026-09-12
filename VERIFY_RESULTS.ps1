param([string]$PythonExe = "")
$ErrorActionPreference = "Stop"
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
$prefixArgs = @()
if ([string]::IsNullOrWhiteSpace($PythonExe)) {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        $PythonExe = "py"
        $prefixArgs = @("-3.12")
    } else {
        $PythonExe = "python"
    }
}
& $PythonExe @prefixArgs -X utf8 -u (Join-Path $PSScriptRoot "verify_selected_qaoa_results.py") --output $PSScriptRoot
if ($LASTEXITCODE -ne 0) { throw "Verification failed. Preserve the preceding error output." }
Write-Host "RESULT PACKAGE VERIFY: PASS"

# Apply the Windows parent-config hash compatibility fix

This patch accepts a Git CRLF checkout of the frozen v1 YAML only when its
CRLF-to-LF normalized SHA-256 equals the exact parent hash frozen in
`experiment_config_v2`. It does not accept content changes and does not change
either experiment config.

## A. Preserve the failed console log and verify a clean checkpoint

```powershell
$latestSubject = git log -1 --format="%s"
"LATEST COMMIT: $latestSubject"

if ($latestSubject -ne "Add frozen fibre-aware selector v2") {
  throw "Expected the selector-v2 implementation checkpoint"
}

$failedConsole = ".\evidence\FIBRE_SELECTOR_V2_CONSOLE_WINDOWS.txt"

if (Test-Path -LiteralPath $failedConsole) {
  $recoveryDirectory = Join-Path `
    (Split-Path -Parent (Resolve-Path ".").Path) `
    ("FIBRE_V2_PARENT_HASH_FAILURE_" + (Get-Date -Format "yyyyMMdd_HHmmss"))

  New-Item -ItemType Directory -Path $recoveryDirectory | Out-Null
  Move-Item -LiteralPath $failedConsole -Destination $recoveryDirectory
  "RECOVERY DIRECTORY: $recoveryDirectory"
}

if (git status --porcelain) {
  git status --short
  throw "Worktree has changes other than the preserved failed console"
}
```

## B. Verify and extract the patch

```powershell
$zipPath = Join-Path `
  $env:USERPROFILE `
  "Downloads\URSS_FIBRE_SELECTOR_V2_WINDOWS_PARENT_HASH_FIX_2026-08-28.zip"
$hashPath = $zipPath + ".sha256"

if (-not (Test-Path -LiteralPath $zipPath)) {
  throw "Patch ZIP not found"
}

if (-not (Test-Path -LiteralPath $hashPath)) {
  throw "Patch SHA256 sidecar not found"
}

$actualHash = (
  Get-FileHash -LiteralPath $zipPath -Algorithm SHA256
).Hash.ToLower()
$declaredHash = (
  Get-Content -Raw -LiteralPath $hashPath
).Trim().ToLower()

"PATCH HASH MATCH: $($actualHash -eq $declaredHash)"

if ($actualHash -ne $declaredHash) {
  throw "Patch ZIP hash mismatch"
}

Expand-Archive -LiteralPath $zipPath -DestinationPath . -Force
git status --short
```

## C. Run 124 regressions and Golden

```powershell
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

$testOutput = @(
  python ".\run_pipeline_tests.py" 2>&1 |
    Tee-Object ".\evidence\TEST_OUTPUT_FIBRE_SELECTOR_V2_WINDOWS_HASH_FIX.txt"
)
$testExitCode = $LASTEXITCODE
"TEST EXIT CODE: $testExitCode"

if ($testExitCode -ne 0) {
  throw "Regression tests failed"
}

if (($testOutput -join "`n") -notmatch "Ran 124 tests") {
  throw "Did not run the required 124 tests"
}

Push-Location ".\golden_example"
python ".\run_tests.py"
$goldenExitCode = $LASTEXITCODE
Pop-Location
"GOLDEN EXIT CODE: $goldenExitCode"

if ($goldenExitCode -ne 0) {
  throw "Golden regression failed"
}
```

## D. Commit the compatibility fix

```powershell
git add -- `
  ".\APPLY_FIBRE_SELECTOR_V2.md" `
  ".\APPLY_FIBRE_SELECTOR_V2_WINDOWS_PARENT_HASH_FIX.md" `
  ".\evidence\TEST_OUTPUT_FIBRE_SELECTOR_V2_WINDOWS_HASH_FIX.txt" `
  ".\tests\test_fibre_selector.py" `
  ".\urss_pipeline\fibre_validation.py"

git diff --cached --check

if ($LASTEXITCODE -ne 0) {
  throw "Compatibility patch has formatting errors"
}

git commit -m "Accept CRLF checkout for frozen v1 parent hash"

if ($LASTEXITCODE -ne 0) {
  throw "Compatibility patch commit failed"
}

if (git status --porcelain) {
  git status --short
  throw "Compatibility patch did not leave a clean worktree"
}

git --no-pager log -3 --format="%h %s"
"WINDOWS PARENT HASH FIX GATE: PASS"
```

After this gate passes, rerun section D of `APPLY_FIBRE_SELECTOR_V2.md`.

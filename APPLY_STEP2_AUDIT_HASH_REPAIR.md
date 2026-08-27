# Repair the formal Step 2 audit hash sidecars

Run from the repository root in Windows PowerShell 5.1. This repair is
permitted only when the existing `benchmark_audit_v1.sha256` matches the
frozen HTML audit and not the JSON audit. That condition proves a deterministic
sidecar-name collision rather than a change to the frozen experiment data.

## A. Confirm the collision and a clean starting point

```powershell
$jsonPath = ".\data\benchmark_audit_v1.json"
$htmlPath = ".\data\benchmark_audit_v1.html"
$sidecarPath = ".\data\benchmark_audit_v1.sha256"

$jsonHash = (Get-FileHash $jsonPath -Algorithm SHA256).Hash.ToLower()
$htmlHash = (Get-FileHash $htmlPath -Algorithm SHA256).Hash.ToLower()
$declaredHash = (Get-Content $sidecarPath -Raw).Trim()

"JSON SHA256:     $jsonHash"
"HTML SHA256:     $htmlHash"
"DECLARED SHA256: $declaredHash"
"COLLISION CONFIRMED: $($declaredHash -eq $htmlHash -and $declaredHash -ne $jsonHash)"

if ($declaredHash -ne $htmlHash -or $declaredHash -eq $jsonHash) {
  throw "Not the known JSON/HTML sidecar collision; stop"
}

if (git status --porcelain) {
  throw "Working tree must be clean before applying the repair"
}
```

## B. Extract the repair ZIP and run regressions

After verifying the ZIP SHA-256 supplied with the delivery, extract it into
the repository root. Then run:

```powershell
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

$testOutput = @(
  python ".\run_pipeline_tests.py" 2>&1 |
    Tee-Object ".\evidence\TEST_OUTPUT_STEP2_AUDIT_HASH_REPAIR_WINDOWS.txt"
)
$testExitCode = $LASTEXITCODE
"TEST EXIT CODE: $testExitCode"

if ($testExitCode -ne 0) { throw "Regression tests failed" }
if (($testOutput -join "`n") -notmatch "Ran 45 tests") {
  throw "Did not run the required 45 tests"
}

Push-Location ".\golden_example"
python ".\run_tests.py"
$goldenExitCode = $LASTEXITCODE
Pop-Location
"GOLDEN EXIT CODE: $goldenExitCode"
if ($goldenExitCode -ne 0) { throw "Golden regression failed" }
```

Required: `Ran 45 tests`, `OK`, exit code `0`, and Golden `10 passed`.

## C. Write separate JSON and HTML sidecars

```powershell
$utf8 = [System.Text.UTF8Encoding]::new($false)
$jsonHash = (Get-FileHash $jsonPath -Algorithm SHA256).Hash.ToLower()
$htmlHash = (Get-FileHash $htmlPath -Algorithm SHA256).Hash.ToLower()

[System.IO.File]::WriteAllText(
  ".\data\benchmark_audit_v1.sha256",
  $jsonHash + "`n",
  $utf8
)
[System.IO.File]::WriteAllText(
  ".\data\benchmark_audit_v1.html.sha256",
  $htmlHash + "`n",
  $utf8
)

$jsonDeclared = (Get-Content ".\data\benchmark_audit_v1.sha256" -Raw).Trim()
$htmlDeclared = (Get-Content ".\data\benchmark_audit_v1.html.sha256" -Raw).Trim()
"JSON HASH MATCH: $($jsonDeclared -eq $jsonHash)"
"HTML HASH MATCH: $($htmlDeclared -eq $htmlHash)"
if ($jsonDeclared -ne $jsonHash -or $htmlDeclared -ne $htmlHash) {
  throw "Audit sidecar repair failed"
}
```

This does not alter either frozen audit artifact. It separates their two
hashes and fixes the generator so a future regeneration cannot overwrite the
JSON sidecar with the HTML hash.

## D. Record and commit the repair

```powershell
$repairNote = @"

## Formal Step 2 audit-sidecar repair

- The frozen JSON and HTML audit contents were not changed.
- Root cause: both artifacts previously mapped to benchmark_audit_v1.sha256;
  the later HTML write overwrote the JSON hash.
- JSON SHA-256: $jsonHash.
- HTML SHA-256: $htmlHash.
- Separate JSON and HTML sidecars now verify independently.
"@

[System.IO.File]::AppendAllText(
  ".\assumptions_and_decisions.md",
  $repairNote.TrimEnd() + "`n",
  $utf8
)

git add -- `
  ".\APPLY_STEP2_AUDIT_HASH_REPAIR.md" `
  ".\assumptions_and_decisions.md" `
  ".\data\benchmark_audit_v1.sha256" `
  ".\data\benchmark_audit_v1.html.sha256" `
  ".\evidence\TEST_OUTPUT_STEP2_AUDIT_HASH_REPAIR_WINDOWS.txt" `
  ".\tests\test_formal_data.py" `
  ".\urss_pipeline\formal_data.py"

git diff --cached --check
git --no-pager diff --cached --stat
git commit -m "Repair formal Step 2 audit hash sidecars"
git status
```

Do not rerun E1 until the repair commit exists and Git reports
`nothing to commit, working tree clean`.

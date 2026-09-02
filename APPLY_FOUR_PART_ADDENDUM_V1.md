# Apply the four-part experimental addendum v1

This update is based on local checkpoint `1a4f866`. It adds an append-only
experimental branch; it does not replace the frozen E1--E6 raw rows, tables,
figures, manifests, or result pack.

## A. Verify and extract

Run from the repository root in PowerShell. Replace the ZIP path if needed.

```powershell
$updateZip = Join-Path $env:USERPROFILE `
  "Downloads\URSS_FOUR_PART_ADDENDUM_V1_UPDATE.zip"

$sidecarPath = "$updateZip.sha256"
$expected = (Get-Content -LiteralPath $sidecarPath -Raw).Trim().ToLower()
$actual = (
  Get-FileHash -LiteralPath $updateZip -Algorithm SHA256
).Hash.ToLower()

"UPDATE ZIP SHA256: $actual"
if ($actual -ne $expected) {
  throw "Update ZIP hash mismatch; do not extract"
}

if (git status --porcelain) {
  git status --short
  throw "Commit or safely preserve unrelated local changes before extraction"
}

Expand-Archive -LiteralPath $updateZip -DestinationPath . -Force
```

## B. Verify the update manifest

```powershell
$manifest = Import-Csv ".\UPDATE_FILE_MANIFEST_FOUR_PART_ADDENDUM_V1.csv"

foreach ($row in $manifest) {
  if (-not (Test-Path -LiteralPath $row.path)) {
    throw "Missing update file: $($row.path)"
  }
  $hash = (
    Get-FileHash -LiteralPath $row.path -Algorithm SHA256
  ).Hash.ToLower()
  $size = (Get-Item -LiteralPath $row.path).Length
  if ($hash -ne $row.sha256 -or $size -ne [int64]$row.size_bytes) {
    throw "Update file verification failed: $($row.path)"
  }
}

"FOUR-PART UPDATE MANIFEST GATE: PASS"
```

## C. Install the already frozen environment and test

Use the same Python environment that successfully ran the frozen E1--E6
pipeline. No dependency versions are changed by this update.

```powershell
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

python ".\run_pipeline_tests.py"
if ($LASTEXITCODE -ne 0) {
  throw "Regression tests failed"
}
```

The source archive supplied for this update contains CRLF-transformed frozen
text files. The update accepts that transport only if converting CRLF to LF
reproduces both the signed SHA-256 and signed byte count. Other changes remain
fatal.

## D. Commit the implementation checkpoint

```powershell
git add -- `
  ".\APPLY_FOUR_PART_ADDENDUM_V1.md" `
  ".\IMPLEMENTATION_REPORT_FOUR_PART_ADDENDUM_V1.md" `
  ".\RUN_COMMANDS_FOUR_PART_ADDENDUM_V1.md" `
  ".\UPDATE_FILE_MANIFEST_FOUR_PART_ADDENDUM_V1.csv" `
  ".\UPDATE_FILE_MANIFEST_FOUR_PART_ADDENDUM_V1.sha256" `
  ".\configs\four_part_addendum_v1.json" `
  ".\configs\four_part_addendum_v1.json.sha256" `
  ".\run_four_part_addendum_v1.py" `
  ".\tests\test_four_part_addendum_v1.py" `
  ".\urss_pipeline\e2_resources.py" `
  ".\urss_pipeline\fibre_rerun.py" `
  ".\urss_pipeline\four_part_addendum.py"

git diff --cached --check
if ($LASTEXITCODE -ne 0) {
  throw "Formatting gate failed"
}

git commit -m "Add four-part experimental addendum"
```

Then follow `RUN_COMMANDS_FOUR_PART_ADDENDUM_V1.md` without changing the
frozen config.

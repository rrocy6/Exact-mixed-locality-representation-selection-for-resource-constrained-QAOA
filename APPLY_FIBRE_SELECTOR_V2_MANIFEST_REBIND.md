# Bind selector v2 to the repository's frozen formal manifests

The repository's oracle, QAOA and compilation manifests have the same semantic
fingerprints as the calibration snapshot. Their byte hashes differ only in the
`config_sha256`, `generation_plan_sha256` and `code_commit` provenance columns.
This patch binds selector v2 to the repository's exact oracle-manifest bytes;
it does not change instances, splits, canonical data, selector weights or tau.

## A. Preserve failed-run evidence and restore a clean checkpoint

```powershell
$latestSubject = git log -1 --format="%s"
"LATEST COMMIT: $latestSubject"

if ($latestSubject -ne "Bind selector v2 to frozen Step 1 config") {
  throw "Expected the Step 1 parent-rebind checkpoint"
}

$failedConsole = ".\evidence\FIBRE_SELECTOR_V2_CONSOLE_WINDOWS.txt"
$stagingPath = ".\fibre_selector_v2_building"

if (Test-Path -LiteralPath ".\fibre_selector_v2") {
  throw "A final selector-v2 output unexpectedly exists"
}

if (
  (Test-Path -LiteralPath $failedConsole) -or
  (Test-Path -LiteralPath $stagingPath)
) {
  $recoveryDirectory = Join-Path `
    (Split-Path -Parent (Resolve-Path ".").Path) `
    ("FIBRE_V2_MANIFEST_HASH_FAILURE_" + (Get-Date -Format "yyyyMMdd_HHmmss"))

  New-Item -ItemType Directory -Path $recoveryDirectory | Out-Null

  if (Test-Path -LiteralPath $failedConsole) {
    Move-Item `
      -LiteralPath $failedConsole `
      -Destination (Join-Path $recoveryDirectory "FIBRE_SELECTOR_V2_CONSOLE_WINDOWS.txt")
  }

  if (Test-Path -LiteralPath $stagingPath) {
    Move-Item `
      -LiteralPath $stagingPath `
      -Destination (Join-Path $recoveryDirectory "fibre_selector_v2_building")
  }

  "RECOVERY DIRECTORY: $recoveryDirectory"
}

if (git status --porcelain) {
  git status --short
  throw "Worktree has changes beyond the preserved failed run"
}
```

## B. Verify and extract the manifest-rebind patch

```powershell
$zipPath = Join-Path `
  $env:USERPROFILE `
  "Downloads\URSS_FIBRE_SELECTOR_V2_MANIFEST_REBIND_2026-08-28.zip"
$hashPath = $zipPath + ".sha256"

if (-not (Test-Path -LiteralPath $zipPath)) {
  throw "Manifest-rebind ZIP not found"
}

if (-not (Test-Path -LiteralPath $hashPath)) {
  throw "Manifest-rebind SHA256 sidecar not found"
}

$actualHash = (
  Get-FileHash -LiteralPath $zipPath -Algorithm SHA256
).Hash.ToLower()
$declaredHash = (
  Get-Content -Raw -LiteralPath $hashPath
).Trim().ToLower()

"PATCH HASH MATCH: $($actualHash -eq $declaredHash)"

if ($actualHash -ne $declaredHash) {
  throw "Manifest-rebind ZIP hash mismatch"
}

Expand-Archive -LiteralPath $zipPath -DestinationPath . -Force
git status --short
```

## C. Reproduce the semantic and byte-level provenance gates

```powershell
$expectedSemanticHashes = @{
  oracle = "0398e59c92edb96fe0acd5fec9518ebe02595a6e9418d85a01dc2f6b9a4d7ce0"
  qaoa = "1a4de05ba2d948b6b797a1928cf14534afda09fc84c121074c4c88f5700b14d1"
  compilation = "996a3d48711f694d3403c9d40d0d810008b9bf433c84652159bab8a10b0006b1"
}

$semanticFailures = [System.Collections.Generic.List[string]]::new()

foreach ($name in @("oracle", "qaoa", "compilation")) {
  $manifestPath = "data/manifests/${name}_v1.csv"
  $semanticHash = (
    & python -c "import sys,csv,hashlib,json; excluded={'config_sha256','generation_plan_sha256','code_commit'}; f=open(sys.argv[1],newline='',encoding='utf-8'); rows=list(csv.DictReader(f)); f.close(); payload=[{k:r[k] for k in sorted(r) if k not in excluded} for r in sorted(rows,key=lambda x:x['instance_id'])]; print(hashlib.sha256((json.dumps(payload,sort_keys=True,separators=(',',':'))+'\n').encode()).hexdigest())" $manifestPath
  ).Trim()

  "${name} SEMANTIC MATCH: $($semanticHash -eq $expectedSemanticHashes[$name])"

  if ($semanticHash -ne $expectedSemanticHashes[$name]) {
    $semanticFailures.Add($name)
  }
}

if ($semanticFailures.Count -ne 0) {
  $semanticFailures
  throw "Semantic manifest gate failed"
}

$oracleExpected = "d14b3cbcd9f75404ece9960bc60b76cb47ca7bd457019c8fd7fed8c0dafd9ee3"
$configExpected = "9d124ad72c0fe2b841fbfc927ec45c35cb413a6a0e01baada17f1025709d315c"
$oracleActual = (
  Get-FileHash ".\data\manifests\oracle_v1.csv" -Algorithm SHA256
).Hash.ToLower()
$oracleDeclared = (
  Get-Content -Raw ".\data\manifests\oracle_v1.sha256"
).Trim().ToLower()
$v2Oracle = (
  & python -c "import yaml; c=yaml.safe_load(open(r'configs/experiment_config_v2.yaml',encoding='utf-8')); print(c['fibre_selector_freeze_provenance']['calibration_manifest_sha256'])"
).Trim()

if (
  $oracleActual -ne $oracleExpected -or
  $oracleDeclared -ne $oracleExpected -or
  $v2Oracle -ne $oracleExpected
) {
  throw "Oracle manifest byte-level provenance gate failed"
}

$configReport = @(
  python ".\validate_experiment_config.py" `
    --config ".\configs\experiment_config_v2.yaml" 2>&1
) | Out-String
$configReport

if ($LASTEXITCODE -ne 0 -or $configReport -notmatch $configExpected) {
  throw "Manifest-rebound experiment_config_v2 validation failed"
}

"MANIFEST REBIND PROVENANCE GATE: PASS"
```

## D. Run regressions and commit

```powershell
$testOutput = @(
  python ".\run_pipeline_tests.py" 2>&1 |
    Tee-Object ".\evidence\TEST_OUTPUT_FIBRE_SELECTOR_V2_MANIFEST_REBIND_WINDOWS.txt"
)
$testExitCode = $LASTEXITCODE
"TEST EXIT CODE: $testExitCode"

if ($testExitCode -ne 0 -or ($testOutput -join "`n") -notmatch "Ran 124 tests") {
  throw "Required 124 regressions did not pass"
}

Push-Location ".\golden_example"
python ".\run_tests.py"
$goldenExitCode = $LASTEXITCODE
Pop-Location
"GOLDEN EXIT CODE: $goldenExitCode"

if ($goldenExitCode -ne 0) {
  throw "Golden regression failed"
}

git add -- `
  ".\APPLY_FIBRE_SELECTOR_V2.md" `
  ".\APPLY_FIBRE_SELECTOR_V2_MANIFEST_REBIND.md" `
  ".\RUN_COMMANDS_FIBRE_SELECTOR_V2.md" `
  ".\configs\experiment_config_v2.yaml" `
  ".\configs\experiment_config_v2.sha256" `
  ".\evidence\TEST_OUTPUT_FIBRE_SELECTOR_V2_MANIFEST_REBIND_WINDOWS.txt"

git diff --cached --check

if ($LASTEXITCODE -ne 0) {
  throw "Manifest-rebind files have formatting errors"
}

git commit -m "Bind selector v2 to frozen formal manifests"

if ($LASTEXITCODE -ne 0) {
  throw "Manifest-rebind commit failed"
}

if (git status --porcelain) {
  git status --short
  throw "Manifest-rebind commit did not leave a clean worktree"
}

git --no-pager log -4 --format="%h %s"
"MANIFEST REBIND COMMIT GATE: PASS"
```

After this gate passes, rerun section D of `APPLY_FIBRE_SELECTOR_V2.md`.

# Bind selector v2 to the repository's frozen Step 1 config

This patch changes only selector-v2 provenance. It binds `parent_config.sha256`
to the v1 config frozen in this repository at commit `27172d0`. It does not
modify `experiment_config_v1`, raw/canonical data, ground truth, selector
parameters, or any E1--E6 result.

## A. Preserve the second failed console and verify the checkpoint

```powershell
$latestSubject = git log -1 --format="%s"
"LATEST COMMIT: $latestSubject"

if ($latestSubject -ne "Accept CRLF checkout for frozen v1 parent hash") {
  throw "Expected the Windows parent-hash compatibility checkpoint"
}

$failedConsole = ".\evidence\FIBRE_SELECTOR_V2_CONSOLE_WINDOWS.txt"

if (Test-Path -LiteralPath $failedConsole) {
  $recoveryDirectory = Join-Path `
    (Split-Path -Parent (Resolve-Path ".").Path) `
    ("FIBRE_V2_PARENT_REBIND_FAILURE_" + (Get-Date -Format "yyyyMMdd_HHmmss"))

  New-Item -ItemType Directory -Path $recoveryDirectory | Out-Null
  Move-Item -LiteralPath $failedConsole -Destination $recoveryDirectory
  "RECOVERY DIRECTORY: $recoveryDirectory"
}

if (git status --porcelain) {
  git status --short
  throw "Worktree has changes other than the preserved failed console"
}
```

## B. Verify and extract the provenance patch

```powershell
$zipPath = Join-Path `
  $env:USERPROFILE `
  "Downloads\URSS_FIBRE_SELECTOR_V2_PARENT_REBIND_2026-08-28.zip"
$hashPath = $zipPath + ".sha256"

if (-not (Test-Path -LiteralPath $zipPath)) {
  throw "Parent-rebind ZIP not found"
}

if (-not (Test-Path -LiteralPath $hashPath)) {
  throw "Parent-rebind SHA256 sidecar not found"
}

$actualHash = (
  Get-FileHash -LiteralPath $zipPath -Algorithm SHA256
).Hash.ToLower()
$declaredHash = (
  Get-Content -Raw -LiteralPath $hashPath
).Trim().ToLower()

"PATCH HASH MATCH: $($actualHash -eq $declaredHash)"

if ($actualHash -ne $declaredHash) {
  throw "Parent-rebind ZIP hash mismatch"
}

Expand-Archive -LiteralPath $zipPath -DestinationPath . -Force
git status --short
```

## C. Prove that v1 and v2 provenance agree

```powershell
$v1Expected = "c1fe6ddb0aa5e0bd75dbc46707e2824bbe199bac82b2d766160294ce56353d99"
$v2Expected = "32d7f78b26785dddf544f7068e723cb41591d0217ce78075caa349d578163970"

$v1Worktree = (
  Get-FileHash ".\configs\experiment_config_v1.yaml" -Algorithm SHA256
).Hash.ToLower()
$v1Declared = (
  Get-Content -Raw ".\configs\experiment_config_v1.sha256"
).Trim().ToLower()
$v1Committed = (
  & python -c "import hashlib,subprocess; b=subprocess.check_output(['git','show','HEAD:configs/experiment_config_v1.yaml']); print(hashlib.sha256(b).hexdigest())"
).Trim()
$v2Parent = (
  & python -c "import yaml; c=yaml.safe_load(open(r'configs/experiment_config_v2.yaml',encoding='utf-8')); print(c['parent_config']['sha256'])"
).Trim()

"V1 WORKTREE: $v1Worktree"
"V1 DECLARED: $v1Declared"
"V1 COMMITTED: $v1Committed"
"V2 PARENT: $v2Parent"

if (
  $v1Worktree -ne $v1Expected -or
  $v1Declared -ne $v1Expected -or
  $v1Committed -ne $v1Expected -or
  $v2Parent -ne $v1Expected
) {
  throw "Frozen v1/v2 parent provenance does not agree"
}

$configReport = @(
  python ".\validate_experiment_config.py" `
    --config ".\configs\experiment_config_v2.yaml" 2>&1
) | Out-String
$configReport

if ($LASTEXITCODE -ne 0 -or $configReport -notmatch $v2Expected) {
  throw "Rebound experiment_config_v2 validation failed"
}

"PARENT REBIND PROVENANCE GATE: PASS"
```

## D. Run regressions and commit

```powershell
$testOutput = @(
  python ".\run_pipeline_tests.py" 2>&1 |
    Tee-Object ".\evidence\TEST_OUTPUT_FIBRE_SELECTOR_V2_PARENT_REBIND_WINDOWS.txt"
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
  ".\APPLY_FIBRE_SELECTOR_V2_PARENT_REBIND.md" `
  ".\RUN_COMMANDS_FIBRE_SELECTOR_V2.md" `
  ".\configs\experiment_config_v2.yaml" `
  ".\configs\experiment_config_v2.sha256" `
  ".\evidence\TEST_OUTPUT_FIBRE_SELECTOR_V2_PARENT_REBIND_WINDOWS.txt"

git diff --cached --check

if ($LASTEXITCODE -ne 0) {
  throw "Parent-rebind files have formatting errors"
}

git commit -m "Bind selector v2 to frozen Step 1 config"

if ($LASTEXITCODE -ne 0) {
  throw "Parent-rebind commit failed"
}

if (git status --porcelain) {
  git status --short
  throw "Parent-rebind commit did not leave a clean worktree"
}

git --no-pager log -4 --format="%h %s"
"PARENT REBIND COMMIT GATE: PASS"
```

After this gate passes, rerun section D of `APPLY_FIBRE_SELECTOR_V2.md`.

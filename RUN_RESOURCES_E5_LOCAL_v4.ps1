param(
    [string]$QaoaState = (Join-Path $env:USERPROFILE 'Downloads\URSS_QAOA_LOCAL_20260913_010625_121_3cb2fd\LOCAL_RUN_STATE.json'),
    [ValidateRange(1,16)][int]$Workers = 4,
    [string]$ResumeState = ''
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
$env:OMP_NUM_THREADS = '1'
$env:OPENBLAS_NUM_THREADS = '1'
$env:MKL_NUM_THREADS = '1'
$env:NUMEXPR_NUM_THREADS = '1'
$statePath = ''
$transcriptStarted = $false

function Invoke-Step {
    param([string]$File, [string[]]$ArgList)
    & $File @ArgList
    if ($LASTEXITCODE -ne 0) { throw ('Command failed: ' + $File + ' ' + ($ArgList -join ' ')) }
}
function Require-File {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw ('Required file missing: ' + $Path) }
}
function Save-State {
    param($State)
    [System.IO.File]::WriteAllText($statePath, ($State | ConvertTo-Json -Depth 8), (New-Object System.Text.UTF8Encoding($false)))
}

try {
    $versionPath = Join-Path $PSScriptRoot 'CODE_VERSION.json'
    Require-File $versionPath
    $version = Get-Content -LiteralPath $versionPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $bundle = Join-Path $PSScriptRoot 'CODE_CHANGES.bundle'
    Require-File $bundle
    if ((Get-FileHash -LiteralPath $bundle -Algorithm SHA256).Hash.ToLowerInvariant() -ne [string]$version.bundle_sha256) {
        throw 'Local Git bundle hash differs from CODE_VERSION.json.'
    }
    $selection = Join-Path $PSScriptRoot 'executed\inputs\selection'
    Require-File (Join-Path $selection 'CHANGED_DESIGNS_AND_CONTROLS.json')
    if ([string]::IsNullOrWhiteSpace($ResumeState)) {
        Require-File $QaoaState
        $previous = Get-Content -LiteralPath $QaoaState -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($previous.schema -ne 'urss_local_qaoa_v3' -or -not $previous.completed) { throw 'A completed local QAOA v3 state is required.' }
        Require-File ([string]$previous.python)
        $stamp = (Get-Date -Format 'yyyyMMdd_HHmmss_fff') + '_' + ([Guid]::NewGuid().ToString('N').Substring(0,6))
        $session = Join-Path $env:USERPROFILE ('Downloads\URSS_E2_E5_LOCAL_' + $stamp)
        New-Item -ItemType Directory -Path $session | Out-Null
        $statePath = Join-Path $session 'RESOURCE_RUN_STATE.json'
        $state = [PSCustomObject]@{
            schema = 'urss_local_resources_e5_v4'
            session = $session
            source_repo = [string]$previous.source_repo
            python = [string]$previous.python
            qaoa_results = [string]$previous.results
            qaoa_state = (Resolve-Path -LiteralPath $QaoaState).Path
            worktree = (Join-Path $session 'code_worktree')
            results = (Join-Path $session 'local_results')
            branch = ('fix/resources-e5-local-' + $stamp)
            code_commit = [string]$version.code_commit
            archive = ''
            completed = $false
        }
        Save-State $state
    } else {
        $statePath = (Resolve-Path -LiteralPath $ResumeState).Path
        $state = Get-Content -LiteralPath $statePath -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($state.schema -ne 'urss_local_resources_e5_v4' -or $state.code_commit -ne $version.code_commit) {
            throw 'Resume state uses a different schema or code revision.'
        }
    }
    Write-Host ('RESUME STATE: ' + $statePath)
    $log = Join-Path ([string]$state.session) ('RESOURCE_RUN_' + (Get-Date -Format 'yyyyMMdd_HHmmss_fff') + '.log')
    Start-Transcript -Path $log | Out-Null
    $transcriptStarted = $true
    if (-not (Test-Path -LiteralPath ([string]$state.worktree))) {
        Invoke-Step 'git' @('-C',[string]$state.source_repo,'bundle','verify',$bundle)
        Invoke-Step 'git' @('-C',[string]$state.source_repo,'fetch',$bundle,[string]$version.bundle_ref)
        Invoke-Step 'git' @('-C',[string]$state.source_repo,'-c','core.autocrlf=false','-c','core.eol=lf','worktree','add','-b',[string]$state.branch,[string]$state.worktree,[string]$version.code_commit)
    }
    $head = & git -C ([string]$state.worktree) rev-parse HEAD
    if ($LASTEXITCODE -ne 0 -or ([string]$head).Trim() -ne [string]$version.code_commit) { throw 'Execution worktree commit differs.' }
    if ((Test-Path -LiteralPath ([string]$state.results)) -and -not (Test-Path -LiteralPath (Join-Path ([string]$state.results) 'PLAN.json'))) {
        $kept = ([string]$state.results) + '_prepare_incomplete_' + (Get-Date -Format 'yyyyMMdd_HHmmss_fff')
        Move-Item -LiteralPath ([string]$state.results) -Destination $kept
        Write-Host ('Incomplete preparation retained: ' + $kept)
    }
    $runner = Join-Path ([string]$state.worktree) 'run_selected_resources_e5.py'
    Write-Host 'STARTING E2 RESOURCE RECOMPILATION AND E5 RECOMPUTATION'
    Invoke-Step ([string]$state.python) @('-X','utf8','-u',$runner,'--stage','all','--repo',[string]$state.worktree,'--selection',$selection,'--qaoa-results',[string]$state.qaoa_results,'--output',[string]$state.results,'--workers',[string]$Workers)
    $figures = Join-Path ([string]$state.worktree) 'make_resources_e5_paper_updates.py'
    Invoke-Step ([string]$state.python) @('-X','utf8','-u',$figures,'--output',[string]$state.results)
    Invoke-Step ([string]$state.python) @('-X','utf8','-u',$runner,'--stage','report','--repo',[string]$state.worktree,'--output',[string]$state.results)
    $verifier = Join-Path ([string]$state.worktree) 'verify_resources_e5_results.py'
    Invoke-Step ([string]$state.python) @('-X','utf8','-u',$verifier,'--output',[string]$state.results)
    $audit = Get-Content -LiteralPath (Join-Path ([string]$state.results) 'EXECUTION_AUDIT.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($audit.status -ne 'E2_E5_SELECTED_UPDATE_COMPLETE') { throw 'Resource/E5 audit does not report completion.' }
    $archive = Join-Path ([string]$state.session) ('URSS_E2_E5_LOCAL_RESULTS_' + (Get-Date -Format 'yyyyMMdd_HHmmss_fff') + '.zip')
    Compress-Archive -Path (Join-Path ([string]$state.results) '*') -DestinationPath $archive
    $state.archive = $archive
    $state.completed = $true
    Save-State $state
    Write-Host 'LOCAL E2 + E5: PASS'
    Write-Host ('RESOURCE ROWS: ' + $audit.resource_rows_processed)
    Write-Host ('E5 PRIMARY ENDPOINTS: ' + $audit.E5_primary_endpoints)
    Write-Host ('LOCAL RESULT ZIP: ' + $archive)
    Write-Host ('ZIP SHA256: ' + (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant())
    Write-Host ('RESUME STATE: ' + $statePath)
} catch {
    Write-Host ('RESOURCE RUN STOPPED: ' + $_.Exception.Message)
    if (-not [string]::IsNullOrWhiteSpace($statePath)) { Write-Host ('RESUME STATE: ' + $statePath) }
    throw
} finally {
    if ($transcriptStarted) { Stop-Transcript | Out-Null }
}

[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [string]$Idea = "",

    [string]$AgentCmd = $(if ($env:AGENT_CMD) { $env:AGENT_CMD } else { "agy" }),

    [ValidateRange(1, 20)]
    [int]$MaxRetries = 3,

    [ValidateSet("phase1", "phase2", "phase3", "phase4")]
    [string]$ResumeFrom = "phase1",

    [switch]$NoGit
)

$ErrorActionPreference = "Stop"
$LogDir = ".agent/logs"

if ($ResumeFrom -eq "phase1" -and [string]::IsNullOrWhiteSpace($Idea)) {
    Write-Error "Project idea is required when starting from phase1. Example: .\run-team.ps1 -Idea 'Build a personal finance tracker'"
    exit 1
}

$RoleFiles = @(
    ".agent/roles/pm.md",
    ".agent/roles/uiux.md",
    ".agent/roles/programmer.md",
    ".agent/roles/qc.md"
)
foreach ($rf in $RoleFiles) {
    if (-not (Test-Path $rf) -or (Get-Item $rf).Length -eq 0) {
        Write-Error "FATAL: Missing or empty role file: $rf"
        exit 1
    }
}

if (-not (Get-Command $AgentCmd -ErrorAction SilentlyContinue)) {
    Write-Error "FATAL: CLI command '$AgentCmd' not found in PATH."
    exit 1
}

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

function Assert-NonEmptyArtifacts {
    param(
        [string]$PhaseName,
        [string[]]$Paths
    )
    foreach ($p in $Paths) {
        if (-not (Test-Path $p) -or (Get-Item $p).Length -eq 0) {
            throw "FATAL: Gate failed after $PhaseName — '$p' is missing or empty."
        }
    }
}

function Invoke-GitCheckpoint {
    param([string]$Message)
    if ($NoGit -or -not (Get-Command git -ErrorAction SilentlyContinue)) {
        return
    }
    if (-not (Test-Path ".git")) {
        git init -q
    }
    git add -A
    $staged = git diff --cached --name-only
    if ($staged) {
        $authorName = if ($env:GIT_AUTHOR_NAME) { $env:GIT_AUTHOR_NAME } else { "agent-purnomo" }
        $authorEmail = if ($env:GIT_AUTHOR_EMAIL) { $env:GIT_AUTHOR_EMAIL } else { "agent-purnomo@local" }
        git -c user.name="$authorName" -c user.email="$authorEmail" commit -q -m "checkpoint: $Message"
    }
}

function Test-QaPass {
    if (-not (Test-Path "QA_REPORT.md") -or (Get-Item "QA_REPORT.md").Length -eq 0) {
        return $false
    }
    $nonEmpty = Get-Content -Path "QA_REPORT.md" -Encoding UTF8 | Where-Object { $_.Trim() -ne "" }
    if (-not $nonEmpty -or $nonEmpty.Count -eq 0) {
        return $false
    }
    $lastLine = ($nonEmpty[-1]).Trim()
    return ($lastLine -eq "STATUS: PASS")
}

function Invoke-AgentStep {
    param(
        [string]$LogFile,
        [string]$PromptText
    )
    & $AgentCmd -p $PromptText 2>&1 | Tee-Object -FilePath $LogFile
    if ($LASTEXITCODE -ne 0) {
        throw "Agent command '$AgentCmd' exited with code $LASTEXITCODE. See $LogFile"
    }
}

if ($ResumeFrom -eq "phase1") {
    Write-Host "=== [PHASE 1] Project Manager -> PRD.md & TASKS.md ===" -ForegroundColor Cyan
    $pmRole = Get-Content -Raw -Encoding UTF8 ".agent/roles/pm.md"
    $pmPrompt = "$pmRole`n`nUSER REQUEST:`n$Idea"
    Invoke-AgentStep -LogFile "$LogDir/phase1.log" -PromptText $pmPrompt
    Assert-NonEmptyArtifacts -PhaseName "Phase 1" -Paths @("PRD.md", "TASKS.md")
    Invoke-GitCheckpoint -Message "phase-1-prd-and-tasks"
}

if ($ResumeFrom -in @("phase1", "phase2")) {
    Assert-NonEmptyArtifacts -PhaseName "Phase 2 precondition" -Paths @("PRD.md", "TASKS.md")
    Write-Host "=== [PHASE 2] UI/UX Designer -> DESIGN_SPEC.md ===" -ForegroundColor Cyan
    $uiuxRole = Get-Content -Raw -Encoding UTF8 ".agent/roles/uiux.md"
    $uiuxPrompt = "$uiuxRole`n`nRead ./PRD.md and ./TASKS.md from the current directory and generate ./DESIGN_SPEC.md."
    Invoke-AgentStep -LogFile "$LogDir/phase2.log" -PromptText $uiuxPrompt
    Assert-NonEmptyArtifacts -PhaseName "Phase 2" -Paths @("DESIGN_SPEC.md")
    Invoke-GitCheckpoint -Message "phase-2-design-spec"
}

Assert-NonEmptyArtifacts -PhaseName "Phase 3 precondition" -Paths @("PRD.md", "TASKS.md", "DESIGN_SPEC.md")

for ($i = 1; $i -le $MaxRetries; $i++) {
    if ($i -eq 1 -and $ResumeFrom -eq "phase4") {
        Write-Host "=== [SKIP] Resuming directly at Phase 4 (Iteration $i/$MaxRetries) ===" -ForegroundColor Yellow
    } else {
        Write-Host "=== [PHASE 3 - Iteration $i/$MaxRetries] Programmer -> Implementation & Build ===" -ForegroundColor Cyan
        $progRole = Get-Content -Raw -Encoding UTF8 ".agent/roles/programmer.md"
        $progPrompt = "$progRole`n`nRead ./PRD.md, ./TASKS.md, ./DESIGN_SPEC.md, and ./QA_REPORT.md (if present). Implement pending tasks or fix logged bugs, update verified checkboxes in ./TASKS.md, and verify build/typecheck in terminal."
        Invoke-AgentStep -LogFile "$LogDir/phase3_iter$i.log" -PromptText $progPrompt
        Invoke-GitCheckpoint -Message "phase-3-iter-$i"
    }

    # Archive stale QA_REPORT.md before Phase 4
    if (Test-Path "QA_REPORT.md") {
        Move-Item -Force "QA_REPORT.md" "$LogDir/QA_REPORT.before-iter$i.md"
    }

    Write-Host "=== [PHASE 4 - Iteration $i/$MaxRetries] QC Tester -> Automated Test & Audit ===" -ForegroundColor Cyan
    $qcRole = Get-Content -Raw -Encoding UTF8 ".agent/roles/qc.md"
    $qcPrompt = "$qcRole`n`nRead ./PRD.md, ./TASKS.md, and ./DESIGN_SPEC.md. Write and run automated tests safely in terminal (no hanging servers or leaked ports), then write a fresh ./QA_REPORT.md ending with STATUS: PASS or STATUS: FAIL."
    Invoke-AgentStep -LogFile "$LogDir/phase4_iter$i.log" -PromptText $qcPrompt
    Assert-NonEmptyArtifacts -PhaseName "Phase 4 (Iteration $i)" -Paths @("QA_REPORT.md")
    Copy-Item -Force "QA_REPORT.md" "$LogDir/QA_REPORT.iter$i.md"
    Invoke-GitCheckpoint -Message "phase-4-iter-$i"

    if (Test-QaPass) {
        Write-Host "=== [SUCCESS] Passed QC on iteration $i! ===" -ForegroundColor Green
        exit 0
    }

    Write-Host "=== [FAIL] Defects logged in QA_REPORT.md on iteration $i. Routing back to Programmer... ===" -ForegroundColor Yellow
}

Write-Host "=== [STOP] Reached max retries ($MaxRetries). Inspect QA_REPORT.md and $LogDir/ for remaining defects. ===" -ForegroundColor Red
exit 1

[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [string]$Idea = "",

    [string]$TargetDir = "",

    [string]$AgentCmd = $(if ($env:AGENT_CMD) { $env:AGENT_CMD } else { "agy" }),

    [ValidateRange(1, 20)]
    [int]$MaxRetries = 3,

    [ValidateSet("phase1", "phase2", "phase3", "phase4")]
    [string]$ResumeFrom = "phase1",

    [ValidateSet("auto", "arg", "stdin")]
    [string]$PromptMode = "auto",

    [switch]$AllowIncompleteTasks,

    [switch]$NoGit
)

$ErrorActionPreference = "Stop"
$LogDir = ".agent/logs"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

if ($ResumeFrom -eq "phase1" -and [string]::IsNullOrWhiteSpace($Idea)) {
    Write-Error "Project idea is required when starting from phase1. Example: .\run-team.ps1 -Idea 'Build a personal finance tracker'"
    exit 1
}

function Ensure-GitIgnore {
    param([string]$GitIgnorePath = ".gitignore")
    $required = @(
        ".agent/logs/",
        ".env",
        ".env.*",
        "!.env.example",
        "node_modules/",
        "__pycache__/",
        "*.py[cod]",
        ".venv/",
        "venv/",
        "dist/",
        "build/",
        ".pytest_cache/",
        "coverage/",
        "*.db",
        "*.sqlite",
        "*.sqlite3"
    )
    $existing = @()
    if (Test-Path $GitIgnorePath) {
        $existing = Get-Content -Path $GitIgnorePath -Encoding UTF8 | ForEach-Object { $_.Trim() }
    }
    $missing = $required | Where-Object { $existing -notcontains $_ }
    if ($missing.Count -gt 0) {
        if (-not (Test-Path $GitIgnorePath)) {
            Set-Content -Path $GitIgnorePath -Value "# Added automatically by agent_purnomo safety guard" -Encoding UTF8
        } else {
            Add-Content -Path $GitIgnorePath -Value "`n# Added automatically by agent_purnomo safety guard" -Encoding UTF8
        }
        foreach ($item in $missing) {
            Add-Content -Path $GitIgnorePath -Value $item -Encoding UTF8
        }
    }
}

$OriginalLocation = Get-Location
try {
    if (-not [string]::IsNullOrWhiteSpace($TargetDir)) {
        $templateRoot = if (Test-Path ".agent/roles") { (Get-Location).Path } else { $ScriptDir }
        New-Item -ItemType Directory -Force -Path "$TargetDir/.agent/roles" | Out-Null
        New-Item -ItemType Directory -Force -Path "$TargetDir/.agent/workflows" | Out-Null

        foreach ($sub in @("roles", "workflows")) {
            $srcDir = Join-Path $templateRoot ".agent/$sub"
            $dstDir = Join-Path $TargetDir ".agent/$sub"
            if (Test-Path $srcDir) {
                Get-ChildItem -Path $srcDir -File | ForEach-Object {
                    $dstFile = Join-Path $dstDir $_.Name
                    if (-not (Test-Path $dstFile)) {
                        Copy-Item $_.FullName $dstFile
                    }
                }
            }
        }
        $srcGi = Join-Path $templateRoot ".gitignore"
        $dstGi = Join-Path $TargetDir ".gitignore"
        if ((Test-Path $srcGi) -and -not (Test-Path $dstGi)) {
            Copy-Item $srcGi $dstGi
        }
        Set-Location $TargetDir
        Ensure-GitIgnore -GitIgnorePath ".gitignore"
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

    $resolvedCmd = Get-Command $AgentCmd -ErrorAction SilentlyContinue
    if (-not $resolvedCmd) {
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
        Ensure-GitIgnore -GitIgnorePath ".gitignore"
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
        $nonEmpty = @(Get-Content -Path "QA_REPORT.md" -Encoding UTF8 | Where-Object { $_.Trim() -ne "" })
        if ($nonEmpty.Count -eq 0) {
            return $false
        }
        $lastLine = ($nonEmpty[-1]).Trim()
        return ($lastLine -eq "STATUS: PASS")
    }

    function Get-UncheckedTasks {
        if (-not (Test-Path "TASKS.md")) {
            return @()
        }
        return @(Get-Content -Path "TASKS.md" -Encoding UTF8 | Where-Object { $_ -match '^\s*-\s*\[\s\]\s+' })
    }

    function Build-ProgrammerPrompt {
        param([int]$Iteration)
        $progRole = Get-Content -Raw -Encoding UTF8 ".agent/roles/programmer.md"
        $base = "$progRole`n`nRead ./PRD.md, ./TASKS.md, ./DESIGN_SPEC.md, and ./QA_REPORT.md (if present). Implement pending tasks or fix logged bugs, update verified checkboxes in ./TASKS.md, and verify build/typecheck in terminal."
        if ($Iteration -le 1 -and -not (Test-Path "QA_REPORT.md")) {
            return $base
        }
        $sections = @()
        if (Test-Path "QA_REPORT.md") {
            $bugs = @(Get-Content -Path "QA_REPORT.md" -Encoding UTF8 | Where-Object { $_ -match '(^### BUG-|CRITICAL|MAJOR)' } | Select-Object -First 25)
            if ($bugs.Count -gt 0) {
                $sections += "ACTIVE QA DEFECTS TO FIX FIRST:`n" + ($bugs -join "`n")
            }
        }
        $unchecked = @(Get-UncheckedTasks | Select-Object -First 25)
        if ($unchecked.Count -gt 0) {
            $sections += "REMAINING UNCHECKED TASKS:`n" + ($unchecked -join "`n")
        }
        if ($sections.Count -eq 0) {
            return $base
        }
        return "$base`n`n=== FOCUSED RETRY CONTEXT (ITERATION $Iteration) ===`n" + ($sections -join "`n`n")
    }

    function Invoke-AgentStep {
        param(
            [string]$LogFile,
            [string]$PromptText
        )
        $effectiveMode = $PromptMode
        $isBatchWrapper = $resolvedCmd.Source -match '\.(cmd|bat)$'
        if ($effectiveMode -eq "auto") {
            if ($PromptText.Length -gt 8000 -or ($isBatchWrapper -and $PromptText.Contains("`n"))) {
                $effectiveMode = "stdin"
            } else {
                $effectiveMode = "arg"
            }
        }

        $prevPref = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        try {
            if ($effectiveMode -eq "stdin") {
                $PromptText | & $resolvedCmd.Source -p 2>&1 | Tee-Object -FilePath $LogFile
            } else {
                & $resolvedCmd.Source -p $PromptText 2>&1 | Tee-Object -FilePath $LogFile
            }
            $exitCode = $LASTEXITCODE
        } finally {
            $ErrorActionPreference = $prevPref
        }
        if ($exitCode -ne 0) {
            throw "Agent command '$AgentCmd' exited with code $exitCode. See $LogFile"
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
            $progPrompt = Build-ProgrammerPrompt -Iteration $i
            Invoke-AgentStep -LogFile "$LogDir/phase3_iter$i.log" -PromptText $progPrompt
            Invoke-GitCheckpoint -Message "phase-3-iter-$i"
        }

        if (Test-Path "QA_REPORT.md") {
            Move-Item -Force "QA_REPORT.md" "$LogDir/QA_REPORT.before-iter$i.md"
        }

        Write-Host "=== [PHASE 4 - Iteration $i/$MaxRetries] QC Tester -> Automated Test & Audit ===" -ForegroundColor Cyan
        $qcRole = Get-Content -Raw -Encoding UTF8 ".agent/roles/qc.md"
        $qcPrompt = "$qcRole`n`nRead ./PRD.md, ./TASKS.md, and ./DESIGN_SPEC.md. Write and run automated tests safely in terminal (no hanging servers or leaked ports), then write a fresh ./QA_REPORT.md ending with STATUS: PASS or STATUS: FAIL."
        Invoke-AgentStep -LogFile "$LogDir/phase4_iter$i.log" -PromptText $qcPrompt
        Assert-NonEmptyArtifacts -PhaseName "Phase 4 (Iteration $i)" -Paths @("QA_REPORT.md")

        $qaOk = Test-QaPass
        if ($qaOk) {
            $unchecked = Get-UncheckedTasks
            if ($unchecked.Count -gt 0 -and -not $AllowIncompleteTasks) {
                Write-Host "=== [WARN] QA_REPORT.md returned STATUS: PASS, but $($unchecked.Count) unchecked item(s) remain in TASKS.md! ===" -ForegroundColor Yellow
                $nl = [Environment]::NewLine
                $failMsg = "${nl}## Backlog Completion Gate Failure${nl}- **Severity:** ``MAJOR``${nl}- **Detail:** $($unchecked.Count) unchecked acceptance criteria remain in ``./TASKS.md``.${nl}${nl}STATUS: FAIL"
                Add-Content -Path "QA_REPORT.md" -Encoding UTF8 -Value $failMsg
                $qaOk = $false
            }
        }

        Copy-Item -Force "QA_REPORT.md" "$LogDir/QA_REPORT.iter$i.md"
        Invoke-GitCheckpoint -Message "phase-4-iter-$i"

        if ($qaOk) {
            Write-Host "=== [SUCCESS] Passed QC and Backlog Gate on iteration $i! ===" -ForegroundColor Green
            exit 0
        }

        Write-Host "=== [FAIL] Defects or unfinished tasks remain on iteration $i. Routing back to Programmer... ===" -ForegroundColor Yellow
    }

    Write-Host "=== [STOP] Reached max retries ($MaxRetries). Inspect QA_REPORT.md and $LogDir/ for remaining defects. ===" -ForegroundColor Red
    exit 1
} finally {
    Set-Location $OriginalLocation
}

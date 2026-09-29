# Keep this file ASCII-safe for Windows PowerShell 5.1.
param(
    [string]$ResumeRoot
)

$ErrorActionPreference = "Stop"
$utf8 = New-Object System.Text.UTF8Encoding($false)
[Console]::OutputEncoding = $utf8
$OutputEncoding = $utf8
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

$repo = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$generator = Join-Path $PSScriptRoot "make_orientation_eval_scenes.py"
$orchestrator = Join-Path $PSScriptRoot "orchestrator.py"
$evaluator = Join-Path $PSScriptRoot "detail_vlm_eval.py"
$sceneDir = Join-Path $repo "mvl-skeleton\scene"
$runsDir = Join-Path $repo "mvl-skeleton\runs"
$project = Join-Path $repo "XRunity"
$unity = "C:\Program Files\Unity\Hub\Editor\6000.5.6f1\Editor\Unity.exe"

if (-not (Test-Path -LiteralPath $unity)) {
    throw "Unity.exe not found: $unity"
}

Write-Host "=== preflight tests ===" -ForegroundColor Cyan
Push-Location $PSScriptRoot
try {
    & python -m unittest test_make_orientation_eval_scenes.py test_machine_checks.py | Out-Host
    if ($LASTEXITCODE -ne 0) {
        throw "Preflight tests failed (exit=$LASTEXITCODE)"
    }
}
finally {
    Pop-Location
}

if ($ResumeRoot) {
    $root = (Resolve-Path -LiteralPath $ResumeRoot).Path
    Write-Host "Resuming: $root" -ForegroundColor Yellow
}
else {
    $stamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $root = Join-Path $runsDir "orientation_detection_$stamp"
}
$inputDir = Join-Path $root "inputs"
$runDir = Join-Path $root "runs"
$sourceScenes = 1..3 | ForEach-Object {
    Join-Path $sceneDir "scene_study_seed$_.json"
}

& python $generator @sourceScenes --output-dir $inputDir | Out-Host
if ($LASTEXITCODE -ne 0) {
    throw "Orientation scene generation failed (exit=$LASTEXITCODE)"
}

$iterationDirs = [System.Collections.Generic.List[string]]::new()
foreach ($seed in 1..3) {
    $scene = Join-Path $inputDir "scene_study_seed${seed}_orientation_eval.json"
    $run = $null
    if (Test-Path -LiteralPath $runDir) {
        $run = Get-ChildItem -LiteralPath $runDir -Directory |
            Where-Object { $_.Name -like "study_room_seed${seed}_orientation_eval*" } |
            Where-Object {
                $iter = Join-Path $_.FullName "iter_00"
                (Test-Path -LiteralPath (Join-Path $iter "violations.json")) -and
                (Test-Path -LiteralPath (Join-Path $iter "detail_audit.json"))
            } |
            Sort-Object Name -Descending |
            Select-Object -First 1
    }
    if ($run) {
        Write-Host "=== orientation / seed${seed}: reuse completed audit ===" -ForegroundColor Yellow
    }
    else {
        Write-Host "=== orientation / seed$seed (4 positives) ===" -ForegroundColor Cyan
        & python $orchestrator `
            --scene $scene `
            --unity $unity `
            --project $project `
            --max-iters 1 `
            --detail-vlm-every-iteration `
            --runs-dir $runDir | Out-Host
        if ($LASTEXITCODE -ne 0) {
            throw "seed$seed failed (exit=$LASTEXITCODE)"
        }
        $run = Get-ChildItem -LiteralPath $runDir -Directory |
            Where-Object { $_.Name -like "study_room_seed${seed}_orientation_eval*" } |
            Sort-Object Name -Descending |
            Select-Object -First 1
    }
    if (-not $run) {
        throw "Run directory not found: seed$seed"
    }
    [void]$iterationDirs.Add((Join-Path $run.FullName "iter_00"))
}

$csv = Join-Path $root "orientation_detection_eval.csv"
$evalArgs = @($evaluator)
$evalArgs += $iterationDirs.ToArray()
$evalArgs += @("--csv", $csv)
& python @evalArgs
if ($LASTEXITCODE -ne 0) {
    throw "Evaluation failed (exit=$LASTEXITCODE)"
}

Write-Host "Complete: $root" -ForegroundColor Green
Write-Host "Use only the orientation TOTAL (12 positives). Other rows come from defect-injection scenes." -ForegroundColor Yellow

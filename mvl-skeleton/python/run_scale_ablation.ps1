$ErrorActionPreference = "Stop"

$repo = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$orchestrator = Join-Path $repo "mvl-skeleton\python\orchestrator.py"
$evaluator = Join-Path $repo "mvl-skeleton\python\scale_ablation_eval.py"
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
    & python -m unittest test_unity_bridge.py test_repair.py | Out-Host
    if ($LASTEXITCODE -ne 0) {
        throw "Preflight tests failed (exit=$LASTEXITCODE)"
    }
}
finally {
    Pop-Location
}

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$root = Join-Path $runsDir "scale_ablation_$stamp"
$perAxisDirs = [System.Collections.Generic.List[string]]::new()
$uniformDirs = [System.Collections.Generic.List[string]]::new()

function Invoke-Condition {
    param(
        [string]$Name,
        [bool]$Uniform,
        [System.Collections.Generic.List[string]]$IterationDirs
    )
    $conditionDir = Join-Path $root $Name
    foreach ($seed in 1..3) {
        $scene = Join-Path $sceneDir "scene_study_seed$seed.json"
        Write-Host "=== $Name / seed$seed ===" -ForegroundColor Cyan
        $runArgs = @(
            $orchestrator,
            "--scene", $scene,
            "--unity", $unity,
            "--project", $project,
            "--max-iters", "1",
            "--runs-dir", $conditionDir
        )
        if ($Uniform) {
            $runArgs += "--uniform-scale"
        }
        & python @runArgs | Out-Host
        if ($LASTEXITCODE -ne 0) {
            throw "$Name seed$seed failed (exit=$LASTEXITCODE)"
        }
        $run = Get-ChildItem -LiteralPath $conditionDir -Directory |
            Where-Object { $_.Name -like "study_room_seed$seed*" } |
            Sort-Object Name -Descending |
            Select-Object -First 1
        if (-not $run) {
            throw "Run directory not found: $Name seed$seed"
        }
        [void]$IterationDirs.Add((Join-Path $run.FullName "iter_00"))
    }
}

Invoke-Condition "per_axis" $false $perAxisDirs
Invoke-Condition "uniform" $true $uniformDirs

$resultsCsv = Join-Path $root "scale_ablation.csv"
$distortionCsv = Join-Path $root "aspect_ratio_distribution.csv"
$referenceScene = Join-Path $sceneDir "scene_study_seed1.json"
$evalArgs = @($evaluator, "--per-axis")
$evalArgs += $perAxisDirs.ToArray()
$evalArgs += "--uniform"
$evalArgs += $uniformDirs.ToArray()
$evalArgs += @(
    "--reference-scene", $referenceScene,
    "--csv", $resultsCsv,
    "--distortion-csv", $distortionCsv
)
& python @evalArgs
if ($LASTEXITCODE -ne 0) {
    throw "Evaluation failed (exit=$LASTEXITCODE)"
}

Write-Host "Complete: $root" -ForegroundColor Green

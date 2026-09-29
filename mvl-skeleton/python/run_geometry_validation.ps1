$ErrorActionPreference = "Stop"

$repo = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$orchestrator = Join-Path $repo "mvl-skeleton\python\orchestrator.py"
$sceneDir = Join-Path $repo "mvl-skeleton\scene"
$project = Join-Path $repo "XRunity"
$unity = "C:\Program Files\Unity\Hub\Editor\6000.5.6f1\Editor\Unity.exe"

if (-not (Test-Path -LiteralPath $unity)) {
    throw "Unity.exe not found: $unity"
}

foreach ($seed in 1..3) {
    $scene = Join-Path $sceneDir "scene_study_seed$seed.json"
    Write-Host "=== study_room_seed$seed full-quality geometry validation ===" -ForegroundColor Cyan
    & python $orchestrator `
        --scene $scene `
        --unity $unity `
        --project $project `
        --skip-vlm `
        --max-iters 12
    if ($LASTEXITCODE -ne 0) {
        throw "seed$seed failed (exit=$LASTEXITCODE). Remaining seeds were not started."
    }
}

Write-Host "All three full-quality runs completed." -ForegroundColor Green

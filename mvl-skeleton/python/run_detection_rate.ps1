# Save this script as UTF-8 with BOM when editing in Windows PowerShell 5.1.
# That shell otherwise decodes its Japanese status messages using the ANSI code page.
$ErrorActionPreference = "Stop"

# 検出率(再現率)の測定: 欠陥入りの seed1〜3 を1反復だけ回し、
# 詳細VLMの判定を機械検査の違反(正解ラベル)と突き合わせて集計する。
# --detail-vlm-repair は付けない(修復すると「何を検出できたか」が測れない)。
# --fast-unity も付けない(ベイクを飛ばすと影が変わり、誤検出率の測定条件と揃わない)。

$repo         = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$orchestrator = Join-Path $repo "mvl-skeleton\python\orchestrator.py"
$evaluator    = Join-Path $repo "mvl-skeleton\python\detail_vlm_eval.py"
$sceneDir     = Join-Path $repo "mvl-skeleton\scene"
$runsDir      = Join-Path $repo "mvl-skeleton\runs"
$project      = Join-Path $repo "XRunity"
$unity        = "C:\Program Files\Unity\Hub\Editor\6000.5.6f1\Editor\Unity.exe"

if (-not (Test-Path -LiteralPath $unity)) {
    throw "Unity.exe not found: $unity"
}

$started = Get-Date

foreach ($seed in 1..3) {
    $scene = Join-Path $sceneDir "scene_study_seed$seed.json"
    Write-Host "=== seed$seed : 検出率測定ラン (1反復) ===" -ForegroundColor Cyan
    & python $orchestrator `
        --scene $scene `
        --unity $unity `
        --project $project `
        --max-iters 1 `
        --detail-vlm-every-iteration
    if ($LASTEXITCODE -ne 0) {
        throw "seed$seed failed (exit=$LASTEXITCODE). 残りのシードは開始していない。"
    }
}

$dirs = foreach ($seed in 1..3) {
    $run = Get-ChildItem -LiteralPath $runsDir -Directory -Filter "study_room_seed$seed*" |
        Where-Object { $_.CreationTime -ge $started } |
        Sort-Object Name -Descending |
        Select-Object -First 1
    if (-not $run) { throw "seed$seed の新しいランが見つからない。" }
    Join-Path $run.FullName "iter_00"
}

Write-Host "=== 集計対象 ===" -ForegroundColor Cyan
$dirs | ForEach-Object { Write-Host "  $_" }

$csv = Join-Path $runsDir "detail_vlm_eval_3seeds.csv"
& python $evaluator @dirs --csv $csv
if ($LASTEXITCODE -ne 0) {
    throw "集計に失敗 (exit=$LASTEXITCODE)."
}

Write-Host "完了: $csv" -ForegroundColor Green
Write-Host "浮遊・貫通・向きは検出率を出し、大きさ・機能関係は別枠。" -ForegroundColor Yellow

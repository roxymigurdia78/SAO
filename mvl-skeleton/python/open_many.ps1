# Open several saved runs at once, each in its own window, to compare by walking.
# Usage (in the sao folder):
#   .\mvl-skeleton\python\open_many.ps1 -Names contrast_1,contrast_2,contrast_3
#   (each name can be a part of the run name; the newest match is used)
# Add -Rebuild to build the players again. Unity must be CLOSED while building.
param([Parameter(Mandatory=$true)][string[]]$Names, [switch]$Rebuild)

$unity     = "C:\Program Files\Unity\Hub\Editor\6000.5.6f1\Editor\Unity.exe"
$sao       = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$project   = Join-Path $sao "XRunity"
$runsDir   = Join-Path $project "Assets\MVLRuns"
$buildRoot = Join-Path $sao "builds"

if (-not (Test-Path $runsDir)) { Write-Host "No saved runs in $runsDir"; exit 1 }
$scenes = Get-ChildItem $runsDir -Filter *.unity | Sort-Object LastWriteTime -Descending
function Resolve-Run([string]$key) {
    $exact = $scenes | Where-Object { $_.BaseName -eq $key } | Select-Object -First 1
    if ($exact) { return $exact.BaseName }
    $hit = $scenes | Where-Object { $_.BaseName -like "*$key*" } | Select-Object -First 1
    if ($hit) { return $hit.BaseName }
    Write-Host "No run matches '$key' in $runsDir"; exit 1
}
$runs = @($Names | ForEach-Object { Resolve-Run $_ })
$runs | ForEach-Object { Write-Host "run: $_" }

foreach ($name in $runs) {
    $dir = Join-Path $buildRoot $name
    $exe = Join-Path $dir "Room.exe"
    if ($Rebuild -and (Test-Path $dir)) { Remove-Item -Recurse -Force $dir }
    if (-not (Test-Path $exe)) {
        Write-Host "Building $name ... (a few minutes; Unity must be closed)"
        New-Item -ItemType Directory -Force -Path $dir | Out-Null
        $log = Join-Path $dir "build.log"
        Start-Process -FilePath $unity -Wait -ArgumentList @(
            "-batchmode", "-projectPath", "`"$project`"",
            "-executeMethod", "MVLPlayerBuilder.BuildFromArgs",
            "-runScene", "Assets/MVLRuns/$name.unity",
            "-outExe", "`"$exe`"",
            "-logFile", "`"$log`"")
        if (-not (Test-Path $exe)) { Write-Host "Build failed. See $log"; exit 1 }
    }
}

foreach ($name in $runs) {
    Start-Process -FilePath (Join-Path $buildRoot "$name\Room.exe") -ArgumentList @("-screen-fullscreen", "0", "-screen-width", "800", "-screen-height", "450")
}
Write-Host "Opened $($runs.Count) windows. Window titles show the run names."

# Open two saved runs side by side as separate windows, so you can walk both rooms at once.
# Usage (in the sao folder):
#   .\mvl-skeleton\python\open_two.ps1                      # the two newest runs
#   .\mvl-skeleton\python\open_two.ps1 -A win_ceil_model -B holodeck   # part of the run name is enough (newest match)
# Controls in each window: hold right mouse + move = look / WASD = move / Q E = down/up / Shift = fast
# Add -Rebuild to build the players again (e.g. if a window shows an empty space).
# The first time for each run, a Windows player (exe) is built (Unity must be CLOSED). Later it opens instantly.
param([string]$A = "", [string]$B = "", [switch]$Rebuild)

$unity     = "C:\Program Files\Unity\Hub\Editor\6000.5.6f1\Editor\Unity.exe"
$sao       = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$project   = Join-Path $sao "XRunity"
$runsDir   = Join-Path $project "Assets\MVLRuns"
$buildRoot = Join-Path $sao "builds"

if (-not (Test-Path $runsDir)) { Write-Host "No saved runs in $runsDir"; exit 1 }
$scenes = Get-ChildItem $runsDir -Filter *.unity | Sort-Object LastWriteTime -Descending
# -A / -B can be a part of the name (e.g. "holodeck"): the newest run whose name contains it is used
function Resolve-Run([string]$key) {
    $exact = $scenes | Where-Object { $_.BaseName -eq $key } | Select-Object -First 1
    if ($exact) { return $exact.BaseName }
    $hit = $scenes | Where-Object { $_.BaseName -like "*$key*" } | Select-Object -First 1
    if ($hit) { return $hit.BaseName }
    Write-Host "No run matches '$key' in $runsDir"; exit 1
}
if ($B -eq "") { $B = $scenes[0].BaseName } else { $B = Resolve-Run $B }
if ($A -eq "") { $A = ($scenes | Where-Object { $_.BaseName -ne $B } | Select-Object -First 1).BaseName } else { $A = Resolve-Run $A }
Write-Host "A: $A"
Write-Host "B: $B"

foreach ($name in @($A, $B)) {
    $dir = Join-Path $buildRoot $name
    $exe = Join-Path $dir "Room.exe"
    if ($Rebuild -and (Test-Path $dir)) { Remove-Item -Recurse -Force $dir }   # -Rebuild: build the player again
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

foreach ($name in @($A, $B)) {
    Start-Process -FilePath (Join-Path $buildRoot "$name\Room.exe") -ArgumentList @("-screen-fullscreen", "0", "-screen-width", "960", "-screen-height", "540")
}
Write-Host "Opened two windows. Window titles show the run names."

# Open Unity and show the "MVL run list" window (walk saved runs in Play mode).
# Usage (in the sao folder):  .\mvl-skeleton\python\open_runs.ps1
# Close Unity before running orchestrator.py again (batch mode fails while the editor is open).
$unity   = "C:\Program Files\Unity\Hub\Editor\6000.5.6f1\Editor\Unity.exe"
$project = (Resolve-Path (Join-Path $PSScriptRoot "..\..\XRunity")).Path
Start-Process -FilePath $unity -ArgumentList @("-projectPath", "`"$project`"", "-executeMethod", "MVLRunBrowser.Open")
Write-Host "Unity is starting. The MVL run list window opens automatically (menu: MVL)."

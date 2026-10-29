# Build the Windows app (and the installer, if Inno Setup is available). Run from the repo root.
$ErrorActionPreference = "Stop"
python -m PyInstaller beamer.spec --noconfirm
$iscc = (Get-Command iscc -ErrorAction SilentlyContinue).Source
if (-not $iscc) { $iscc = @("$env:ProgramFiles(x86)\Inno Setup 6\ISCC.exe", "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1 }
if ($iscc) { & $iscc installer\beamer.iss; Write-Host "Installer: dist\Beamer-Setup.exe" }
else { Write-Host "Inno Setup not found; portable build is in dist\Beamer" }

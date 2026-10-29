# One-command release. From the repo root:
#   scripts\release.ps1 -Version 0.1.3 -Notes "what changed"
# Bumps the version, builds the app + installer, commits, tags, pushes and publishes a GitHub release.
param(
    [Parameter(Mandatory = $true)][string]$Version,
    [Parameter(Mandatory = $true)][string]$Notes
)
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

if ($Version -notmatch '^\d+\.\d+\.\d+$') { throw "Version must look like 1.2.3" }
if (git status --porcelain | Select-String -NotMatch '^\s*$' | Where-Object { $_ -match 'config\.json|_key|creds' }) {
    throw "Refusing to release: a settings or key file is in the working tree."
}

$gh = (Get-Command gh -ErrorAction SilentlyContinue).Source
if (-not $gh) { $gh = Get-ChildItem "$env:LOCALAPPDATA\Microsoft\WinGet\Packages" -Filter gh.exe -Recurse | Select-Object -First 1 -ExpandProperty FullName }
if (-not $gh) { throw "GitHub CLI (gh) not found" }
$iscc = (Get-Command iscc -ErrorAction SilentlyContinue).Source
if (-not $iscc) { $iscc = @("$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe", "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1 }
if (-not $iscc) { throw "Inno Setup 6 not found" }
$py = ".venv\Scripts\python.exe"

# 1. version bump
(Get-Content beamer\__init__.py) -replace '__version__ = ".*"', "__version__ = `"$Version`"" | Set-Content beamer\__init__.py
(Get-Content installer\beamer.iss) -replace '#define AppVersion ".*"', "#define AppVersion `"$Version`"" | Set-Content installer\beamer.iss

# 2. changelog entry (newest first)
$log = Get-Content CHANGELOG.md -Raw
$entry = "# Changelog`r`n`r`n## $Version`r`n- $Notes`r`n"
Set-Content CHANGELOG.md ($log -replace '^# Changelog\s*', $entry + "`r`n")

# 3. build
& $py -m PyInstaller beamer.spec --noconfirm
& $iscc installer\beamer.iss
if (-not (Test-Path dist\Beamer-Setup.exe)) { throw "Installer was not built" }

# 4. commit, tag, push, publish
git add -A
git commit -m "Release $Version`n`n$Notes"
git tag "v$Version"
git push origin main --tags
& $gh release create "v$Version" dist\Beamer-Setup.exe --title "Beamer $Version" --notes $Notes
Write-Host "Published Beamer $Version"

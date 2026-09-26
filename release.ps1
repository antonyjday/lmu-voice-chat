# Builds dist\LMU-Voice-Chat-<version>.zip from the last commit, for a GitHub release.
# Testers extract it and double-click "Install LMU Voice Chat.bat".
# Publish with: gh release create v<version> dist\LMU-Voice-Chat-<version>.zip

$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$Version = (Get-Content VERSION -TotalCount 1).Trim()
if (git status --porcelain) { Write-Host 'Commit your changes first: the zip is built from the last commit.' -ForegroundColor Red; exit 1 }
New-Item -ItemType Directory -Force dist | Out-Null
$zip = "dist\LMU-Voice-Chat-$Version.zip"
git archive --format=zip --prefix="LMU Voice Chat $Version/" -o $zip HEAD
if ($LASTEXITCODE -ne 0) { exit 1 }
Write-Host "Built $zip"

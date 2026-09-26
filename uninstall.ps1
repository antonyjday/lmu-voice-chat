# Removes LMU Voice Chat: the app folder (with your config.toml), the shortcuts,
# Start with Windows and the Settings > Apps entry. Settings > Apps > LMU Voice
# Chat > Uninstall runs this.

$ErrorActionPreference = 'Stop'
$AppName = 'LMU Voice Chat'
$UninstallKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\LMUVoiceChat'
$RunKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run'
$Dir = $PSScriptRoot
$ModelCache = Join-Path $env:USERPROFILE '.cache\huggingface\hub'

if (Test-Path (Join-Path $Dir '.git')) {  # never delete a development copy
    Write-Host "$Dir is a git checkout, not an installed copy. Nothing removed." -ForegroundColor Red
    exit 1
}

Write-Host "Uninstalling $AppName from $Dir"
$answer = Read-Host 'This also deletes your settings (config.toml). Continue? [y/N]'
if ($answer -notmatch '^y') { Write-Host 'Cancelled.'; exit 1 }

# Close the app (matched by command line: the venv's python.exe starts a child interpreter).
$script = (Join-Path $Dir 'lmu_chat.py').ToLower()
Get-CimInstance Win32_Process -Filter "Name = 'pythonw.exe' OR Name = 'python.exe'" |
    Where-Object { $_.CommandLine -and $_.CommandLine.ToLower().Contains($script) } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

foreach ($folder in @('Programs', 'Desktop')) {
    $link = Join-Path ([Environment]::GetFolderPath($folder)) "$AppName.lnk"
    if (Test-Path $link) { Remove-Item $link -Force }
}
$run = (Get-ItemProperty $RunKey -ErrorAction SilentlyContinue).$AppName
if ($run -and $run.ToLower().Contains($script)) { Remove-ItemProperty $RunKey -Name $AppName }
if (Test-Path $UninstallKey) { Remove-Item $UninstallKey -Recurse -Force }

$models = @(Get-ChildItem $ModelCache -Directory -Filter 'models--Systran--faster-whisper-*' -ErrorAction SilentlyContinue)
if ($models) {
    $mb = [int]((Get-ChildItem $models.FullName -Recurse -File | Measure-Object Length -Sum).Sum / 1MB)
    if ((Read-Host "Also delete the downloaded speech models ($mb MB)? [y/N]") -match '^y') {
        $models | Remove-Item -Recurse -Force
    }
}

Set-Location $env:TEMP  # can't delete the folder we're in
Start-Sleep -Milliseconds 500  # let the closed app release its log file
Remove-Item $Dir -Recurse -Force
Write-Host "$AppName is uninstalled." -ForegroundColor Green
Read-Host 'Press Enter to close'

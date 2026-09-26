# Installs or updates LMU Voice Chat for the current user (no admin rights needed).
# Run it with "Install LMU Voice Chat.bat". It copies the app to
# %LOCALAPPDATA%\Programs\LMU Voice Chat, installs Python 3.12 if needed, sets up
# the dependencies and speech model, and adds Start Menu and desktop shortcuts.
# Running a newer version's installer updates in place and keeps config.toml.
#
#   -Here      set up this folder instead of copying it (for development)
#   -NoStart   don't start the app at the end

param([switch]$Here, [switch]$NoStart)

$ErrorActionPreference = 'Stop'
$AppName = 'LMU Voice Chat'
$UninstallKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\LMUVoiceChat'
$Source = $PSScriptRoot
$Dir = if ($Here) { $Source } else { Join-Path $env:LOCALAPPDATA "Programs\$AppName" }
$Version = (Get-Content (Join-Path $Source 'VERSION') -TotalCount 1).Trim()

function Step($text) { Write-Host ''; Write-Host "== $text" -ForegroundColor Cyan }
function Fail($text) { Write-Host ''; Write-Host $text -ForegroundColor Red; exit 1 }

function Stop-App {
    # The venv's python.exe starts the base interpreter as a child, so match on the
    # command line rather than the executable path.
    $script = (Join-Path $Dir 'lmu_chat.py').ToLower()
    Get-CimInstance Win32_Process -Filter "Name = 'pythonw.exe' OR Name = 'python.exe'" |
        Where-Object { $_.CommandLine -and $_.CommandLine.ToLower().Contains($script) } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
}

function Find-Python {
    try {
        $exe = & py -3.12 -c 'import sys; print(sys.executable)' 2>$null
        if ($LASTEXITCODE -eq 0 -and $exe) { return $exe.Trim() }
    } catch {}  # no py launcher
    foreach ($p in @("$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
                     "$env:ProgramFiles\Python312\python.exe")) {
        if (Test-Path $p) { return $p }
    }
    return $null
}

function New-Shortcut($path, $target, $arguments, $icon) {
    $s = (New-Object -ComObject WScript.Shell).CreateShortcut($path)
    $s.TargetPath = $target
    $s.Arguments = $arguments
    $s.WorkingDirectory = $Dir
    $s.IconLocation = "$icon,0"
    $s.Description = 'Push-to-talk voice chat for Le Mans Ultimate'
    $s.Save()
}

Write-Host "Installing $AppName $Version to $Dir"

Step 'Closing the app if it is running'
Stop-App

Step 'Finding Python 3.12'
$Python = Find-Python
if (-not $Python) {
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        Fail ("Python 3.12 is needed. Install it from https://www.python.org/downloads/ " +
              "(tick 'py launcher'), then run this installer again.")
    }
    Write-Host 'Not found. Installing it with winget (a few minutes)...'
    & winget install --id Python.Python.3.12 --exact --scope user --silent `
        --accept-package-agreements --accept-source-agreements
    $Python = Find-Python
    if (-not $Python) {
        Fail ("Python 3.12 didn't install. Install it from https://www.python.org/downloads/ " +
              "(tick 'py launcher'), then run this installer again.")
    }
}
Write-Host "Using $Python"

if (-not $Here -and $Source -ne $Dir) {
    Step 'Copying the app'
    New-Item -ItemType Directory -Force $Dir | Out-Null
    # Leaves the user's config.toml and log alone, and skips development files.
    & robocopy $Source $Dir /E /XD .venv .git __pycache__ dist `
        /XF config.toml lmu_chat.log DEV_NOTES.md .gitignore .gitattributes release.ps1 `
        /NFL /NDL /NJH /NJS /NP | Out-Null
    if ($LASTEXITCODE -ge 8) { Fail "Couldn't copy the files to $Dir." }
    Get-ChildItem $Dir -File | Unblock-File  # drop the "downloaded from the internet" mark
}

Step 'Installing the dependencies'
$Venv = Join-Path $Dir '.venv'
$Py = Join-Path $Venv 'Scripts\python.exe'
$Pyw = Join-Path $Venv 'Scripts\pythonw.exe'
if (Test-Path $Py) {
    $works = $false  # a venv breaks if the Python it was made from is removed
    try { & $Py -c 'pass' 2>$null; $works = ($LASTEXITCODE -eq 0) } catch {}
    if (-not $works) { Remove-Item $Venv -Recurse -Force }
}
if (-not (Test-Path $Py)) {
    & $Python -m venv $Venv
    if ($LASTEXITCODE -ne 0) { Fail "Couldn't create $Venv." }
}
& $Py -m pip install --disable-pip-version-check -r (Join-Path $Dir 'requirements.txt')
if ($LASTEXITCODE -ne 0) { Fail "Installing the dependencies failed (see above). Check your internet connection and try again." }

Step 'Downloading the speech model (about 250 MB the first time)'
& $Py (Join-Path $Dir 'lmu_chat.py') --download-model
if ($LASTEXITCODE -ne 0) { Write-Host 'The download failed; the app will try again when it starts.' -ForegroundColor Yellow }

Step 'Adding shortcuts'
$Icon = Join-Path $Dir 'lmu_chat.ico'
& $Py (Join-Path $Dir 'tray.py') --icon $Icon
if ($LASTEXITCODE -ne 0) { Fail "Couldn't create the icon." }
$AppArgs = '"' + (Join-Path $Dir 'lmu_chat.py') + '"'
$StartMenu = Join-Path ([Environment]::GetFolderPath('Programs')) "$AppName.lnk"
$Desktop = Join-Path ([Environment]::GetFolderPath('Desktop')) "$AppName.lnk"
New-Shortcut $StartMenu $Pyw $AppArgs $Icon
New-Shortcut $Desktop $Pyw $AppArgs $Icon
Write-Host "Start Menu and desktop: $AppName"

if (-not $Here) {
    # Settings > Apps lists it, with an Uninstall button.
    $size = (Get-ChildItem $Dir -Recurse -File -Force | Measure-Object Length -Sum).Sum
    New-Item $UninstallKey -Force | Out-Null
    $values = @{
        DisplayName = $AppName; DisplayVersion = $Version; DisplayIcon = $Icon
        InstallLocation = $Dir; NoModify = 1; NoRepair = 1; EstimatedSize = [int]($size / 1KB)
        UninstallString = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$Dir\uninstall.ps1`""
    }
    foreach ($name in $values.Keys) {
        $type = if ($values[$name] -is [int]) { 'DWord' } else { 'String' }
        New-ItemProperty $UninstallKey -Name $name -Value $values[$name] -PropertyType $type -Force | Out-Null
    }
}

Write-Host ''
Write-Host "$AppName $Version is installed." -ForegroundColor Green
if (-not $NoStart) {
    Start-Process $Pyw -ArgumentList $AppArgs -WorkingDirectory $Dir
    Write-Host 'It is running in the system tray (on Windows 11, look behind the ^ arrow).'
    Write-Host 'Right-click its icon > Set push-to-talk button... to choose your key or wheel button.'
}

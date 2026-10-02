$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$venv = Join-Path $PSScriptRoot ".venv"
$python = Join-Path $venv "Scripts\python.exe"
$browsers = Join-Path $PSScriptRoot "data\playwright-browsers"
$marker = Join-Path $browsers ".chromium-installed"

if (-not (Test-Path $python)) {
    $pyLauncher = Get-Command py -ErrorAction SilentlyContinue
    if ($null -ne $pyLauncher) {
        & $pyLauncher.Source -3.12 -m venv $venv
    } else {
        & python -m venv $venv
    }
}

& $python -m pip install --upgrade pip
& $python -m pip install -r (Join-Path $PSScriptRoot "requirements-windows.txt")
if (-not (Test-Path $marker)) {
    New-Item -ItemType Directory -Force $browsers | Out-Null
    $env:PLAYWRIGHT_BROWSERS_PATH = $browsers
    & $python -m playwright install chromium
    [IO.File]::WriteAllText($marker, "installed")
}

$env:PLAYWRIGHT_BROWSERS_PATH = $browsers
$env:PYTHONUNBUFFERED = "1"
& $python (Join-Path $PSScriptRoot "panel.py")

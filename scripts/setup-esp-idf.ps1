param(
    [string]$IdfVersion = "v5.5.2",
    [string]$Target = "esp32s3"
)

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$referencesDir = Join-Path $repoRoot "references"
$idfDir = Join-Path $referencesDir "esp-idf-v5.5.2"
$idfPythonEnv = Join-Path $env:USERPROFILE ".espressif\python_env\idf5.5_py3.12_env\Scripts"

if (Test-Path -LiteralPath (Join-Path $idfPythonEnv "python.exe")) {
    $env:PATH = "$idfPythonEnv;$env:PATH"
} elseif (-not (Get-Command python -ErrorAction SilentlyContinue) -and -not (Get-Command py -ErrorAction SilentlyContinue)) {
    throw "Python was not found. Install Python 3.10+ first, or use Espressif's Windows installer, then rerun this script."
}

if (-not (Test-Path -LiteralPath $referencesDir)) {
    New-Item -ItemType Directory -Path $referencesDir | Out-Null
}

if (-not (Test-Path -LiteralPath $idfDir)) {
    Write-Host "Cloning ESP-IDF $IdfVersion into $idfDir"
    git clone --branch $IdfVersion --recursive https://github.com/espressif/esp-idf.git $idfDir
} else {
    Write-Host "ESP-IDF already exists at $idfDir"
}

Write-Host "Installing ESP-IDF tools for target $Target"
& (Join-Path $idfDir "install.ps1") $Target

Write-Host "Done. Activate it with:"
Write-Host "  . .\references\esp-idf-v5.5.2\export.ps1"

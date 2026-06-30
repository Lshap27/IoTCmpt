param(
    [string]$BuildDir = "build-esp32s3",
    [string]$Target = "esp32s3"
)

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$idfDir = Join-Path $repoRoot "references\esp-idf-v5.5.2"
$projectDir = Join-Path $repoRoot "s3-sensor-cloud"
$idfPythonEnv = Join-Path $env:USERPROFILE ".espressif\python_env\idf5.5_py3.12_env\Scripts"

if (-not (Test-Path -LiteralPath (Join-Path $idfDir "export.ps1"))) {
    throw "ESP-IDF not found at $idfDir. Run scripts\setup-esp-idf.ps1 first."
}

if (Test-Path -LiteralPath (Join-Path $idfPythonEnv "python.exe")) {
    $env:PATH = "$idfPythonEnv;$env:PATH"
} elseif (-not (Get-Command python -ErrorAction SilentlyContinue) -and -not (Get-Command py -ErrorAction SilentlyContinue)) {
    throw "Python was not found. Run scripts\setup-esp-idf.ps1 after installing Python 3.10+."
}

Push-Location $projectDir
try {
    . (Join-Path $idfDir "export.ps1")
    idf.py -B $BuildDir -D IDF_TARGET=$Target build
} finally {
    Pop-Location
}

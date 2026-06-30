param(
    [string]$BuildDir = "build-esp32s3",
    [string]$Target = "esp32s3"
)

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$projectDir = Join-Path $repoRoot "s3-sensor-cloud"
$eimConfig = "C:\Espressif\tools\eim_idf.json"
$idfDir = Join-Path $repoRoot "references\esp-idf-v5.5.2"
$activationScript = $null

if (Test-Path -LiteralPath $eimConfig) {
    $eim = Get-Content -LiteralPath $eimConfig -Raw | ConvertFrom-Json
    $selected = $eim.idfInstalled | Where-Object { $_.id -eq $eim.idfSelectedId } | Select-Object -First 1
    if (-not $selected) {
        $selected = $eim.idfInstalled | Where-Object { $_.name -eq "v5.5.2" } | Select-Object -First 1
    }
    if ($selected -and (Test-Path -LiteralPath $selected.activationScript)) {
        $idfDir = $selected.path
        $activationScript = $selected.activationScript
        Write-Host "Using EIM ESP-IDF setup: $($selected.name) at $idfDir"
    }
}

if (-not $activationScript) {
    $idfPythonEnv = Join-Path $env:USERPROFILE ".espressif\python_env\idf5.5_py3.12_env\Scripts"
    $activationScript = Join-Path $idfDir "export.ps1"

    if (-not (Test-Path -LiteralPath $activationScript)) {
        throw "ESP-IDF not found. Run scripts\setup-esp-idf.ps1 or install ESP-IDF v5.5.2 with EIM."
    }

    if (Test-Path -LiteralPath (Join-Path $idfPythonEnv "python.exe")) {
        $env:PATH = "$idfPythonEnv;$env:PATH"
    } elseif (-not (Get-Command python -ErrorAction SilentlyContinue) -and -not (Get-Command py -ErrorAction SilentlyContinue)) {
        throw "Python was not found. Run scripts\setup-esp-idf.ps1 or use Espressif EIM."
    }
}

Push-Location $projectDir
try {
    . $activationScript
    idf.py -B $BuildDir -D IDF_TARGET=$Target build
} finally {
    Pop-Location
}

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("Install", "Menuconfig", "Build")]
    [string] $Action
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$FirmwarePath = Join-Path $RepoRoot "firmware\esp32s3"

function Add-IdfCandidate {
    param(
        [Parameter(Mandatory = $false)]
        [AllowEmptyString()]
        [string] $Path
    )

    if (-not [string]::IsNullOrWhiteSpace($Path) -and $script:IdfCandidates -notcontains $Path) {
        $script:IdfCandidates += $Path
    }
}

function Get-IdfPath {
    $script:IdfCandidates = @()
    Add-IdfCandidate -Path $env:IDF_PATH

    $settingsPath = Join-Path $RepoRoot ".vscode\settings.json"
    if (Test-Path -LiteralPath $settingsPath) {
        try {
            $settings = Get-Content -LiteralPath $settingsPath -Raw | ConvertFrom-Json
            $setup = $settings.PSObject.Properties["idf.currentSetup"]
            if ($null -ne $setup) {
                Add-IdfCandidate -Path ([string] $setup.Value)
            }
        }
        catch {
            Write-Verbose "Could not read ${settingsPath}: $($_.Exception.Message)"
        }
    }

    $idfEnvPath = Join-Path $env:USERPROFILE ".espressif\idf-env.json"
    if (Test-Path -LiteralPath $idfEnvPath) {
        try {
            $idfEnvironment = Get-Content -LiteralPath $idfEnvPath -Raw | ConvertFrom-Json
            if ($null -ne $idfEnvironment.idfInstalled) {
                foreach ($entry in $idfEnvironment.idfInstalled.PSObject.Properties) {
                    Add-IdfCandidate -Path ([string] $entry.Value.path)
                }
            }
        }
        catch {
            Write-Verbose "Could not read ${idfEnvPath}: $($_.Exception.Message)"
        }
    }

    if (Test-Path -LiteralPath "C:\esp") {
        Get-ChildItem -LiteralPath "C:\esp" -Directory -ErrorAction SilentlyContinue | ForEach-Object {
            Add-IdfCandidate -Path (Join-Path $_.FullName "esp-idf")
        }
    }

    foreach ($candidate in $script:IdfCandidates) {
        if (Test-Path -LiteralPath (Join-Path $candidate "export.ps1")) {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
    }

    throw "未找到 ESP-IDF。请先安装 Espressif IDF 扩展并完成其配置，然后重新运行此任务。"
}

function Set-IdfToolEnvironment {
    # Espressif's Windows installer commonly places the shared toolchain under
    # C:\Espressif, while the Python environment stays under the user profile.
    # Prefer that complete shared toolchain when it is available.
    if (-not [string]::IsNullOrWhiteSpace($env:IDF_TOOLS_PATH)) {
        return
    }

    $sharedToolsPath = "C:\Espressif"
    $requiredTools = @(
        "xtensa-esp-elf-gdb",
        "riscv32-esp-elf-gdb",
        "xtensa-esp-elf",
        "riscv32-esp-elf",
        "cmake",
        "ninja",
        "openocd-esp32",
        "idf-exe",
        "ccache",
        "dfu-util",
        "esp-rom-elfs"
    )

    foreach ($tool in $requiredTools) {
        if (-not (Test-Path -LiteralPath (Join-Path $sharedToolsPath "tools\$tool"))) {
            return
        }
    }

    $pythonEnvironment = $null
    $bundledPythonEnvironment = Join-Path $sharedToolsPath "tools\python\v5.5.2\venv"
    if (Test-Path -LiteralPath (Join-Path $bundledPythonEnvironment "Scripts\python.exe")) {
        $pythonEnvironment = Get-Item -LiteralPath $bundledPythonEnvironment
    }

    $pythonEnvRoots = @(
        (Join-Path $sharedToolsPath "python_env"),
        (Join-Path $env:USERPROFILE ".espressif\python_env")
    )

    if ($null -eq $pythonEnvironment) {
        foreach ($pythonEnvRoot in $pythonEnvRoots) {
            $candidate = Get-ChildItem -LiteralPath $pythonEnvRoot -Directory -Filter "idf5.5_py*_env" -ErrorAction SilentlyContinue |
                Where-Object { Test-Path -LiteralPath (Join-Path $_.FullName "Scripts\python.exe") } |
                Select-Object -First 1
            if ($null -ne $candidate) {
                $pythonEnvironment = $candidate
                break
            }
        }
    }

    if ($null -eq $pythonEnvironment) {
        return
    }

    $env:IDF_TOOLS_PATH = $sharedToolsPath
    $env:IDF_PYTHON_ENV_PATH = $pythonEnvironment.FullName

    if (-not (Test-Path -LiteralPath (Join-Path $sharedToolsPath "espidf.constraints.v5.5.txt"))) {
        # Older installers may keep the constraint file in the user profile.
        # The selected environment was created from this ESP-IDF's constraints.
        $env:IDF_PYTHON_CHECK_CONSTRAINTS = "0"
    }
}

$IdfPath = Get-IdfPath
Set-IdfToolEnvironment

if ($Action -eq "Install") {
    Write-Host "Installing or repairing ESP-IDF tools for ESP32-S3..." -ForegroundColor Cyan
    & (Join-Path $IdfPath "install.ps1") "esp32s3"
    exit $LASTEXITCODE
}

try {
    . (Join-Path $IdfPath "export.ps1")
    $idfCommand = Get-Command idf.py -ErrorAction Stop
}
catch {
    throw "ESP-IDF 已找到，但开发环境尚未就绪。请先运行任务 '固件：安装/修复 ESP-IDF 环境'，然后重试。原始原因：$($_.Exception.Message)"
}

Push-Location $FirmwarePath
try {
    if ($Action -eq "Menuconfig") {
        & idf.py -B build-esp32s3 menuconfig
    }
    else {
        & idf.py -B build-esp32s3 build
    }

    exit $LASTEXITCODE
}
finally {
    Pop-Location
}

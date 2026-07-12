[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("Check", "Install", "Menuconfig", "Build", "Flash", "Monitor", "FlashMonitor")]
    [string] $Action,

    # 串口号，例如 COM5。留空时由 idf.py 自动探测。
    [string] $Port
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

# Git Bash/MSYS 终端启动的进程会泄漏 MSYSTEM 变量，
# ESP-IDF 的 idf_tools.py 检测到它会直接报 "MSys/Mingw is not supported" 并退出。
Remove-Item Env:MSYSTEM -ErrorAction SilentlyContinue

if ($Action -eq "Install") {
    Write-Host "Installing or repairing ESP-IDF tools for ESP32-S3..." -ForegroundColor Cyan
    # install.ps1 是 PowerShell 脚本，不会设置 $LASTEXITCODE，因此依据 $? 判定结果
    & (Join-Path $IdfPath "install.ps1") "esp32s3"
    if (-not $?) {
        exit 1
    }
}

try {
    . (Join-Path $IdfPath "export.ps1")
    $idfCommand = Get-Command idf.py -ErrorAction Stop
}
catch {
    throw "ESP-IDF 框架已找到，但工具链尚未就绪。请先运行任务 '固件：安装/修复 ESP-IDF 工具链'，然后重试。原始原因：$($_.Exception.Message)"
}

function Test-IdfEnvironment {
    $requiredCommands = @(
        "python",
        "cmake",
        "ninja",
        "openocd"
    )
    $missing = @($requiredCommands | Where-Object {
        $null -eq (Get-Command $_ -ErrorAction SilentlyContinue)
    })
    if ($missing.Count -gt 0) {
        throw "ESP-IDF 工具链不完整，缺少命令：$($missing -join ', ')"
    }
    $xtensaCompiler = @("xtensa-esp-elf-gcc", "xtensa-esp32s3-elf-gcc") |
        Where-Object { $null -ne (Get-Command $_ -ErrorAction SilentlyContinue) } |
        Select-Object -First 1
    if (-not $xtensaCompiler) {
        throw "ESP-IDF 工具链不完整，缺少 ESP32-S3 Xtensa 编译器。"
    }

    $versionOutput = (& idf.py --version 2>&1 | Out-String).Trim()
    if ($LASTEXITCODE -ne 0 -or $versionOutput -notmatch "(?i)ESP-IDF\s+v?(\d+)\.(\d+)(?:\.(\d+))?") {
        throw "无法确认 ESP-IDF 版本：$versionOutput"
    }
    $major = [int] $Matches[1]
    $minor = [int] $Matches[2]
    if ($major -ne 5 -or $minor -lt 1) {
        throw "当前项目要求 ESP-IDF >=5.1 且 <6.0，检测到：$versionOutput"
    }

    $pythonVersion = (& python --version 2>&1 | Out-String).Trim()
    Write-Host "ESP-IDF environment is ready." -ForegroundColor Green
    Write-Host "  Framework: $versionOutput"
    Write-Host "  Framework path: $IdfPath"
    Write-Host "  Tools root: $env:IDF_TOOLS_PATH"
    Write-Host "  Python environment: $env:IDF_PYTHON_ENV_PATH"
    Write-Host "  Python: $pythonVersion"
    Write-Host "  Xtensa compiler: $xtensaCompiler"
}

if ($Action -in @("Check", "Install")) {
    Test-IdfEnvironment
    exit 0
}

Push-Location $FirmwarePath
try {
    $idfArgs = @("-B", "build")
    if (-not [string]::IsNullOrWhiteSpace($Port)) {
        $idfArgs += @("-p", $Port)
    }

    switch ($Action) {
        "Menuconfig" { & idf.py @idfArgs menuconfig }
        "Build" { & idf.py @idfArgs build }
        "Flash" { & idf.py @idfArgs flash }
        "Monitor" { & idf.py @idfArgs monitor }
        "FlashMonitor" { & idf.py @idfArgs flash monitor }
    }

    exit $LASTEXITCODE
}
finally {
    Pop-Location
}

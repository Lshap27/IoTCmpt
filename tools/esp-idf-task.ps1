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
. (Join-Path $PSScriptRoot "esp-idf-environment.ps1")

function Test-IdfEnvironment {
    param([Parameter(Mandatory = $true)] [object] $Setup)

    $requiredCommands = @("python", "cmake", "ninja", "openocd")
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
    Write-Host "  Framework path: $($Setup.IdfPath)"
    Write-Host "  Setup source: $($Setup.Source)"
    Write-Host "  Tools root: $env:IDF_TOOLS_PATH"
    Write-Host "  Python environment: $env:IDF_PYTHON_ENV_PATH"
    Write-Host "  Python: $pythonVersion"
    Write-Host "  Xtensa compiler: $xtensaCompiler"
}

$setup = Get-EspIdfSetup -RepoRoot $RepoRoot

if ($Action -eq "Install" -and [string]::IsNullOrWhiteSpace([string] $setup.ActivationScript)) {
    Write-Host "Installing or repairing ESP-IDF tools for ESP32-S3..." -ForegroundColor Cyan
    $env:IDF_PATH = $setup.IdfPath
    if (-not [string]::IsNullOrWhiteSpace([string] $setup.ToolsPath)) {
        $env:IDF_TOOLS_PATH = $setup.ToolsPath
    }
    & (Join-Path $setup.IdfPath "install.ps1") "esp32s3"
    if (-not $?) { exit 1 }
}

try {
    Enable-EspIdfSetup $setup
    $null = Get-Command idf.py -ErrorAction Stop
}
catch {
    throw "ESP-IDF 安装已找到，但环境激活失败。来源：$($setup.Source)。原始原因：$($_.Exception.Message)"
}

if ($Action -in @("Check", "Install")) {
    try {
        Test-IdfEnvironment $setup
    }
    catch {
        if ($Action -eq "Install" -and -not [string]::IsNullOrWhiteSpace([string] $setup.ActivationScript)) {
            throw "EIM 安装记录存在，但工具链验证失败。请在 ESP-IDF Installation Manager 中修复版本 $($setup.Id)，然后重试。原始原因：$($_.Exception.Message)"
        }
        throw
    }
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

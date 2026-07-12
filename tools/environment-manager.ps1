[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("Check", "Install", "Uninstall", "Network", "TestNetwork")]
    [string] $Action,

    [string] $Components = "",

    [ValidateSet("Official", "ChinaMirror", "SystemProxy", "ManualProxy")]
    [string] $NetworkMode = "Official",

    [string] $ProxyUrl = "",
    [string] $MirrorUrl = "https://docker.m.daocloud.io",
    [string] $Confirm = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[Console]::InputEncoding = $Utf8NoBom
[Console]::OutputEncoding = $Utf8NoBom
$OutputEncoding = $Utf8NoBom
$RepoRoot = Split-Path -Parent $PSScriptRoot
$DockerConfigDir = Join-Path $env:USERPROFILE ".docker"
$DockerDaemonPath = Join-Path $DockerConfigDir "daemon.json"

function Test-Command {
    param([string] $Name)
    return $null -ne (Get-Command $Name -ErrorAction SilentlyContinue)
}

function Get-CommandVersion {
    param([string] $Name, [string[]] $Arguments)
    if (-not (Test-Command $Name)) { return "" }
    try {
        $value = & $Name @Arguments 2>$null | Select-Object -First 1
        return "$value".Trim()
    } catch { return "" }
}

function Test-TcpPort {
    param([string] $HostName, [int] $Port, [int] $TimeoutMs = 1800)
    $client = [System.Net.Sockets.TcpClient]::new()
    try {
        $wait = $client.BeginConnect($HostName, $Port, $null, $null)
        if (-not $wait.AsyncWaitHandle.WaitOne($TimeoutMs)) { return $false }
        $client.EndConnect($wait)
        return $true
    } catch { return $false } finally { $client.Dispose() }
}

function Invoke-CapturedPowerShell {
    param([string] $ScriptPath, [string] $ScriptAction)
    $startInfo = New-Object System.Diagnostics.ProcessStartInfo
    $startInfo.FileName = "powershell.exe"
    $escapedPath = $ScriptPath.Replace('"', '\"')
    $startInfo.Arguments = "-NoLogo -NoProfile -ExecutionPolicy Bypass -File `"$escapedPath`" -Action $ScriptAction"
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    $process = New-Object System.Diagnostics.Process
    $process.StartInfo = $startInfo
    $null = $process.Start()
    $stdout = $process.StandardOutput.ReadToEnd()
    $stderr = $process.StandardError.ReadToEnd()
    $process.WaitForExit()
    return [ordered]@{ exitCode=$process.ExitCode; stdout=$stdout; stderr=$stderr }
}

function Get-DockerMirrors {
    if (-not (Test-Path -LiteralPath $DockerDaemonPath)) { return @() }
    try {
        $config = Get-Content -LiteralPath $DockerDaemonPath -Raw | ConvertFrom-Json
        $property = $config.PSObject.Properties["registry-mirrors"]
        if ($null -eq $property) { return @() }
        return @($property.Value)
    } catch { return @() }
}

function Get-EnvironmentReport {
    $dockerInstalled = Test-Command "docker"
    $dockerRunning = $false
    $composeVersion = ""
    if ($dockerInstalled) {
        try {
            $null = & docker info --format "{{.ServerVersion}}" 2>$null
            $dockerRunning = $LASTEXITCODE -eq 0
            $composeVersion = Get-CommandVersion "docker" @("compose", "version")
        } catch { $dockerRunning = $false }
    }

    $idfCandidates = [System.Collections.Generic.List[string]]::new()
    if ($env:IDF_PATH) { $idfCandidates.Add($env:IDF_PATH) }
    $vscodeSettings = Join-Path $RepoRoot ".vscode\settings.json"
    if (Test-Path -LiteralPath $vscodeSettings) {
        try {
            $settings = Get-Content -LiteralPath $vscodeSettings -Raw | ConvertFrom-Json
            if ($settings.PSObject.Properties["idf.currentSetup"]) {
                $idfCandidates.Add([string] $settings."idf.currentSetup")
            }
        } catch {}
    }
    $idfEnvPath = Join-Path $env:USERPROFILE ".espressif\idf-env.json"
    if (Test-Path -LiteralPath $idfEnvPath) {
        try {
            $idfEnvironment = Get-Content -LiteralPath $idfEnvPath -Raw | ConvertFrom-Json
            if ($null -ne $idfEnvironment.idfInstalled) {
                foreach ($entry in $idfEnvironment.idfInstalled.PSObject.Properties) {
                    if ($entry.Value.path) { $idfCandidates.Add([string] $entry.Value.path) }
                }
            }
        } catch {}
    }
    if (Test-Path -LiteralPath "C:\esp") {
        Get-ChildItem -LiteralPath "C:\esp" -Directory -ErrorAction SilentlyContinue |
            ForEach-Object { $idfCandidates.Add((Join-Path $_.FullName "esp-idf")) }
    }
    $idfCandidates.Add("C:\esp\esp-idf")

    $idfPath = @($idfCandidates | Select-Object -Unique | Where-Object {
        $_ -and (Test-Path -LiteralPath (Join-Path $_ "export.ps1"))
    } | Select-Object -First 1)[0]
    $idfFound = -not [string]::IsNullOrWhiteSpace($idfPath)
    $idfVersion = ""
    $idfCompatible = $false
    if ($idfFound) {
        $versionFile = Join-Path $idfPath "tools\cmake\version.cmake"
        if (Test-Path -LiteralPath $versionFile) {
            $versionText = Get-Content -LiteralPath $versionFile -Raw
            $majorMatch = [regex]::Match($versionText, "IDF_VERSION_MAJOR\s+(\d+)")
            $minorMatch = [regex]::Match($versionText, "IDF_VERSION_MINOR\s+(\d+)")
            $patchMatch = [regex]::Match($versionText, "IDF_VERSION_PATCH\s+(\d+)")
            if ($majorMatch.Success -and $minorMatch.Success) {
                $major = [int] $majorMatch.Groups[1].Value
                $minor = [int] $minorMatch.Groups[1].Value
                $patch = if ($patchMatch.Success) { [int] $patchMatch.Groups[1].Value } else { 0 }
                $idfVersion = "$major.$minor.$patch"
                # esp32-camera 2.1.7 requires IDF >=5.1. Keep the next major as an explicit review boundary.
                $idfCompatible = $major -eq 5 -and $minor -ge 1
            }
        }
    }

    $idfToolsPath = ""
    foreach ($path in @(
        $(if ($env:IDF_TOOLS_PATH -and (Test-Path (Join-Path $env:IDF_TOOLS_PATH "tools"))) { Join-Path $env:IDF_TOOLS_PATH "tools" } elseif ($env:IDF_TOOLS_PATH) { $env:IDF_TOOLS_PATH }),
        "C:\Espressif\tools",
        (Join-Path $env:USERPROFILE ".espressif\tools")
    )) {
        if ($path -and (Test-Path -LiteralPath $path)) { $idfToolsPath = $path; break }
    }
    $idfPythonPath = ""
    foreach ($path in @(
        $env:IDF_PYTHON_ENV_PATH,
        $(if ($idfVersion) { "C:\Espressif\tools\python\v$idfVersion\venv" })
    )) {
        if ($path -and (Test-Path -LiteralPath (Join-Path $path "Scripts\python.exe"))) {
            $idfPythonPath = $path
            break
        }
    }
    if (-not $idfPythonPath) {
        $pythonEnvironment = Get-ChildItem (Join-Path $env:USERPROFILE ".espressif\python_env") `
            -Directory -Filter "idf5*_env" -ErrorAction SilentlyContinue |
            Where-Object { Test-Path -LiteralPath (Join-Path $_.FullName "Scripts\python.exe") } |
            Select-Object -First 1
        if ($null -ne $pythonEnvironment) { $idfPythonPath = $pythonEnvironment.FullName }
    }

    $idfToolchainReady = $false
    if ($idfFound -and $idfCompatible) {
        $idfCheck = Invoke-CapturedPowerShell `
            (Join-Path $RepoRoot "tools\esp-idf-task.ps1") "Check"
        $idfToolchainReady = $idfCheck.exitCode -eq 0
    }

    $dnsAddresses = @()
    try {
        $dnsAddresses = @([System.Net.Dns]::GetHostAddresses("registry-1.docker.io") |
            ForEach-Object { $_.IPAddressToString })
    } catch {}
    $fakeIp = @($dnsAddresses | Where-Object { $_ -match "^198\.(18|19)\." }).Count -gt 0

    $internetSettings = Get-ItemProperty `
        "HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings" `
        -ErrorAction SilentlyContinue
    $proxyEnabled = $null -ne $internetSettings -and [int]$internetSettings.ProxyEnable -eq 1
    $proxyServer = if ($null -ne $internetSettings) { "$($internetSettings.ProxyServer)" } else { "" }

    $tunAdapters = @()
    $tunDefaultRoute = $false
    try {
        $tunAdapters = @(Get-NetAdapter -ErrorAction SilentlyContinue |
            Where-Object {
                $_.Status -eq "Up" -and
                ("$($_.Name) $($_.InterfaceDescription)" -match "(?i)TUN|Wintun|Meta Tunnel|Clash")
            } | ForEach-Object {
                [ordered]@{
                    name = $_.Name
                    description = $_.InterfaceDescription
                    interfaceIndex = $_.InterfaceIndex
                }
            })
        $tunIndexes = @($tunAdapters | ForEach-Object { $_.interfaceIndex })
        if ($tunIndexes.Count -gt 0) {
            $tunDefaultRoute = $null -ne (Get-NetRoute -AddressFamily IPv4 -DestinationPrefix "0.0.0.0/0" `
                -ErrorAction SilentlyContinue | Where-Object { $tunIndexes -contains $_.InterfaceIndex } |
                Select-Object -First 1)
        }
    } catch {}

    $components = @(
        [ordered]@{ id="docker"; label="Docker Desktop"; required=$true; installed=$dockerInstalled; ready=$dockerRunning; version=(Get-CommandVersion "docker" @("--version")); canInstall=$true; canUninstall=$true; detail=$(if (-not $dockerInstalled) { "未安装" } elseif (-not $dockerRunning) { "已安装，Docker 引擎未运行" } else { "Docker 引擎运行中" }) },
        [ordered]@{ id="compose"; label="Docker Compose"; required=$true; installed=([bool]$composeVersion); ready=([bool]$composeVersion -and $dockerRunning); version=$composeVersion; canInstall=$false; canUninstall=$false; detail="随 Docker Desktop 安装" },
        [ordered]@{ id="pwsh"; label="PowerShell 7"; required=$true; installed=(Test-Command "pwsh"); ready=(Test-Command "pwsh"); version=(Get-CommandVersion "pwsh" @("--version")); canInstall=$true; canUninstall=$true; detail="手动命令和维护脚本" },
        [ordered]@{ id="python"; label="Python 3"; required=$true; installed=(Test-Command "python"); ready=(Test-Command "python"); version=(Get-CommandVersion "python" @("--version")); canInstall=$true; canUninstall=$true; detail="配置面板和设备模拟器" },
        [ordered]@{ id="git"; label="Git"; required=$false; installed=(Test-Command "git"); ready=(Test-Command "git"); version=(Get-CommandVersion "git" @("--version")); canInstall=$true; canUninstall=$true; detail="获取和更新项目" },
        [ordered]@{ id="uv"; label="uv + 服务端依赖"; required=$false; installed=(Test-Command "uv"); ready=(Test-Path -LiteralPath (Join-Path $RepoRoot "server\.venv\Scripts\python.exe")); version=(Get-CommandVersion "uv" @("--version")); canInstall=$true; canUninstall=$true; detail="不用 Docker 时运行后端和模拟器" },
        [ordered]@{ id="node"; label="Node.js + pnpm"; required=$false; installed=(Test-Command "node"); ready=((Test-Command "node") -and (Test-Command "pnpm")); version=(Get-CommandVersion "node" @("--version")); canInstall=$true; canUninstall=$true; detail="不用 Docker 时运行前端" },
        [ordered]@{
            id="espidf"; label="ESP-IDF + 工具链"; required=$false; installed=$idfFound;
            ready=($idfFound -and $idfCompatible -and $idfToolchainReady);
            version=$(if ($idfVersion) { "v$idfVersion" } else { "" });
            canInstall=$idfFound; canUninstall=$false;
            detail=$(if (-not $idfFound) { "未找到 ESP-IDF 框架源码" }
                elseif (-not $idfCompatible) { "版本不兼容，项目要求 >=5.1 且 <6.0" }
                elseif (-not $idfToolchainReady) { "框架已找到，工具链或 Python 环境需要修复" }
                else { "框架、Python、CMake、Ninja、Xtensa 工具链和 OpenOCD 均可用" });
            sourcePath=$idfPath; toolsPath=$idfToolsPath; pythonPath=$idfPythonPath;
            frameworkFound=$idfFound; versionCompatible=$idfCompatible; toolchainReady=$idfToolchainReady
        }
    )

    $mirrors = @(Get-DockerMirrors)
    $requiredReady = @($components | Where-Object { $_.required -and -not $_.ready }).Count -eq 0
    $networkWarning = ""
    $networkWarningLevel = "none"
    if ($fakeIp -and -not $proxyEnabled -and $mirrors.Count -eq 0) {
        if ($tunDefaultRoute) {
            $networkWarning = "已检测到 TUN 模式和 198.18/19 Fake-IP；系统代理关闭属于正常状态。Docker Desktop 是否被 TUN 接管，请以【测试 Docker 拉取网络】的结果为准。"
            $networkWarningLevel = "info"
        } else {
            $networkWarning = "Docker Hub 被解析到 198.18/19 Fake-IP，但未检测到系统代理或活动 TUN 默认路由；Docker Desktop 直连可能失败。"
            $networkWarningLevel = "warning"
        }
    }
    return [ordered]@{
        checkedAt = (Get-Date).ToString("s")
        overallReady = $requiredReady
        components = $components
        network = [ordered]@{
            dockerHubDns = $dnsAddresses
            fakeIpDetected = $fakeIp
            hostHttpsReachable = Test-TcpPort "registry-1.docker.io" 443
            systemProxyEnabled = $proxyEnabled
            systemProxy = $proxyServer
            tunDetected = $tunAdapters.Count -gt 0
            tunDefaultRoute = $tunDefaultRoute
            tunAdapters = $tunAdapters
            registryMirrors = $mirrors
            daemonConfigPath = $DockerDaemonPath
            warning = $networkWarning
            warningLevel = $networkWarningLevel
        }
    }
}

function Invoke-Winget {
    param([ValidateSet("install", "uninstall")] [string] $Verb, [string] $Id)
    if (-not (Test-Command "winget")) { throw "未找到 winget，请先安装或更新 Windows App Installer。" }
    Write-Host "[$Verb] $Id" -ForegroundColor Cyan
    & winget $Verb --id $Id --exact --accept-source-agreements --disable-interactivity
    if ($LASTEXITCODE -ne 0) { throw "winget $Verb $Id 失败，退出代码 $LASTEXITCODE" }
}

function Install-Components {
    $requested = @($Components.Split(",", [System.StringSplitOptions]::RemoveEmptyEntries) |
        ForEach-Object { $_.Trim().ToLowerInvariant() })
    if ($requested -contains "demo") { $requested += @("docker", "pwsh", "python", "git", "uv") }
    $requested = @($requested | Select-Object -Unique)
    $packages = @{
        docker="Docker.DockerDesktop"; pwsh="Microsoft.PowerShell"; python="Python.Python.3.12";
        git="Git.Git"; uv="astral-sh.uv"; node="OpenJS.NodeJS.LTS"
    }
    foreach ($component in $requested) {
        if ($component -eq "espidf") {
            Write-Host "[修复] 检查并安装 ESP-IDF 的 ESP32-S3 工具链" -ForegroundColor Cyan
            & powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File `
                (Join-Path $RepoRoot "tools\esp-idf-task.ps1") -Action Install
            if ($LASTEXITCODE -ne 0) { throw "ESP-IDF 工具链安装或验证失败。" }
            continue
        }
        if (-not $packages.ContainsKey($component)) { throw "不支持安装组件：$component" }
        $commandName = @{ docker="docker"; pwsh="pwsh"; python="python"; git="git"; uv="uv"; node="node" }[$component]
        if (Test-Command $commandName) {
            Write-Host "[跳过] $component 已安装" -ForegroundColor Green
        } else {
            Invoke-Winget "install" $packages[$component]
        }
    }
    if ($requested -contains "uv") {
        $uv = Get-Command uv -ErrorAction SilentlyContinue
        if ($null -ne $uv) {
            Write-Host "[配置] 创建服务端虚拟环境（用于设备模拟器）" -ForegroundColor Cyan
            Push-Location (Join-Path $RepoRoot "server")
            try { & $uv.Source sync --frozen; if ($LASTEXITCODE -ne 0) { throw "uv sync 失败" } } finally { Pop-Location }
        } else {
            Write-Host "uv 已安装但当前面板进程尚未刷新 PATH；重开面板后点击一次‘补全演示环境’即可同步依赖。" -ForegroundColor Yellow
        }
    }
    if ($requested -contains "node") {
        $corepack = Get-Command corepack -ErrorAction SilentlyContinue
        if ($null -ne $corepack) {
            & $corepack.Source enable
            & $corepack.Source prepare pnpm@11.7.0 --activate
        }
    }
    if ($requested -contains "docker" -and (Test-Command docker)) {
        try { & docker desktop start } catch {}
    }
    Write-Host "环境补全完成。新安装的软件可能需要重开配置面板或注销后才进入 PATH。" -ForegroundColor Green
}

function Uninstall-Components {
    if ($Confirm -ne "UNINSTALL") { throw "卸载确认无效。" }
    $packages = @{
        docker="Docker.DockerDesktop"; pwsh="Microsoft.PowerShell"; python="Python.Python.3.12";
        git="Git.Git"; uv="astral-sh.uv"; node="OpenJS.NodeJS.LTS"
    }
    foreach ($component in @($Components.Split(",", [System.StringSplitOptions]::RemoveEmptyEntries) |
        ForEach-Object { $_.Trim().ToLowerInvariant() } | Select-Object -Unique)) {
        if (-not $packages.ContainsKey($component)) { throw "不支持卸载组件：$component" }
        if ($component -eq "python") {
            Write-Host "跳过 Python：配置面板正在使用它。请关闭面板后运行 winget uninstall Python.Python.3.12。" -ForegroundColor Yellow
            continue
        }
        Invoke-Winget "uninstall" $packages[$component]
    }
    Write-Host "所选组件卸载操作完成；项目文件与 Docker 数据卷未被主动删除。" -ForegroundColor Green
}

function Read-DaemonConfig {
    if (-not (Test-Path -LiteralPath $DockerDaemonPath)) { return [pscustomobject]@{} }
    try { return Get-Content -LiteralPath $DockerDaemonPath -Raw | ConvertFrom-Json }
    catch { throw "Docker daemon.json 不是合法 JSON：$DockerDaemonPath" }
}

function Save-DaemonConfig {
    param([object] $Config)
    New-Item -ItemType Directory -Force -Path $DockerConfigDir | Out-Null
    if (Test-Path -LiteralPath $DockerDaemonPath) {
        Copy-Item -LiteralPath $DockerDaemonPath -Destination "$DockerDaemonPath.bak" -Force
    }
    $json = $Config | ConvertTo-Json -Depth 20
    [System.IO.File]::WriteAllText(
        $DockerDaemonPath, $json, [System.Text.UTF8Encoding]::new($false))
    Write-Host "已写入 $DockerDaemonPath（旧文件备份为 daemon.json.bak）" -ForegroundColor Green
}

function Configure-Network {
    switch ($NetworkMode) {
        "ChinaMirror" {
            if ($MirrorUrl -notmatch "^https?://[^\s]+$") { throw "镜像地址必须是合法的 http(s) URL。" }
            $config = Read-DaemonConfig
            $config | Add-Member -NotePropertyName "registry-mirrors" -NotePropertyValue @($MirrorUrl.TrimEnd('/')) -Force
            Save-DaemonConfig $config
        }
        "Official" {
            $config = Read-DaemonConfig
            if ($null -ne $config.PSObject.Properties["registry-mirrors"]) {
                $config.PSObject.Properties.Remove("registry-mirrors")
                Save-DaemonConfig $config
            } else { Write-Host "当前已经使用 Docker Hub 官方源。" -ForegroundColor Green }
        }
        "SystemProxy" {
            $candidatePorts = @(7890, 7897, 10809, 10808, 1080)
            $port = $candidatePorts | Where-Object { Test-TcpPort "127.0.0.1" $_ 300 } | Select-Object -First 1
            if ($null -eq $port) { throw "没有检测到常见本地代理端口，请选择手动代理并填写地址。" }
            $ProxyUrl = "http://127.0.0.1:$port"
            Set-ItemProperty "HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings" ProxyEnable 1
            Set-ItemProperty "HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings" ProxyServer ($ProxyUrl -replace "^https?://", "")
            Write-Host "已启用 Windows 系统代理：$ProxyUrl" -ForegroundColor Green
        }
        "ManualProxy" {
            if ($ProxyUrl -notmatch "^https?://[^\s:]+:\d+$") { throw "代理地址格式应为 http://主机:端口。" }
            Set-ItemProperty "HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings" ProxyEnable 1
            Set-ItemProperty "HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings" ProxyServer ($ProxyUrl -replace "^https?://", "")
            Write-Host "已启用 Windows 系统代理：$ProxyUrl" -ForegroundColor Green
        }
    }
    if (Test-Command docker) {
        Write-Host "正在重启 Docker Desktop 以应用配置……" -ForegroundColor Cyan
        try { & docker desktop restart } catch { Write-Host "请手动重启 Docker Desktop。" -ForegroundColor Yellow }
    }
}

function Test-DockerNetwork {
    if (-not (Test-Command docker)) { throw "Docker 未安装。" }
    Write-Host "测试 Docker BuildKit 访问 Docker Hub（node:22-alpine manifest）……" -ForegroundColor Cyan
    & docker buildx imagetools inspect "node:22-alpine" *> $null
    if ($LASTEXITCODE -ne 0) { throw "Docker 引擎仍无法访问 Docker Hub。请检查代理软件是否允许局域网连接，或切换国内镜像后重试。" }
    Write-Host "Docker Hub 访问正常。" -ForegroundColor Green
}

switch ($Action) {
    "Check" { Get-EnvironmentReport | ConvertTo-Json -Depth 10 }
    "Install" { Install-Components }
    "Uninstall" { Uninstall-Components }
    "Network" { Configure-Network }
    "TestNetwork" { Test-DockerNetwork }
}

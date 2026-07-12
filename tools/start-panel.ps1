# 启动 IoTCmpt 本地可视化配置面板，并自动打开浏览器。
# 面板为纯 Python 标准库实现，无需安装任何第三方依赖。
[CmdletBinding()]
param(
    [int] $Port = 8765
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$PanelScript = Join-Path $RepoRoot "tools\panel\panel_server.py"
$Url = "http://127.0.0.1:$Port"

function Get-PythonCommand {
    # 依次尝试各候选，找到能真正运行的 Python 3（跳过微软商店占位程序）
    $candidates = @(
        @{ Exe = "python"; Args = @() },
        @{ Exe = "py"; Args = @("-3") },
        @{ Exe = "C:\Espressif\tools\python\python.exe"; Args = @() }
    )

    foreach ($candidate in $candidates) {
        try {
            $output = & $candidate.Exe @($candidate.Args + "--version") 2>&1
            if ($LASTEXITCODE -eq 0 -and "$output" -match "Python 3") {
                return $candidate
            }
        } catch {
            continue
        }
    }

    return $null
}

$python = Get-PythonCommand
if ($null -eq $python) {
    Write-Host "未找到 Python 3。请先安装 Python（https://www.python.org/downloads/），" -ForegroundColor Red
    Write-Host "或运行：winget install Python.Python.3.12" -ForegroundColor Yellow
    Read-Host "按回车键退出"
    exit 1
}

# 端口已被占用说明面板已在运行，直接打开浏览器即可
$existing = Test-NetConnection -ComputerName 127.0.0.1 -Port $Port -InformationLevel Quiet -WarningAction SilentlyContinue
if ($existing) {
    Write-Host "面板已在运行，直接打开浏览器：$Url" -ForegroundColor Cyan
    Start-Process $Url
    exit 0
}

Write-Host "正在启动配置面板……" -ForegroundColor Cyan

$serverArgs = $python.Args + @($PanelScript, "--port", "$Port")
$server = Start-Process -PassThru -NoNewWindow -FilePath $python.Exe -ArgumentList $serverArgs

# 等待端口就绪后打开浏览器（最多 30 秒）
$opened = $false
for ($i = 0; $i -lt 30; $i++) {
    if ($server.HasExited) { break }
    Start-Sleep -Seconds 1
    $ready = Test-NetConnection -ComputerName 127.0.0.1 -Port $Port -InformationLevel Quiet -WarningAction SilentlyContinue
    if ($ready) {
        Start-Process $Url
        $opened = $true
        break
    }
}

if ($server.HasExited) {
    Write-Host "面板启动失败（进程已退出）。请把上方错误信息发给开发同学。" -ForegroundColor Red
    Read-Host "按回车键退出"
    exit 1
}

if (-not $opened) {
    Write-Host "等待超时，请手动打开：$Url" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "面板运行中：$Url  （关闭本窗口即可停止面板）" -ForegroundColor Green
Wait-Process -Id $server.Id

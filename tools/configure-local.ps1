[CmdletBinding()]
param(
    [ValidateSet("MockDemo", "DeviceDemo", "LlmDemo")]
    [string] $Preset = "MockDemo",
    [string] $DeviceId = "esp32s3-001",
    [string] $LanAddress = "127.0.0.1",
    [string] $ApiBaseUrl,
    [string] $LlmEndpoint,
    [string] $LlmModel,
    [string] $LlmApiKey,
    [ValidateSet("Simulator", "Real")]
    [string] $DemoDeviceMode,
    [ValidateSet("Mock", "Online")]
    [string] $DemoAiMode,
    [switch] $NonInteractive,
    [switch] $Force,
    [switch] $DryRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $RepoRoot "server\.venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Python)) {
    $Python = "python"
}

if ([string]::IsNullOrWhiteSpace($DemoDeviceMode)) {
    $DemoDeviceMode = if ($Preset -eq "DeviceDemo") { "Real" } else { "Simulator" }
}
if ([string]::IsNullOrWhiteSpace($DemoAiMode)) {
    $DemoAiMode = if ($Preset -eq "MockDemo") { "Mock" } else { "Online" }
}
if ([string]::IsNullOrWhiteSpace($ApiBaseUrl)) {
    $ApiBaseUrl = if ($DemoDeviceMode -eq "Real") { "http://${LanAddress}:8000" } else { "http://127.0.0.1:8000" }
}
if ([string]::IsNullOrWhiteSpace($LlmEndpoint)) {
    $LlmEndpoint = if ($DemoAiMode -eq "Mock") { "mock" } else { "https://api.deepseek.com" }
}
if ([string]::IsNullOrWhiteSpace($LlmModel)) {
    $LlmModel = if ($DemoAiMode -eq "Mock") { "demo-model" } else { "deepseek-v4-flash" }
}

$Values = @{
    AIOT_DEMO_DEVICE_ID = $DeviceId
    AIOT_DEMO_DEVICE_MODE = $DemoDeviceMode
    AIOT_DEMO_AI_MODE = $DemoAiMode
    AIOT_BASE_URL = $ApiBaseUrl
    NEXT_PUBLIC_API_BASE_URL = $ApiBaseUrl
    AIOT_LLM_ENDPOINT = $LlmEndpoint
    AIOT_LLM_MODEL = $LlmModel
    AIOT_LLM_TIMEOUT_SECONDS = "60"
    AIOT_COMMAND_ACK_TIMEOUT_SECONDS = "60"
}
if (-not [string]::IsNullOrWhiteSpace($LlmApiKey)) {
    $Values.AIOT_LLM_API_KEY = $LlmApiKey
}

$Arguments = @((Join-Path $PSScriptRoot "runtime_config.py"))
if ($DryRun) { $Arguments += "--dry-run" }
$Json = $Values | ConvertTo-Json -Compress
$Json | & $Python @Arguments
if ($LASTEXITCODE -ne 0) {
    throw "runtime_config.py failed with exit code $LASTEXITCODE"
}

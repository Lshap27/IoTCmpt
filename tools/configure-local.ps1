[CmdletBinding()]
param(
    [ValidateSet("MockDemo", "DeviceDemo", "LlmDemo")]
    [string] $Preset = "MockDemo",

    [string] $DeviceId,
    [string] $LanAddress,
    [string] $ApiBaseUrl,
    [string] $LlmEndpoint,
    [string] $LlmModel,
    [string] $LlmApiKey,
    [string] $AutopilotEnabled,
    [string] $AutopilotMinConfidence,
    [string] $AutopilotTriggerLevels,
    [ValidateSet("Simulator", "Real")]
    [string] $DemoDeviceMode,
    [ValidateSet("Mock", "Online")]
    [string] $DemoAiMode,

    # 面板/自动化调用时使用：跳过所有交互提问，未指定的参数取默认值。
    [switch] $NonInteractive,

    # 兼容旧任务定义，无实际作用。
    [switch] $Force
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$ComposeEnvPath = Join-Path $RepoRoot ".env"
$ServerEnvPath = Join-Path $RepoRoot "server\.env"
$WebEnvPath = Join-Path $RepoRoot "web\.env.local"
$DeviceIdDefault = "esp32s3-001"

function Get-DefaultLanAddress {
    try {
        # InterfaceMetric 只在 Get-NetIPInterface 上，Get-NetIPAddress 没有该属性
        $metrics = @{}
        Get-NetIPInterface -AddressFamily IPv4 | ForEach-Object {
            $metrics[$_.InterfaceIndex] = $_.InterfaceMetric
        }

        $addresses = Get-NetIPAddress -AddressFamily IPv4 |
            Where-Object {
                $_.IPAddress -ne "127.0.0.1" -and
                $_.IPAddress -notlike "169.254.*" -and
                $_.IPAddress -notlike "198.18.*" -and
                $_.IPAddress -notlike "198.19.*" -and
                $_.InterfaceAlias -notmatch "vEthernet|WSL|Hyper-V|Default Switch|Docker|Loopback|Clash|TUN|TAP|Tailscale|VPN|WireGuard|Wintun|ZeroTier" -and
                $_.PrefixOrigin -in @("Dhcp", "Manual")
            } |
            Sort-Object { $metrics[$_.InterfaceIndex] }, InterfaceIndex

        if ($addresses) {
            return $addresses[0].IPAddress
        }
    } catch {
        return "127.0.0.1"
    }

    return "127.0.0.1"
}

function Get-ExistingEnvValue {
    param(
        [Parameter(Mandatory = $true)]
        [string] $Path,

        [Parameter(Mandatory = $true)]
        [string] $Key
    )

    if (-not (Test-Path -LiteralPath $Path)) {
        return ""
    }

    foreach ($line in Get-Content -LiteralPath $Path) {
        if ($line -match "^\s*$([regex]::Escape($Key))=(.*)$") {
            return $Matches[1].Trim()
        }
    }

    return ""
}

function Read-Value {
    param(
        [Parameter(Mandatory = $true)]
        [string] $Prompt,

        [Parameter(Mandatory = $true)]
        [string] $Default
    )

    $raw = Read-Host "$Prompt [$Default]"
    if ([string]::IsNullOrWhiteSpace($raw)) {
        return $Default
    }

    return $raw.Trim()
}

function Read-YesNo {
    param(
        [Parameter(Mandatory = $true)]
        [string] $Prompt,

        [bool] $Default = $true
    )

    $hint = if ($Default) { "Y/n" } else { "y/N" }
    while ($true) {
        $raw = Read-Host "$Prompt [$hint]"
        if ([string]::IsNullOrWhiteSpace($raw)) {
            return $Default
        }

        switch -Regex ($raw.Trim()) {
            "^(y|yes|true|1|shi|是)$" { return $true }
            "^(n|no|false|0|bu|否)$" { return $false }
            default { Write-Host "Please answer y or n." -ForegroundColor Yellow }
        }
    }
}

function Read-SecretPlainText {
    param(
        [Parameter(Mandatory = $true)]
        [string] $Prompt
    )

    $secure = Read-Host $Prompt -AsSecureString
    if ($null -eq $secure -or $secure.Length -eq 0) {
        return ""
    }

    return [System.Net.NetworkCredential]::new("", $secure).Password
}

function ConvertTo-EnvValue {
    param(
        [AllowNull()]
        [object] $Value
    )

    if ($null -eq $Value) {
        return ""
    }

    return [string] $Value
}

function Write-LocalEnvFile {
    param(
        [Parameter(Mandatory = $true)]
        [string] $Path,

        [Parameter(Mandatory = $true)]
        [AllowEmptyString()]
        [string[]] $Lines
    )

    $directory = Split-Path -Parent $Path
    if (-not (Test-Path -LiteralPath $directory)) {
        New-Item -ItemType Directory -Path $directory | Out-Null
    }

    Set-Content -LiteralPath $Path -Value $Lines -Encoding utf8
    Write-Host "Wrote $Path" -ForegroundColor Green
}

function New-ServerEnvLines {
    param(
        [Parameter(Mandatory = $true)]
        [hashtable] $Config
    )

    $orderedKeys = @(
        "AIOT_APP_ENV",
        "AIOT_DATABASE_URL",
        "AIOT_AUTO_CREATE_TABLES",
        "AIOT_BASE_URL",
        "AIOT_UPLOADS_DIR",
        "AIOT_MAX_UPLOAD_BYTES",
        "AIOT_MQTT_ENABLED",
        "AIOT_MQTT_HOST",
        "AIOT_MQTT_PORT",
        "AIOT_MQTT_CLIENT_ID",
        "AIOT_MQTT_USERNAME",
        "AIOT_MQTT_PASSWORD",
        "AIOT_MQTT_RECONNECT_SECONDS",
        "AIOT_CORS_ORIGINS",
        "AIOT_LLM_ENDPOINT",
        "AIOT_LLM_API_KEY",
        "AIOT_LLM_MODEL",
        "AIOT_LLM_TIMEOUT_SECONDS",
        "AIOT_LLM_IMAGE_MAX_AGE_SECONDS",
        "AIOT_LLM_RESPONSE_FORMAT",
        "AIOT_AUTOPILOT_ENABLED",
        "AIOT_AUTOPILOT_COOLDOWN_SECONDS",
        "AIOT_AUTOPILOT_MIN_CONFIDENCE",
        "AIOT_AUTOPILOT_TRIGGER_LEVELS"
    )

    $lines = @(
        "# Generated by tools/configure-local.ps1.",
        "# Local only. Do not commit real secrets.",
        ""
    )

    foreach ($key in $orderedKeys) {
        $lines += "$key=$(ConvertTo-EnvValue $Config[$key])"
    }

    return $lines
}

function New-ComposeEnvLines {
    param(
        [Parameter(Mandatory = $true)]
        [hashtable] $Config
    )

    $orderedKeys = @(
        "NEXT_PUBLIC_API_BASE_URL",
        "AIOT_DEMO_DEVICE_MODE",
        "AIOT_DEMO_AI_MODE",
        "AIOT_DEMO_DEVICE_ID",
        "AIOT_DEMO_SCENARIO",
        "AIOT_CORS_ORIGINS",
        "AIOT_LLM_ENDPOINT",
        "AIOT_LLM_API_KEY",
        "AIOT_LLM_MODEL",
        "AIOT_LLM_RESPONSE_FORMAT",
        "AIOT_AUTOPILOT_ENABLED",
        "AIOT_AUTOPILOT_COOLDOWN_SECONDS",
        "AIOT_AUTOPILOT_MIN_CONFIDENCE",
        "AIOT_AUTOPILOT_TRIGGER_LEVELS"
    )

    $lines = @(
        "# Generated by tools/configure-local.ps1.",
        "# Used by docker compose. Local only; do not commit real secrets.",
        ""
    )

    foreach ($key in $orderedKeys) {
        $lines += "$key=$(ConvertTo-EnvValue $Config[$key])"
    }

    return $lines
}

function Show-FirmwareHint {
    param(
        [Parameter(Mandatory = $true)]
        [string] $DeviceId,

        [Parameter(Mandatory = $true)]
        [string] $LanAddress
    )

    Write-Host ""
    Write-Host "Firmware menuconfig values for a real ESP32-S3 demo:" -ForegroundColor Cyan
    Write-Host "  APP_DEVICE_ID=$DeviceId"
    Write-Host "  APP_WIFI_ENABLED=y"
    Write-Host "  APP_MQTT_ENABLED=y"
    Write-Host "  APP_MQTT_BROKER_URI=mqtt://$LanAddress`:1883"
    Write-Host "  APP_IMAGE_UPLOAD_ENABLED=y"
    Write-Host "  APP_IMAGE_UPLOAD_URL=http://$LanAddress`:8000/api/devices/$DeviceId/images"
    Write-Host ""
    Write-Host "Open it from VS Code with: Tasks: Run Task -> 固件：打开图形化配置"
}

function Resolve-Value {
    param(
        [AllowEmptyString()]
        [string] $Bound,

        [Parameter(Mandatory = $true)]
        [string] $Prompt,

        [Parameter(Mandatory = $true)]
        [AllowEmptyString()]
        [string] $Default
    )

    if (-not [string]::IsNullOrWhiteSpace($Bound)) {
        return $Bound.Trim()
    }

    if ($NonInteractive) {
        return $Default
    }

    return Read-Value -Prompt $Prompt -Default $Default
}

function Resolve-Bool {
    param(
        [AllowEmptyString()]
        [string] $Bound,

        [Parameter(Mandatory = $true)]
        [string] $Prompt,

        [bool] $Default = $true
    )

    if (-not [string]::IsNullOrWhiteSpace($Bound)) {
        return ($Bound.Trim() -match "^(y|yes|true|1|shi|是)$")
    }

    if ($NonInteractive) {
        return $Default
    }

    return Read-YesNo -Prompt $Prompt -Default $Default
}

$lanAddressValue = if ([string]::IsNullOrWhiteSpace($LanAddress)) { Get-DefaultLanAddress } else { $LanAddress.Trim() }
$deviceIdValue = if ([string]::IsNullOrWhiteSpace($DeviceId)) { $DeviceIdDefault } else { $DeviceId.Trim() }
$apiBaseUrlValue = if ([string]::IsNullOrWhiteSpace($ApiBaseUrl)) { "http://localhost:8000" } else { $ApiBaseUrl.Trim() }
$serverBaseUrl = "http://127.0.0.1:8000"
$mqttHost = "127.0.0.1"
$llmEndpointValue = if ([string]::IsNullOrWhiteSpace($LlmEndpoint)) { "mock" } else { $LlmEndpoint.Trim() }
$llmApiKeyValue = if ($null -eq $LlmApiKey) { "" } else { $LlmApiKey }
if ([string]::IsNullOrWhiteSpace($llmApiKeyValue)) {
    # 未显式传入 key 时保留现有 server\.env 中的值；面板的“留空则不修改”依赖此行为
    $llmApiKeyValue = Get-ExistingEnvValue -Path $ServerEnvPath -Key "AIOT_LLM_API_KEY"
}
$llmModelValue = if ([string]::IsNullOrWhiteSpace($LlmModel)) { "demo-model" } else { $LlmModel.Trim() }
$autopilotEnabledValue = if ([string]::IsNullOrWhiteSpace($AutopilotEnabled)) { "true" } else { $AutopilotEnabled.Trim().ToLowerInvariant() }
$autopilotMinConfidenceValue = if ([string]::IsNullOrWhiteSpace($AutopilotMinConfidence)) { "0.6" } else { $AutopilotMinConfidence.Trim() }
$autopilotTriggerLevelsValue = if ([string]::IsNullOrWhiteSpace($AutopilotTriggerLevels)) { "alert" } else { $AutopilotTriggerLevels.Trim() }
$demoDeviceModeValue = if ([string]::IsNullOrWhiteSpace($DemoDeviceMode)) { "Simulator" } else { $DemoDeviceMode }
$demoAiModeValue = if ([string]::IsNullOrWhiteSpace($DemoAiMode)) { "Mock" } else { $DemoAiMode }
$demoScenarioValue = Get-ExistingEnvValue -Path $ComposeEnvPath -Key "AIOT_DEMO_SCENARIO"
if ([string]::IsNullOrWhiteSpace($demoScenarioValue)) { $demoScenarioValue = "air-alert" }

switch ($Preset) {
    "MockDemo" {
        Write-Host "Configuring local offline demo with AIOT_LLM_ENDPOINT=mock." -ForegroundColor Cyan
        $llmEndpointValue = "mock"
        $demoDeviceModeValue = "Simulator"
        $demoAiModeValue = "Mock"
    }
    "DeviceDemo" {
        Write-Host "Configuring real-device demo defaults." -ForegroundColor Cyan
        $deviceIdValue = Resolve-Value -Bound $DeviceId -Prompt "Device ID" -Default $DeviceIdDefault
        $lanAddressValue = Resolve-Value -Bound $LanAddress -Prompt "This laptop LAN IP for ESP32-S3" -Default $lanAddressValue
        $serverBaseUrl = "http://$lanAddressValue`:8000"
        $mqttHost = $lanAddressValue
        $apiBaseUrlValue = Resolve-Value -Bound $ApiBaseUrl -Prompt "Web console API base URL" -Default "http://localhost:8000"
        $llmEndpointValue = Resolve-Value -Bound $LlmEndpoint -Prompt "LLM endpoint (use mock for offline demo)" -Default "mock"
        if ($llmEndpointValue -ne "mock" -and -not [string]::IsNullOrWhiteSpace($llmEndpointValue)) {
            $llmModelValue = Resolve-Value -Bound $LlmModel -Prompt "LLM model" -Default "demo-model"
            if ([string]::IsNullOrWhiteSpace($LlmApiKey) -and -not $NonInteractive) {
                $enteredKey = Read-SecretPlainText -Prompt "LLM API key (input hidden, leave empty to keep existing)"
                if (-not [string]::IsNullOrWhiteSpace($enteredKey)) {
                    $llmApiKeyValue = $enteredKey
                }
            }
        }
        $autopilotEnabledValue = if (Resolve-Bool -Bound $AutopilotEnabled -Prompt "Enable autopilot by default?" -Default $true) { "true" } else { "false" }
        $autopilotMinConfidenceValue = Resolve-Value -Bound $AutopilotMinConfidence -Prompt "Autopilot minimum confidence" -Default "0.6"
        $autopilotTriggerLevelsValue = Resolve-Value -Bound $AutopilotTriggerLevels -Prompt "Autopilot trigger levels (comma-separated good/watch/alert)" -Default "alert"
        $demoDeviceModeValue = "Real"
        $demoAiModeValue = if ($llmEndpointValue -eq "mock") { "Mock" } else { "Online" }
    }
    "LlmDemo" {
        Write-Host "Configuring local demo with a real OpenAI-compatible LLM endpoint." -ForegroundColor Cyan
        $llmEndpointValue = Resolve-Value -Bound $LlmEndpoint -Prompt "LLM base URL" -Default "https://api.deepseek.com"
        $llmModelValue = Resolve-Value -Bound $LlmModel -Prompt "LLM model" -Default "deepseek-v4-flash"
        if ([string]::IsNullOrWhiteSpace($LlmApiKey) -and -not $NonInteractive) {
            $enteredKey = Read-SecretPlainText -Prompt "LLM API key (input hidden, leave empty to keep existing)"
            if (-not [string]::IsNullOrWhiteSpace($enteredKey)) {
                $llmApiKeyValue = $enteredKey
            }
        }
        $demoDeviceModeValue = "Simulator"
        $demoAiModeValue = "Online"
    }
}

if ($DemoDeviceMode) { $demoDeviceModeValue = $DemoDeviceMode }
if ($DemoAiMode) { $demoAiModeValue = $DemoAiMode }
if ($llmEndpointValue -ne "mock") {
    $llmEndpointValue = $llmEndpointValue.Trim().TrimEnd("/")
    $llmUri = $null
    $isAbsoluteHttpUrl = [Uri]::TryCreate($llmEndpointValue, [UriKind]::Absolute, [ref]$llmUri) -and
        $llmUri.Scheme -in @("http", "https") -and -not [string]::IsNullOrWhiteSpace($llmUri.Host)
    if (-not $isAbsoluteHttpUrl) {
        throw "LLM base URL must be an absolute HTTP(S) URL."
    }
}

if ($deviceIdValue -notmatch "^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$") {
    throw "Device ID must be 1-64 characters and use only letters, numbers, dot, underscore, or hyphen."
}
$confidenceNumber = 0.0
if (-not [double]::TryParse($autopilotMinConfidenceValue, [ref] $confidenceNumber) -or
    $confidenceNumber -lt 0 -or $confidenceNumber -gt 1) {
    throw "Autopilot minimum confidence must be between 0 and 1."
}
$allowedTriggerLevels = @("good", "watch", "alert")
$triggerLevels = @($autopilotTriggerLevelsValue.Split(",") |
    ForEach-Object { $_.Trim().ToLowerInvariant() } |
    Where-Object { $_ } | Select-Object -Unique)
if ($triggerLevels.Count -eq 0 -or @($triggerLevels | Where-Object { $_ -notin $allowedTriggerLevels }).Count -gt 0) {
    throw "Autopilot trigger levels must contain one or more of: good, watch, alert."
}
$autopilotTriggerLevelsValue = $triggerLevels -join ","

$corsOrigins = @(
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://$lanAddressValue`:3000"
) | Select-Object -Unique

$serverConfig = @{
    AIOT_APP_ENV = "dev"
    AIOT_DATABASE_URL = "postgresql+psycopg://aiot:aiot@127.0.0.1:5432/aiot"
    AIOT_AUTO_CREATE_TABLES = "true"
    AIOT_BASE_URL = $serverBaseUrl
    AIOT_UPLOADS_DIR = "uploads"
    AIOT_MAX_UPLOAD_BYTES = "10485760"
    AIOT_MQTT_ENABLED = "true"
    AIOT_MQTT_HOST = $mqttHost
    AIOT_MQTT_PORT = "1883"
    AIOT_MQTT_CLIENT_ID = "aiot-gateway"
    AIOT_MQTT_USERNAME = ""
    AIOT_MQTT_PASSWORD = ""
    AIOT_MQTT_RECONNECT_SECONDS = "3"
    NEXT_PUBLIC_API_BASE_URL = $apiBaseUrlValue
    AIOT_DEMO_DEVICE_MODE = $demoDeviceModeValue
    AIOT_DEMO_AI_MODE = $demoAiModeValue
    AIOT_DEMO_DEVICE_ID = $deviceIdValue
    AIOT_DEMO_SCENARIO = $demoScenarioValue
    AIOT_CORS_ORIGINS = $corsOrigins -join ","
    AIOT_LLM_ENDPOINT = $llmEndpointValue
    AIOT_LLM_API_KEY = $llmApiKeyValue
    AIOT_LLM_MODEL = $llmModelValue
    AIOT_LLM_TIMEOUT_SECONDS = "12"
    AIOT_LLM_IMAGE_MAX_AGE_SECONDS = "600"
    AIOT_LLM_RESPONSE_FORMAT = "json_object"
    AIOT_AUTOPILOT_ENABLED = $autopilotEnabledValue
    AIOT_AUTOPILOT_COOLDOWN_SECONDS = "120"
    AIOT_AUTOPILOT_MIN_CONFIDENCE = $autopilotMinConfidenceValue
    AIOT_AUTOPILOT_TRIGGER_LEVELS = $autopilotTriggerLevelsValue
}

$webLines = @(
    "# Generated by tools/configure-local.ps1.",
    "NEXT_PUBLIC_API_BASE_URL=$apiBaseUrlValue"
)

Write-LocalEnvFile -Path $ComposeEnvPath -Lines (New-ComposeEnvLines -Config $serverConfig)
Write-LocalEnvFile -Path $ServerEnvPath -Lines (New-ServerEnvLines -Config $serverConfig)
Write-LocalEnvFile -Path $WebEnvPath -Lines $webLines

Write-Host ""
Write-Host "Done. These files are ignored by Git:" -ForegroundColor Green
Write-Host "  .env"
Write-Host "  server\.env"
Write-Host "  web\.env.local"

if ($Preset -eq "DeviceDemo") {
    Show-FirmwareHint -DeviceId $deviceIdValue -LanAddress $lanAddressValue
}

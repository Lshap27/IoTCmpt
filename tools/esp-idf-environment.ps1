function Get-ObjectPropertyValue {
    param(
        [AllowNull()]
        [object] $InputObject,
        [Parameter(Mandatory = $true)]
        [string] $Name
    )

    if ($null -eq $InputObject) { return $null }
    $property = $InputObject.PSObject.Properties[$Name]
    if ($null -eq $property) { return $null }
    return $property.Value
}

function Read-JsonFile {
    param([string] $Path)

    if ([string]::IsNullOrWhiteSpace($Path) -or -not (Test-Path -LiteralPath $Path)) {
        return $null
    }
    try {
        return Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json
    }
    catch {
        Write-Verbose "Could not read JSON file ${Path}: $($_.Exception.Message)"
        return $null
    }
}

function Expand-IdfSettingPath {
    param([string] $Path)

    if ([string]::IsNullOrWhiteSpace($Path)) { return "" }
    $expanded = [Environment]::ExpandEnvironmentVariables($Path)
    while ($expanded -match '\$\{env:([^}]+)\}') {
        $value = [Environment]::GetEnvironmentVariable($Matches[1])
        if ($null -eq $value) { $value = "" }
        $expanded = $expanded.Replace($Matches[0], $value)
    }
    return $expanded
}

function Get-EspIdfSettings {
    param([Parameter(Mandatory = $true)] [string] $RepoRoot)

    $result = [ordered]@{
        CurrentSetup = ""
        EimIdfJsonPath = ""
        CustomIdfPath = ""
        CustomToolsPath = ""
        CustomPythonPath = ""
        CustomPath = ""
    }
    $settingsPaths = @(
        $(if ($env:APPDATA) { Join-Path $env:APPDATA "Code\User\settings.json" }),
        (Join-Path $RepoRoot ".vscode\settings.json")
    )
    foreach ($settingsPath in $settingsPaths) {
        $settings = Read-JsonFile $settingsPath
        if ($null -eq $settings) { continue }

        $currentSetup = Get-ObjectPropertyValue $settings "idf.currentSetup"
        if (-not [string]::IsNullOrWhiteSpace([string] $currentSetup)) {
            $result.CurrentSetup = [string] $currentSetup
        }
        $eimPath = Get-ObjectPropertyValue $settings "idf.eimIdfJsonPath"
        if (-not [string]::IsNullOrWhiteSpace([string] $eimPath)) {
            $result.EimIdfJsonPath = Expand-IdfSettingPath ([string] $eimPath)
        }
        $extraVars = Get-ObjectPropertyValue $settings "idf.customExtraVars"
        if ($null -ne $extraVars) {
            foreach ($mapping in @(
                @("IDF_PATH", "CustomIdfPath"),
                @("IDF_TOOLS_PATH", "CustomToolsPath"),
                @("IDF_PYTHON_ENV_PATH", "CustomPythonPath"),
                @("PATH", "CustomPath")
            )) {
                $value = Get-ObjectPropertyValue $extraVars $mapping[0]
                if (-not [string]::IsNullOrWhiteSpace([string] $value)) {
                    $result[$mapping[1]] = Expand-IdfSettingPath ([string] $value)
                }
            }
        }
    }
    return [pscustomobject] $result
}

function ConvertTo-EspIdfSetup {
    param(
        [Parameter(Mandatory = $true)] [string] $IdfPath,
        [string] $Id = "",
        [string] $ToolsPath = "",
        [string] $Python = "",
        [string] $ActivationScript = "",
        [string] $Source = "",
        [string] $ExtraPath = ""
    )

    $pythonEnvironment = $Python
    if (-not [string]::IsNullOrWhiteSpace($Python) -and
        [System.IO.Path]::GetFileName($Python) -match "^python(?:\.exe)?$") {
        $scriptsPath = Split-Path -Parent $Python
        $pythonEnvironment = Split-Path -Parent $scriptsPath
    }
    return [pscustomobject] [ordered]@{
        Id = $Id
        IdfPath = $IdfPath
        ToolsPath = $ToolsPath
        PythonPath = $pythonEnvironment
        ActivationScript = $ActivationScript
        Source = $Source
        ExtraPath = $ExtraPath
    }
}

function Test-EspIdfSetupPath {
    param([AllowNull()] [object] $Setup)

    return $null -ne $Setup -and
        -not [string]::IsNullOrWhiteSpace([string] $Setup.IdfPath) -and
        (Test-Path -LiteralPath (Join-Path $Setup.IdfPath "export.ps1"))
}

function Add-LegacyEspIdfEnvironmentHints {
    param([Parameter(Mandatory = $true)] [object] $Setup)

    if ([string]::IsNullOrWhiteSpace([string] $Setup.ToolsPath)) {
        foreach ($root in @(
            $env:IDF_TOOLS_PATH,
            "C:\Espressif",
            $(if ($env:USERPROFILE) { Join-Path $env:USERPROFILE ".espressif" })
        )) {
            if (-not [string]::IsNullOrWhiteSpace([string] $root) -and
                (Test-Path -LiteralPath (Join-Path $root "tools\cmake"))) {
                $Setup.ToolsPath = $root
                break
            }
        }
    }

    if ([string]::IsNullOrWhiteSpace([string] $Setup.PythonPath)) {
        if (-not [string]::IsNullOrWhiteSpace($env:IDF_PYTHON_ENV_PATH)) {
            $Setup.PythonPath = $env:IDF_PYTHON_ENV_PATH
        } else {
            $pythonCandidates = [System.Collections.Generic.List[string]]::new()
            try {
                $versionInfo = Get-EspIdfVersionInfo $Setup.IdfPath
                if (-not [string]::IsNullOrWhiteSpace([string] $Setup.ToolsPath)) {
                    $pythonCandidates.Add((Join-Path $Setup.ToolsPath "tools\python\v$($versionInfo.Version)\venv"))
                }
            } catch {}
            foreach ($pythonRoot in @(
                $(if (-not [string]::IsNullOrWhiteSpace([string] $Setup.ToolsPath)) { Join-Path $Setup.ToolsPath "python_env" }),
                $(if ($env:USERPROFILE) { Join-Path $env:USERPROFILE ".espressif\python_env" })
            )) {
                if ([string]::IsNullOrWhiteSpace([string] $pythonRoot)) { continue }
                Get-ChildItem -LiteralPath $pythonRoot -Directory -Filter "idf5*_env" -ErrorAction SilentlyContinue |
                    ForEach-Object { $pythonCandidates.Add($_.FullName) }
            }
            foreach ($candidate in $pythonCandidates) {
                if (Test-Path -LiteralPath (Join-Path $candidate "Scripts\python.exe")) {
                    $Setup.PythonPath = $candidate
                    break
                }
            }
        }
    }
    return $Setup
}

function Get-EspIdfSetup {
    param(
        [Parameter(Mandatory = $true)] [string] $RepoRoot,
        [string] $EimIdfJsonPath = ""
    )

    $settings = Get-EspIdfSettings $RepoRoot
    $eimPaths = [System.Collections.Generic.List[string]]::new()
    $configuredEimPath = if (-not [string]::IsNullOrWhiteSpace($EimIdfJsonPath)) {
        $EimIdfJsonPath
    } else {
        $settings.EimIdfJsonPath
    }
    $candidateEimPaths = if (-not [string]::IsNullOrWhiteSpace($configuredEimPath)) {
        @($configuredEimPath)
    } else {
        @(
            "C:\Espressif\tools\eim_idf.json",
            $(if ($env:USERPROFILE) { Join-Path $env:USERPROFILE ".espressif\tools\eim_idf.json" })
        )
    }
    foreach ($path in $candidateEimPaths) {
        if ([string]::IsNullOrWhiteSpace([string] $path)) { continue }
        $resolvedPath = Expand-IdfSettingPath ([string] $path)
        if (Test-Path -LiteralPath $resolvedPath -PathType Container) {
            $resolvedPath = Join-Path $resolvedPath "eim_idf.json"
        }
        if ($eimPaths -notcontains $resolvedPath) { $eimPaths.Add($resolvedPath) }
    }

    $eimSetups = [System.Collections.Generic.List[object]]::new()
    $selectedIds = [System.Collections.Generic.List[string]]::new()
    foreach ($eimPath in $eimPaths) {
        $eim = Read-JsonFile $eimPath
        if ($null -eq $eim) { continue }
        $selectedId = [string] (Get-ObjectPropertyValue $eim "idfSelectedId")
        if (-not [string]::IsNullOrWhiteSpace($selectedId) -and $selectedIds -notcontains $selectedId) {
            $selectedIds.Add($selectedId)
        }
        $installed = @(Get-ObjectPropertyValue $eim "idfInstalled")
        foreach ($entry in $installed) {
            $idfPath = [string] (Get-ObjectPropertyValue $entry "path")
            if ([string]::IsNullOrWhiteSpace($idfPath)) { continue }
            $eimSetups.Add((ConvertTo-EspIdfSetup `
                -IdfPath $idfPath `
                -Id ([string] (Get-ObjectPropertyValue $entry "id")) `
                -ToolsPath ([string] (Get-ObjectPropertyValue $entry "idfToolsPath")) `
                -Python ([string] (Get-ObjectPropertyValue $entry "python")) `
                -ActivationScript ([string] (Get-ObjectPropertyValue $entry "activationScript")) `
                -Source "EIM"))
        }
    }

    if (-not [string]::IsNullOrWhiteSpace($env:IDF_PATH)) {
        $matchingEim = $eimSetups | Where-Object { $_.IdfPath -eq $env:IDF_PATH } | Select-Object -First 1
        if (Test-EspIdfSetupPath $matchingEim) { return $matchingEim }
        $environmentSetup = ConvertTo-EspIdfSetup `
            -IdfPath $env:IDF_PATH `
            -ToolsPath $env:IDF_TOOLS_PATH `
            -Python $env:IDF_PYTHON_ENV_PATH `
            -Source "Environment"
        if (Test-EspIdfSetupPath $environmentSetup) {
            return Add-LegacyEspIdfEnvironmentHints $environmentSetup
        }
    }

    if (-not [string]::IsNullOrWhiteSpace($settings.CustomIdfPath)) {
        $customSetup = ConvertTo-EspIdfSetup `
            -IdfPath $settings.CustomIdfPath `
            -ToolsPath $settings.CustomToolsPath `
            -Python $settings.CustomPythonPath `
            -ExtraPath $settings.CustomPath `
            -Source "VS Code customExtraVars"
        if (Test-EspIdfSetupPath $customSetup) { return $customSetup }
    }

    if (-not [string]::IsNullOrWhiteSpace($settings.CurrentSetup)) {
        $selectedSetup = $eimSetups | Where-Object {
            $_.Id -eq $settings.CurrentSetup -or $_.IdfPath -eq $settings.CurrentSetup
        } | Select-Object -First 1
        if (Test-EspIdfSetupPath $selectedSetup) { return $selectedSetup }

        $legacyCurrentSetup = ConvertTo-EspIdfSetup `
            -IdfPath $settings.CurrentSetup -Source "VS Code legacy currentSetup"
        if (Test-EspIdfSetupPath $legacyCurrentSetup) {
            return Add-LegacyEspIdfEnvironmentHints $legacyCurrentSetup
        }
    }

    foreach ($selectedId in $selectedIds) {
        $selectedSetup = $eimSetups | Where-Object { $_.Id -eq $selectedId } | Select-Object -First 1
        if (Test-EspIdfSetupPath $selectedSetup) { return $selectedSetup }
    }
    foreach ($setup in $eimSetups) {
        if (Test-EspIdfSetupPath $setup) { return $setup }
    }

    if ($env:USERPROFILE) {
        $legacyEnvironment = Read-JsonFile (Join-Path $env:USERPROFILE ".espressif\idf-env.json")
        $legacyInstalled = Get-ObjectPropertyValue $legacyEnvironment "idfInstalled"
        if ($null -ne $legacyInstalled) {
            foreach ($entry in $legacyInstalled.PSObject.Properties) {
                $path = [string] (Get-ObjectPropertyValue $entry.Value "path")
                if ([string]::IsNullOrWhiteSpace($path)) { continue }
                $setup = ConvertTo-EspIdfSetup -IdfPath $path -Source "Legacy idf-env.json"
                if (Test-EspIdfSetupPath $setup) {
                    return Add-LegacyEspIdfEnvironmentHints $setup
                }
            }
        }
    }

    $scanCandidates = [System.Collections.Generic.List[string]]::new()
    if (Test-Path -LiteralPath "C:\esp") {
        Get-ChildItem -LiteralPath "C:\esp" -Directory -ErrorAction SilentlyContinue |
            Sort-Object Name -Descending | ForEach-Object {
                $scanCandidates.Add((Join-Path $_.FullName "esp-idf"))
            }
    }
    $scanCandidates.Add("C:\esp\esp-idf")
    foreach ($path in $scanCandidates) {
        $setup = ConvertTo-EspIdfSetup -IdfPath $path -Source "C:\esp scan"
        if (Test-EspIdfSetupPath $setup) {
            return Add-LegacyEspIdfEnvironmentHints $setup
        }
    }

    throw "未找到可用的 ESP-IDF。请先使用 ESP-IDF Installation Manager 安装并选择一个版本。"
}

function Get-EspIdfVersionInfo {
    param([Parameter(Mandatory = $true)] [string] $IdfPath)

    $versionFile = Join-Path $IdfPath "tools\cmake\version.cmake"
    if (-not (Test-Path -LiteralPath $versionFile)) {
        throw "ESP-IDF 版本文件不存在：$versionFile"
    }
    $versionText = Get-Content -LiteralPath $versionFile -Raw
    $majorMatch = [regex]::Match($versionText, "IDF_VERSION_MAJOR\s+(\d+)")
    $minorMatch = [regex]::Match($versionText, "IDF_VERSION_MINOR\s+(\d+)")
    $patchMatch = [regex]::Match($versionText, "IDF_VERSION_PATCH\s+(\d+)")
    if (-not $majorMatch.Success -or -not $minorMatch.Success) {
        throw "无法从 $versionFile 读取 ESP-IDF 版本。"
    }
    $major = [int] $majorMatch.Groups[1].Value
    $minor = [int] $minorMatch.Groups[1].Value
    $patch = if ($patchMatch.Success) { [int] $patchMatch.Groups[1].Value } else { 0 }
    return [pscustomobject] [ordered]@{
        Version = "$major.$minor.$patch"
        Major = $major
        Minor = $minor
        Patch = $patch
        Compatible = $major -eq 5 -and $minor -ge 1
    }
}

function Enable-EspIdfSetup {
    param([Parameter(Mandatory = $true)] [object] $Setup)

    Remove-Item Env:MSYSTEM -ErrorAction SilentlyContinue
    if (-not [string]::IsNullOrWhiteSpace([string] $Setup.ActivationScript) -and
        (Test-Path -LiteralPath $Setup.ActivationScript)) {
        # EIM-generated profiles are intended for interactive shells and may
        # access optional command properties without null checks. Isolate them
        # from the caller's StrictMode while keeping their environment changes.
        Set-StrictMode -Off
        . $Setup.ActivationScript
        return
    }

    $env:IDF_PATH = $Setup.IdfPath
    if (-not [string]::IsNullOrWhiteSpace([string] $Setup.ToolsPath)) {
        $env:IDF_TOOLS_PATH = $Setup.ToolsPath
    }
    if (-not [string]::IsNullOrWhiteSpace([string] $Setup.PythonPath)) {
        $env:IDF_PYTHON_ENV_PATH = $Setup.PythonPath
    }
    if (-not [string]::IsNullOrWhiteSpace([string] $Setup.ToolsPath) -and
        -not (Test-Path -LiteralPath (Join-Path $Setup.ToolsPath "espidf.constraints.v5.5.txt"))) {
        $env:IDF_PYTHON_CHECK_CONSTRAINTS = "0"
    }
    if (-not [string]::IsNullOrWhiteSpace([string] $Setup.ExtraPath)) {
        $env:PATH = "$($Setup.ExtraPath);$env:PATH"
    }
    . (Join-Path $Setup.IdfPath "export.ps1")
}

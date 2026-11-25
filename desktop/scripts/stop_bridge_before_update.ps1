<#
.SYNOPSIS
Stops the ce-underscore app-harness bridge before an update replaces files and
checks bridge.json against the binary that is installed afterwards.

.DESCRIPTION
Invoked by the NSIS installer hooks (desktop/scripts/nsis-hooks.nsh) and usable
by packaging steps on Windows. "No bridge" is success, because a pip-only cecli
install has no desktop app and nothing to stop. A version skew exits 3 with a
message that names both versions.

.PARAMETER Action
stop, verify, path, uninstall, install, or all. `install` adds the opt-in PATH
entry and verifies; `all` stops and verifies.

.PARAMETER InstallDir
The NSIS install directory. Defaults to the parent of `_up_\scripts`.

.PARAMETER Binary
Explicit ce-underscore.exe path. Defaults to <InstallDir>\ce-underscore.exe or
the copy on PATH.

.PARAMETER BridgeFile
Override for bridge.json (also CECLI_BRIDGE_FILE).
#>

[CmdletBinding()]
param(
    [ValidateSet('stop', 'verify', 'path', 'uninstall', 'install', 'all')]
    [string]$Action = 'all',

    [string]$InstallDir = '',

    [string]$Binary = '',

    [string]$BridgeFile = ''
)

$ErrorActionPreference = 'Stop'

function Stop-BridgeBeforeUpdate {
    $exe = Resolve-BinaryPath
    if (-not $exe) {
        Write-Host 'ce-underscore is not installed; no bridge to stop'
        return 0
    }

    Write-Host "stopping the app-harness bridge via $exe"
    & $exe --stop-bridge *> $null
    $status = $LASTEXITCODE
    if ($status -eq 0) {
        return 0
    }

    $file = Get-BridgeFile
    if (-not (Test-Path -LiteralPath $file)) {
        Write-Host "ce-underscore --stop-bridge exited $status; no $file, treating as 'no bridge'"
        return 0
    }

    [Console]::Error.WriteLine("error: failed to stop the app-harness bridge (exit $status)")
    return $status
}

function Test-BridgeVersion {
    $file = Get-BridgeFile
    if (-not (Test-Path -LiteralPath $file)) {
        Write-Host "no $file; nothing to verify"
        return 0
    }

    try {
        $state = Get-Content -Raw -LiteralPath $file | ConvertFrom-Json
    }
    catch {
        Write-Warning "$file is not valid JSON; skipping the skew check"
        return 0
    }

    $stored = [string]$state.version
    if (-not $stored) {
        Write-Warning "$file has no version; skipping the skew check"
        return 0
    }

    $exe = Resolve-BinaryPath
    if (-not $exe) {
        [Console]::Error.WriteLine('error: cannot verify the bridge version: ce-underscore is not installed')
        return 4
    }

    $raw = (& $exe --version) -join ' '
    $match = [regex]::Match($raw, '\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.]+)?')
    if (-not $match.Success) {
        [Console]::Error.WriteLine("error: $exe --version did not report a version")
        return 4
    }

    $installed = $match.Value
    if ($installed -ne $stored) {
        [Console]::Error.WriteLine("version skew: $file reports $stored but $exe reports $installed")
        [Console]::Error.WriteLine('The old bridge was not stopped before its files were replaced. Run:')
        [Console]::Error.WriteLine('  ce-underscore --stop-bridge')
        [Console]::Error.WriteLine('then start it again with:')
        [Console]::Error.WriteLine('  ce-underscore --ensure-bridge')
        return 3
    }

    Write-Host "bridge version $installed matches $exe"
    return 0
}

function Add-PathEntry {
    if ($env:CECLI_ADD_TO_PATH -ne '1') {
        Write-Host 'skipping the PATH entry; set CECLI_ADD_TO_PATH=1 to opt in'
        return 0
    }

    $dir = (Resolve-InstallDir).TrimEnd('\')
    $current = [Environment]::GetEnvironmentVariable('Path', 'User')
    $parts = @($current -split ';' | Where-Object { $_ })
    if ($parts -contains $dir) {
        Write-Host "$dir is already on the user PATH"
        return 0
    }

    $updated = if ($current) { "$current;$dir" } else { $dir }
    [Environment]::SetEnvironmentVariable('Path', $updated, 'User')
    Write-Host "added $dir to the user PATH"
    return 0
}

function Remove-PathEntry {
    $dir = (Resolve-InstallDir).TrimEnd('\')
    $current = [Environment]::GetEnvironmentVariable('Path', 'User')
    if (-not $current) {
        return 0
    }

    $parts = @($current -split ';' | Where-Object { $_ -and $_ -ne $dir })
    [Environment]::SetEnvironmentVariable('Path', ($parts -join ';'), 'User')
    Write-Host "removed $dir from the user PATH"
    return 0
}

function Resolve-InstallDir {
    if ($InstallDir) {
        return $InstallDir
    }

    $script_dir = Split-Path -Parent $PSCommandPath
    $up_dir = Split-Path -Parent $script_dir
    return (Split-Path -Parent $up_dir)
}

function Resolve-BinaryPath {
    if ($Binary) {
        return $Binary
    }

    $candidates = @()
    if ($InstallDir) {
        $candidates += (Join-Path $InstallDir 'ce-underscore.exe')
    }
    $candidates += 'ce-underscore.exe'

    foreach ($candidate in $candidates) {
        $command = Get-Command $candidate -ErrorAction SilentlyContinue
        if ($command) {
            return $command.Source
        }
    }

    return $null
}

function Get-BridgeFile {
    if ($BridgeFile) {
        return $BridgeFile
    }
    if ($env:CECLI_BRIDGE_FILE) {
        return $env:CECLI_BRIDGE_FILE
    }
    if ($env:LOCALAPPDATA) {
        return (Join-Path $env:LOCALAPPDATA 'cecli\bridge.json')
    }

    return (Join-Path $HOME '.cache/cecli/bridge.json')
}

$result = switch ($Action) {
    'stop' { Stop-BridgeBeforeUpdate }
    'verify' { Test-BridgeVersion }
    'path' { Add-PathEntry }
    'uninstall' {
        $null = Stop-BridgeBeforeUpdate
        Remove-PathEntry
    }
    'install' {
        $code = Add-PathEntry
        if ($code -eq 0) { $code = Test-BridgeVersion }
        $code
    }
    'all' {
        $code = Stop-BridgeBeforeUpdate
        if ($code -eq 0) { $code = Test-BridgeVersion }
        $code
    }
}

exit $result

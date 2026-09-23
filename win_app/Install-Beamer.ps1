$ErrorActionPreference = 'Stop'

# Over SSH there is nobody to press Enter and no desktop to open a window on: Read-Host fails on
# the null stdin, and a Start-Process lands Beamer in session 0, where it is an invisible,
# tray-less receiver that also holds the SSH pipe open so the install never returns.
$Interactive = [Environment]::UserInteractive -and -not $env:SSH_CLIENT

trap {
    Write-Host $_ -ForegroundColor Red
    if ($Interactive) { Read-Host 'Press Enter to close' }
    break
}

# The app was called OpenKB until 19-08-2026, then Beamy until 10-09-2026. Only
# the display name moved each time until now: this rename also moves the data
# directory, from %LOCALAPPDATA%\OpenKB to %LOCALAPPDATA%\Beamer. app_config.py's
# migrate_legacy_config copies the OpenKB-era config.json across on first run
# rather than moving it, so the old directory and its config.json are never
# touched here.
$LegacyOpenKBDir = Join-Path $env:LOCALAPPDATA 'OpenKB'
$InstallDir = Join-Path $env:LOCALAPPDATA 'Beamer'
$ExeSource = Join-Path $PSScriptRoot 'dist\Beamer.exe'
$ExeDestination = Join-Path $InstallDir 'Beamer.exe'

# Everything the OpenKB name left behind, so the rename does not leave a second
# Start Menu entry, a second logon task, a stale firewall rule for an exe that
# no longer exists, or an OpenKB.exe that still runs alongside this one.
$LegacyName = 'OpenKB'
Get-Process $LegacyName -ErrorAction SilentlyContinue | Stop-Process -Force
# Stop-Process returns before the exe is released, and deleting it straight away then fails silently.
Get-Process $LegacyName -ErrorAction SilentlyContinue | Wait-Process -Timeout 10 -ErrorAction SilentlyContinue
Unregister-ScheduledTask -TaskName $LegacyName -Confirm:$false -ErrorAction SilentlyContinue
Remove-Item -Path (Join-Path $LegacyOpenKBDir "$LegacyName.exe") -Force -ErrorAction SilentlyContinue
Remove-Item -Path (Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\$LegacyName.lnk") -Force -ErrorAction SilentlyContinue
Remove-Item -Path (Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Startup\$LegacyName.lnk") -Force -ErrorAction SilentlyContinue
Remove-Item -Path (Join-Path ([Environment]::GetFolderPath('Desktop')) "$LegacyName.lnk") -Force -ErrorAction SilentlyContinue
# A rule named plain OpenKB also survived on the rig until 15-09-2026: TCP 51820 for any program on
# every profile, Public included.
Get-NetFirewallRule -DisplayName "$LegacyName Receiver (TCP-In)", $LegacyName -ErrorAction SilentlyContinue | Remove-NetFirewallRule -ErrorAction SilentlyContinue

# Everything the Beamy name left behind. Its data directory was never its own --
# it shared OpenKB's, so Beamy.exe there is removed but config.json stays; it is
# still what migrate_legacy_config reads from.
Get-Process 'Beamy' -ErrorAction SilentlyContinue | Stop-Process -Force
Get-Process 'Beamy' -ErrorAction SilentlyContinue | Wait-Process -Timeout 10 -ErrorAction SilentlyContinue
Remove-Item -Path (Join-Path $LegacyOpenKBDir 'Beamy.exe') -Force -ErrorAction SilentlyContinue
Remove-Item -Path (Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\Beamy.lnk') -Force -ErrorAction SilentlyContinue
Remove-Item -Path (Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\Startup\Beamy.lnk') -Force -ErrorAction SilentlyContinue
Remove-Item -Path (Join-Path ([Environment]::GetFolderPath('Desktop')) 'Beamy.lnk') -Force -ErrorAction SilentlyContinue
Remove-ItemProperty -Path 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run' -Name 'Beamy' -ErrorAction SilentlyContinue

# Beamer.exe now carries a requireAdministrator manifest (build.spec uac_admin=True) so
# SendInput can reach elevated windows, e.g. an admin terminal, which UIPI otherwise
# silently discards input for. The firewall rules below need this session elevated too.
$IsElevated = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

& "$PSScriptRoot\build_win_app.ps1"
if (-not (Test-Path $ExeSource)) { throw 'The Windows build did not produce Beamer.exe' }

New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
Get-Process 'Beamer' -ErrorAction SilentlyContinue | Stop-Process -Force
Get-Process 'Beamer' -ErrorAction SilentlyContinue | Wait-Process -Timeout 10 -ErrorAction SilentlyContinue
# The exe can stay locked for a moment after the process has gone (23-09-2026: the copy failed
# with "being used by another process" straight after Wait-Process returned, and worked on a rerun).
for ($attempt = 1; ; $attempt++) {
    try {
        Copy-Item -Path $ExeSource -Destination $ExeDestination -Force -ErrorAction Stop
        break
    } catch [System.IO.IOException] {
        if ($attempt -ge 10) { throw }
        Start-Sleep -Milliseconds 500
    }
}

$Shell = New-Object -ComObject WScript.Shell
$StartMenuPath = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\Beamer.lnk'
$StartMenuShortcut = $Shell.CreateShortcut($StartMenuPath)
$StartMenuShortcut.TargetPath = $ExeDestination
$StartMenuShortcut.WorkingDirectory = $InstallDir
$StartMenuShortcut.Description = 'Beamer Windows Receiver'
$StartMenuShortcut.Save()

# No installer writes a desktop shortcut; delete any this or an older install left.
Remove-Item -Path (Join-Path ([Environment]::GetFolderPath('Desktop')) 'Beamer.lnk') -Force -ErrorAction SilentlyContinue

# Startup used to be a plain shortcut in the Startup folder. Explorer launches a
# requireAdministrator exe from there with a UAC prompt on every logon instead of
# starting silently, so startup is now a Scheduled Task (RunLevel Highest) instead.
# Remove any shortcut left behind by a previous install so there isn't a second starter.
$StartupPath = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\Startup\Beamer.lnk'
Remove-Item -Path $StartupPath -Force -ErrorAction SilentlyContinue

# Defensively remove a legacy Run-key entry too, in case an older install used one instead.
Remove-ItemProperty -Path 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run' -Name 'Beamer' -ErrorAction SilentlyContinue

if ($IsElevated) {
    # Start at logon belongs to the app: the switch on its Overview page writes and removes the
    # Beamer task, and the installer never does, on install or reinstall. A Beamy task is removed,
    # since it starts an exe that no longer exists.
    Unregister-ScheduledTask -TaskName 'Beamy' -Confirm:$false -ErrorAction SilentlyContinue

    try {
        Get-NetFirewallRule -DisplayName 'Beamy Receiver (TCP-In)' -ErrorAction SilentlyContinue | Remove-NetFirewallRule
        Get-NetFirewallRule -DisplayName 'Beamy Pairing (UDP-In)' -ErrorAction SilentlyContinue | Remove-NetFirewallRule
        Get-NetFirewallRule -DisplayName 'Beamer Receiver (TCP-In)' -ErrorAction SilentlyContinue | Remove-NetFirewallRule
        # 24820 and 24821, not the old 51820/51821: those sat inside the 49152-65535 range
        # Windows hands out for itself, and a WinNAT reservation landing on the receiver's port
        # left the PC unable to listen while its outward link carried on working.
        New-NetFirewallRule -DisplayName 'Beamer Receiver (TCP-In)' -Direction Inbound -Protocol TCP -LocalPort 24820 -Action Allow -Profile Private -Program $ExeDestination | Out-Null
        # The pairing beacon answers the Mac on UDP 24821; without this the Mac never sees the PC.
        Get-NetFirewallRule -DisplayName 'Beamer Pairing (UDP-In)' -ErrorAction SilentlyContinue | Remove-NetFirewallRule
        New-NetFirewallRule -DisplayName 'Beamer Pairing (UDP-In)' -Direction Inbound -Protocol UDP -LocalPort 24821 -Action Allow -Profile Private -Program $ExeDestination | Out-Null
        Write-Host 'Private-network firewall rules installed (TCP 24820 receiver, UDP 24821 pairing).' -ForegroundColor Green
    } catch {
        Write-Host "Could not install the firewall rule: $_" -ForegroundColor Yellow
    }
} else {
    Write-Host 'This session is not elevated, so the firewall rules were not configured. Re-run this installer from an admin PowerShell.' -ForegroundColor Yellow
}

# Beamer.exe is manifested requireAdministrator, so launching it from a non-elevated
# session needs an explicit elevation request; from an already-elevated session this
# just runs it without a further prompt.
if ($Interactive) {
    Start-Process -FilePath $ExeDestination -WorkingDirectory $InstallDir -Verb RunAs
    Write-Host "Beamer installed at $ExeDestination" -ForegroundColor Green
    Read-Host 'Press Enter to close'
} else {
    Write-Host "Beamer installed at $ExeDestination and not started; start it at the PC." -ForegroundColor Green
}

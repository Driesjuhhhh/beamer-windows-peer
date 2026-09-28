# Builds dist\Beamer.exe. With -Release it also builds Beamer-Setup-<version>.exe with Inno Setup
# into ..\..\docs\beamer-releases\<version>\, from a clean commit.
param([switch]$Release)

$ErrorActionPreference = 'Stop'

# Windows PowerShell 5.1 turns a native command's stderr into an error record, and with the
# preference above a pip upgrade notice or unittest's own progress -- both ordinary stderr --
# aborts the build with NativeCommandError. Merging with 2>&1 is not enough; the preference has
# to be relaxed for the call itself, which this does inside a function so it stays local. Every
# call checks $LASTEXITCODE afterwards, which survives the function, so nothing is lost.
function Invoke-Native {
    param([Parameter(Mandatory = $true)][scriptblock]$Command)
    $ErrorActionPreference = 'Continue'
    & $Command
}

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
if (-not $ScriptDir) { $ScriptDir = Get-Location }
Set-Location $ScriptDir
$ProjectDir = Split-Path -Parent $ScriptDir

if ($Release) {
    # docs\ is not part of the build and changes independently of it; anything else uncommitted
    # would ship code that no commit records.
    $Dirty = git -C $ProjectDir status --porcelain -- . ':(exclude)docs'
    if ($Dirty) { throw 'Uncommitted changes outside docs\ - commit them so the release matches a commit' }
    $Iscc = Join-Path $env:LOCALAPPDATA 'Programs\Inno Setup 6\ISCC.exe'
    if (-not (Test-Path $Iscc)) { throw "Inno Setup 6 is not installed at $Iscc" }
}

$Python = Get-Command python -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source
if (-not $Python) { throw 'Python was not found on PATH' }

if (-not (Test-Path .venv\Scripts\python.exe)) {
    Invoke-Native { & $Python -m venv .venv }
    if ($LASTEXITCODE -ne 0) { throw 'Virtual environment creation failed' }
}

Invoke-Native { & .\.venv\Scripts\python.exe -m pip install -r requirements-win.txt }
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed' }

Invoke-Native { & .\.venv\Scripts\python.exe -m unittest discover -s tests -v }
if ($LASTEXITCODE -ne 0) { throw 'Windows tests failed' }

Invoke-Native { & .\.venv\Scripts\python.exe -m PyInstaller --clean --noconfirm --distpath dist --workpath build build.spec }
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller failed' }

$Output = Join-Path $ScriptDir 'dist\Beamer.exe'
if (-not (Test-Path $Output)) { throw 'PyInstaller did not create Beamer.exe' }
Write-Output "Built $Output"

if ($Release) {
    $Version = (Get-Content (Join-Path $ProjectDir 'VERSION') -Raw).Trim()
    $ReleaseDir = [IO.Path]::GetFullPath((Join-Path $ProjectDir "..\docs\beamer-releases\$Version"))
    & $Iscc "/O$ReleaseDir" Beamer-Setup.iss
    if ($LASTEXITCODE -ne 0) { throw 'Inno Setup failed' }
    $Commit = git -C $ProjectDir rev-parse --short HEAD
    Write-Output "Released $(Join-Path $ReleaseDir "Beamer-Setup-$Version.exe") from $Commit"
}

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$payloadDir = Join-Path $PSScriptRoot 'build\installer-payload'
$buildDir = Join-Path $PSScriptRoot 'build\msi'
$outputDir = Join-Path $PSScriptRoot 'dist'
New-Item -ItemType Directory -Path $payloadDir,$buildDir -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $outputDir 'Beamer.exe'),(Join-Path $outputDir 'Pair-Beamer.exe'),(Join-Path $PSScriptRoot 'INSTALLATIE.txt') -Destination $payloadDir
Copy-Item -LiteralPath (Join-Path $repoRoot 'LICENSE') -Destination $payloadDir
$hostScript = @'
@echo off
cd /d "%~dp0"
echo Close Beamer on both PCs before pairing.
echo This PC is the LEFT PC. The other PC is to its right.
Pair-Beamer.exe host --edge right
pause
'@
$joinScript = @'
@echo off
cd /d "%~dp0"
echo Close Beamer on both PCs before pairing.
echo This PC is the RIGHT PC. The other PC is to its left.
set /p "BEAMER_PEER_ADDRESS=IP address of the left PC: "
if not defined BEAMER_PEER_ADDRESS exit /b 1
Pair-Beamer.exe join --address "%BEAMER_PEER_ADDRESS%" --edge left
pause
'@
Set-Content -LiteralPath (Join-Path $payloadDir 'Pair-Left-PC.cmd') -Value $hostScript -Encoding ascii
Set-Content -LiteralPath (Join-Path $payloadDir 'Pair-Right-PC.cmd') -Value $joinScript -Encoding ascii
$files = @(
    @('BeamerExe','Beamer.exe','AppComponent'),
    @('PairExe','Pair-Beamer.exe','PairComponent'),
    @('Guide','INSTALLATIE.txt','GuideComponent'),
    @('License','LICENSE','LicenseComponent'),
    @('HostCmd','Pair-Left-PC.cmd','HostComponent'),
    @('JoinCmd','Pair-Right-PC.cmd','JoinComponent')
)
$ddf = @('.OPTION EXPLICIT','.Set CabinetNameTemplate=payload.cab',".Set DiskDirectoryTemplate=$buildDir",'.Set MaxDiskSize=0','.Set MaxCabinetSize=0','.Set FolderSizeThreshold=2147483647','.Set CompressionType=MSZIP','.Set Cabinet=on','.Set Compress=on')
foreach ($file in $files) { $ddf += '"' + (Join-Path $payloadDir $file[1]) + '" ' + $file[0] }
$ddfPath = Join-Path $buildDir 'payload.ddf'
Set-Content -LiteralPath $ddfPath -Value $ddf -Encoding ascii
& "$env:SystemRoot\System32\makecab.exe" /F $ddfPath
if ($LASTEXITCODE -ne 0) { throw 'Cabinet creation failed' }
$msiPath = Join-Path $outputDir 'Beamer-Windows-Peer-UI-1.4.5.msi'
if (Test-Path -LiteralPath $msiPath) { throw 'UI installer already exists; preserve it before rebuilding' }
$installer = New-Object -ComObject WindowsInstaller.Installer
$database = $installer.OpenDatabase($msiPath, 3)
function Sql([string]$query) {
    try { $view = $database.OpenView($query) } catch { throw "SQL failed: $query; $($installer.LastErrorRecord().FormatText())" }
    $view.Execute()
    $view.Close()
}
function Insert([string]$table, [string[]]$columns, [object[]]$values) {
    $quoted = $columns | ForEach-Object { '`' + $_ + '`' }
    $marks = $values | ForEach-Object { '?' }
    $query = 'INSERT INTO `' + $table + '` (' + ($quoted -join ',') + ') VALUES (' + ($marks -join ',') + ')'
    $record = $installer.CreateRecord($values.Count)
    for ($index = 0; $index -lt $values.Count; $index++) {
        if ($null -eq $values[$index]) { continue }
        if ($values[$index] -is [int]) { $record.IntegerData($index+1) = $values[$index] }
        else { $record.StringData($index+1) = [string]$values[$index] }
    }
    $view = $database.OpenView($query)
    $view.Execute($record)
    $view.Close()
}
Sql 'CREATE TABLE `Property` (`Property` CHAR(72) NOT NULL, `Value` CHAR(0) NOT NULL LOCALIZABLE PRIMARY KEY `Property`)'
Sql 'CREATE TABLE `Directory` (`Directory` CHAR(72) NOT NULL, `Directory_Parent` CHAR(72), `DefaultDir` CHAR(255) NOT NULL LOCALIZABLE PRIMARY KEY `Directory`)'
Sql 'CREATE TABLE `Component` (`Component` CHAR(72) NOT NULL, `ComponentId` CHAR(38), `Directory_` CHAR(72) NOT NULL, `Attributes` SHORT NOT NULL, `Condition` CHAR(255), `KeyPath` CHAR(72) PRIMARY KEY `Component`)'
Sql 'CREATE TABLE `Feature` (`Feature` CHAR(38) NOT NULL, `Feature_Parent` CHAR(38), `Title` CHAR(64) LOCALIZABLE, `Description` CHAR(255) LOCALIZABLE, `Display` SHORT, `Level` SHORT NOT NULL, `Directory_` CHAR(72), `Attributes` SHORT NOT NULL PRIMARY KEY `Feature`)'
Sql 'CREATE TABLE `FeatureComponents` (`Feature_` CHAR(38) NOT NULL, `Component_` CHAR(72) NOT NULL PRIMARY KEY `Feature_`, `Component_`)'
Sql 'CREATE TABLE `File` (`File` CHAR(72) NOT NULL, `Component_` CHAR(72) NOT NULL, `FileName` CHAR(255) NOT NULL LOCALIZABLE, `FileSize` LONG NOT NULL, `Version` CHAR(72), `Language` CHAR(20), `Attributes` SHORT, `Sequence` SHORT NOT NULL PRIMARY KEY `File`)'
Sql 'CREATE TABLE `Media` (`DiskId` SHORT NOT NULL, `LastSequence` LONG NOT NULL, `DiskPrompt` CHAR(64) LOCALIZABLE, `Cabinet` CHAR(255), `VolumeLabel` CHAR(32), `Source` CHAR(72) PRIMARY KEY `DiskId`)'
Sql 'CREATE TABLE `Shortcut` (`Shortcut` CHAR(72) NOT NULL, `Directory_` CHAR(72) NOT NULL, `Name` CHAR(128) NOT NULL LOCALIZABLE, `Component_` CHAR(72) NOT NULL, `Target` CHAR(255) NOT NULL, `Arguments` CHAR(255), `Description` CHAR(255) LOCALIZABLE, `Hotkey` SHORT, `Icon_` CHAR(72), `IconIndex` SHORT, `ShowCmd` SHORT, `WkDir` CHAR(72) PRIMARY KEY `Shortcut`)'
Sql 'CREATE TABLE `RemoveFile` (`FileKey` CHAR(72) NOT NULL, `Component_` CHAR(72) NOT NULL, `FileName` CHAR(255) LOCALIZABLE, `DirProperty` CHAR(72) NOT NULL, `InstallMode` SHORT NOT NULL PRIMARY KEY `FileKey`)'
Sql 'CREATE TABLE `Upgrade` (`UpgradeCode` CHAR(38) NOT NULL, `VersionMin` CHAR(20), `VersionMax` CHAR(20), `Language` CHAR(255), `Attributes` LONG NOT NULL, `Remove` CHAR(255), `ActionProperty` CHAR(72) NOT NULL PRIMARY KEY `UpgradeCode`, `VersionMin`, `VersionMax`, `Language`, `Attributes`)'
foreach ($table in @('InstallExecuteSequence','InstallUISequence')) {
    Sql ('CREATE TABLE `' + $table + '` (`Action` CHAR(72) NOT NULL, `Condition` CHAR(255), `Sequence` SHORT NOT NULL PRIMARY KEY `Action`)')
}
$productCode = '{920A06D7-D53D-446F-BD14-D2FE5B3BB3BD}'
$shortcutIndex = 0
foreach ($entry in @(
    @('ProductCode',$productCode),@('ProductName','Beamer Windows Peer (experimental)'),
    @('ProductVersion','1.4.5'),@('ProductLanguage','1033'),
    @('Manufacturer','Beamer local development build'),
    @('UpgradeCode','{E97759E2-AB73-44CF-B1C1-852DE0B37BD7}'),
    @('INSTALLLEVEL','1'),@('ARPCOMMENTS','Experimental Windows-to-Windows build. Pairing helper and guide included.'),
    @('ARPNOMODIFY','1'),@('MSIFASTINSTALL','7'),@('SecureCustomProperties','OLDPRODUCTS')
)) { Insert 'Property' @('Property','Value') $entry }
Insert 'Upgrade' @('UpgradeCode','VersionMax','Attributes','Remove','ActionProperty') @('{E97759E2-AB73-44CF-B1C1-852DE0B37BD7}','1.4.5',0,'ALL','OLDPRODUCTS')
foreach ($entry in @(
    @('TARGETDIR',$null,'SourceDir'),@('LocalAppDataFolder','TARGETDIR','.'),
    @('INSTALLDIR','LocalAppDataFolder','BEAMER~1|Beamer Windows Peer'),
    @('ProgramMenuFolder','TARGETDIR','.'),@('BeamerPeerMenu','ProgramMenuFolder','BEAMER~1|Beamer Windows Peer')
)) { Insert 'Directory' @('Directory','Directory_Parent','DefaultDir') $entry }
Insert 'Feature' @('Feature','Title','Description','Display','Level','Directory_','Attributes') @('Complete','Beamer Windows Peer','GUI, pairing helper and guide',1,1,'INSTALLDIR',0)
$sequence = 0
foreach ($file in $files) {
    $sequence++
    Insert 'Component' @('Component','ComponentId','Directory_','Attributes','KeyPath') @($file[2],('{' + [guid]::NewGuid().ToString().ToUpper() + '}'),'INSTALLDIR',256,$file[0])
    Insert 'FeatureComponents' @('Feature_','Component_') @('Complete',$file[2])
    $shortName = 'FILE' + $sequence + '.DAT|' + $file[1]
    $size = [int](Get-Item -LiteralPath (Join-Path $payloadDir $file[1])).Length
    Insert 'File' @('File','Component_','FileName','FileSize','Attributes','Sequence') @($file[0],$file[2],$shortName,$size,0,$sequence)
}
Insert 'Media' @('DiskId','LastSequence','Cabinet') @(1,$sequence,'#payload.cab')
foreach ($entry in @(
    @('AppShortcut','Beamer Windows Peer','AppComponent','Beamer.exe'),
    @('HostShortcut','Pair left PC','HostComponent','Pair-Left-PC.cmd'),
    @('JoinShortcut','Pair right PC','JoinComponent','Pair-Right-PC.cmd'),
    @('GuideShortcut','Setup guide','GuideComponent','INSTALLATIE.txt')
)) {
    $shortcutIndex++
    Insert 'Shortcut' @('Shortcut','Directory_','Name','Component_','Target','ShowCmd','WkDir') @($entry[0],'BeamerPeerMenu',('LINK' + $shortcutIndex + '|' + $entry[1]),$entry[2],('[INSTALLDIR]' + $entry[3]),1,'INSTALLDIR')
}
Insert 'RemoveFile' @('FileKey','Component_','DirProperty','InstallMode') @('RemoveMenu','AppComponent','BeamerPeerMenu',2)
Insert 'RemoveFile' @('FileKey','Component_','DirProperty','InstallMode') @('RemoveAppDirectory','AppComponent','INSTALLDIR',2)
$actions = @(
    @('FindRelatedProducts',25),@('CostInitialize',800),@('FileCost',900),@('CostFinalize',1000),
    @('InstallValidate',1400),@('RemoveExistingProducts',1450),@('InstallInitialize',1500),@('ProcessComponents',1600),
    @('UnpublishFeatures',1800),@('RemoveShortcuts',3200),@('RemoveFiles',3500),
    @('InstallFiles',4000),@('CreateShortcuts',4500),@('RegisterUser',6000),
    @('RegisterProduct',6100),@('PublishFeatures',6300),@('PublishProduct',6400),@('InstallFinalize',6600)
)
foreach ($action in $actions) { Insert 'InstallExecuteSequence' @('Action','Sequence') $action }
foreach ($action in @(@('CostInitialize',800),@('FileCost',900),@('CostFinalize',1000),@('ExecuteAction',1300))) {
    Insert 'InstallUISequence' @('Action','Sequence') $action
}
$record = $installer.CreateRecord(2)
$record.StringData(1) = 'payload.cab'
$record.SetStream(2,(Join-Path $buildDir 'payload.cab'))
$view = $database.OpenView('INSERT INTO `_Streams` (`Name`,`Data`) VALUES (?,?)')
$view.Execute($record)
$view.Close()
$summary = $database.SummaryInformation(20)
$summary.Property(2) = 'Beamer Windows Peer Installer'
$summary.Property(3) = 'Experimental Windows-to-Windows Beamer build'
$summary.Property(7) = 'x64;1033'
$summary.Property(9) = '{' + [guid]::NewGuid().ToString().ToUpper() + '}'
$summary.Property(14) = 200
$summary.Property(15) = 2
$summary.Persist()
$database.Commit()
Write-Output "Created $msiPath"


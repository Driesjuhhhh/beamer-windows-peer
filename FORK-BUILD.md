# Windows Peer fork build

The `windows-peer` branch starts at upstream `e5339fa82d4ba5c662fda920f441b2e70d6c9199` (Beamer 1.4.2). Version 1.4.5 identifies this experimental fork build. The user's merge of upstream 1.4.3 (`4feead2`) is preserved, including the CPace pairing/security update and PyNaCl dependency. The Windows pairing UI/helper consume its `(token, authenticated_name)` result.

Added features: Windows peer configuration, Windows receiver focus roles, Windows modifier mapping, in-app **Pair a Windows PC**, command-line pairing, and Windows pairing tests. The default peer remains Mac. Mac sources and shared protocol implementations are unchanged.

Version 1.4.5 adds [Advanced Crossing](ADVANCED-CROSSING.md): per-monitor identities, authenticated screen inventory/identify/layout controls, a drag-and-snap editor, saved layouts with reversed ownership on the peer and targeted arrivals through each touching screen pair. Windows `receiver.py` has opt-in extension handling; Mac sources and the shared wire-version definitions remain unchanged. Both Windows PCs need this version for the advanced editor.

The package excludes third-party ICU DLLs accidentally collected from the build machine's PATH: those DLLs caused QtCore to fail with Windows error 127. Qt uses the Windows system ICU library.

## Build on Windows

Use a supported 64-bit Python and Windows 10/11. From the repository root, run PowerShell:

```powershell
Set-Location win_app
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-win.txt
.\.venv\Scripts\python.exe -m PyInstaller --clean --noconfirm --distpath dist --workpath build-gui build.spec
$env:BEAMER_PAIR_HELPER = '1'
try {
    .\.venv\Scripts\python.exe -m PyInstaller --clean --noconfirm --distpath dist --workpath build-pair build.spec
} finally {
    Remove-Item Env:BEAMER_PAIR_HELPER
}
.\build_peer_installer.ps1
```

The builder expects `dist/Beamer.exe` and `dist/Pair-Beamer.exe` and creates `dist/Beamer-Windows-Peer-UI-1.4.5.msi`. It uses Windows `makecab` and Windows Installer COM. Preserve an existing MSI before rebuilding. Building does not install the application.

The MSI installs per user into `%LOCALAPPDATA%\Beamer Windows Peer`, with a separate product identity from official Beamer. Pairing preferences use the existing Beamer configuration directory. The MSI includes the app, pairing helper, optional left/right pairing shortcuts, installation guide and GPL license.

## Validation and limits

For the combined 1.4.5 revision, 181 relevant tests passed: sender (40), receiver (55), CPace (56), Windows pairing UI (7), Windows peer configuration/socket integration (6), display geometry (9) and the advanced editor (8). Qt was rendered offscreen and the new pairing button/dialog checked. Packaged Qt DLLs loaded through the Windows loader after the ICU packaging correction. The generated MSI cabinet was unpacked and all six payload hashes matched its source files; MSI costing and directory resolution succeeded.

The earlier full suite had 567 passes, two skips and one pre-existing edge-glow hover test failure, reproduced on upstream. A later full-suite run did not complete in the restricted environment. Actual MSI installation, full frozen-app startup, two physical Windows PCs and a Mac build remain unverified. Windows peer support is experimental.

For a packaged headless Qt check, set `BEAMER_PACKAGE_CHECK=1` when building `build.spec`; this creates `Beamer-Package-Check.exe` instead of the normal app. Clear the flag before normal builds.

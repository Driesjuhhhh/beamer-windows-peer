from pathlib import Path
import os


source_dir = Path(SPECPATH)
smoke_check = os.environ.get("BEAMER_PACKAGE_CHECK") == "1"
pair_helper = os.environ.get("BEAMER_PAIR_HELPER") == "1"

analysis = Analysis(
    [str(source_dir / ("frozen_check.py" if smoke_check else "pair_windows.py" if pair_helper else "kvm_bridge_win.py"))],
    pathex=[str(source_dir)],
    binaries=[],
    datas=[(str(source_dir / "Beamer.ico"), "."), (str(source_dir / "assets"), "assets"), (str(source_dir.parent / "VERSION"), ".")],
    # effects.py imports its fx_* modules by name, which PyInstaller's analysis cannot see.
    hiddenimports=["cryptography", "nacl", "_cffi_backend"] + sorted(path.stem for path in source_dir.glob("fx_*.py")),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["PIL", "pystray", "tkinter", "numpy", "PySide6.QtQml", "PySide6.QtQuick", "PySide6.Qt3DCore", "PySide6.QtMultimedia"],
    noarchive=False,
)

# Qt 6.11 uses the Windows system ICU API. PATH may also contain Poppler's
# identically named ICU DLLs, whose exported names are version-suffixed and
# incompatible with Qt. Do not redistribute a foreign ICU in place of Windows'.
analysis.binaries = [entry for entry in analysis.binaries
                     if not Path(entry[0]).name.lower().startswith(("icuuc", "icuin", "icudt"))]

python_archive = PYZ(analysis.pure)

executable = EXE(
    python_archive,
    analysis.scripts,
    analysis.binaries,
    analysis.datas,
    [],
    name="Beamer-Package-Check" if smoke_check else "Pair-Beamer" if pair_helper else "Beamer",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=smoke_check or pair_helper,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(source_dir / "Beamer.ico"),
    # Embeds a requireAdministrator manifest so the receiver always runs elevated.
    # Windows UIPI silently drops SendInput events aimed at a focused elevated
    # window (e.g. an admin terminal) when the sender isn't elevated too.
    uac_admin=not (smoke_check or pair_helper),
)

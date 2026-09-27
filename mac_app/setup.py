import os
import sys
from pathlib import Path

from setuptools import setup


sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


VERSION = (Path(__file__).resolve().parent.parent / "VERSION").read_text().strip()
BUILD = os.environ.get("BEAMER_BUILD", "1")


setup(
    name="Beamer",
    version=VERSION,
    app=["kvm_bridge_app.py"],
    py_modules=[
        "bridge",
        "clipboard_mac",
        "config",
        "crossing",
        "desktop_mac",
        "gestures",
        "ignored",
        "input_injector_mac",
        "key_codes",
        "link_state",
        "media_keys",
        "notch_beam",
        "notch_island",
        "pages",
        "previews",
        "no_unlock",
        "pairing",
        "protocol",
        "receiver",
        "return_edge",
        "settings_store",
        "theme",
        "tokens",
        "wake",
        "widgets",
        "windows_input",
    ],
    # No Mac ships Hanken Grotesk or B612 Mono. macOS registers anything under
    # ATSApplicationFontsPath before the app runs, so the bundle carries the same files the
    # Windows receiver does rather than a second copy of them.
    data_files=[(
        "Fonts",
        [
            "../win_app/assets/HankenGrotesk-Variable.ttf",
            "../win_app/assets/B612Mono-Regular.ttf",
            "../win_app/assets/B612Mono-Bold.ttf",
        ],
    ), ("", ["../VERSION"])],
    options={
        "py2app": {
            "argv_emulation": False,
            # cryptography ships a compiled _rust extension plus cffi; py2app's own recipe pulls
            # both in, but naming the package keeps its data files and submodules in the bundle.
            "packages": ["rumps", "cryptography", "cffi"],
            "includes": ["objc", "AppKit", "ApplicationServices", "Quartz"],
            "iconfile": "../Beamer.icns",
            "plist": {
                "CFBundleDisplayName": "Beamer",
                "CFBundleIdentifier": "uk.co.kalkman.beamer",
                "CFBundleName": "Beamer",
                "CFBundleShortVersionString": VERSION,
                "CFBundleVersion": BUILD,
                "LSMinimumSystemVersion": "13.0",
                "LSUIElement": False,
                "NSHighResolutionCapable": True,
                "NSPrincipalClass": "NSApplication",
                "ATSApplicationFontsPath": "Fonts",
                "NSHumanReadableCopyright": "Copyright 2026 Toby Kalkman",
                "NSLocalNetworkUsageDescription": "Beamer needs to reach the Windows PC on your local network to forward keyboard and mouse input.",
            },
        }
    },
)

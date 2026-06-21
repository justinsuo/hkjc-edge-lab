#!/usr/bin/env python3
"""Generate a double-clickable macOS .app bundle that launches HKJC Edge Lab.

Usage: python scripts/make_macos_app.py [dest_dir]   (default: ~/Applications)
The bundle just runs the project's venv launcher, which opens a native pywebview window.
"""
import os
import stat
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
APP_NAME = "HKJC Edge Lab"


def main():
    dest = Path(sys.argv[1]).expanduser() if len(sys.argv) > 1 else Path.home() / "Applications"
    dest.mkdir(parents=True, exist_ok=True)
    app = dest / f"{APP_NAME}.app"
    macos = app / "Contents" / "MacOS"
    macos.mkdir(parents=True, exist_ok=True)

    venv_py = PROJECT / ".venv" / "bin" / "python"
    launcher = macos / "HKJCEdgeLab"
    launcher.write_text(f"""#!/bin/bash
# HKJC Edge Lab launcher
cd "{PROJECT}"
exec "{venv_py}" -m hkjc_edge.web.launcher
""")
    launcher.chmod(launcher.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

    (app / "Contents" / "Info.plist").write_text(f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>{APP_NAME}</string>
  <key>CFBundleDisplayName</key><string>{APP_NAME}</string>
  <key>CFBundleExecutable</key><string>HKJCEdgeLab</string>
  <key>CFBundleIdentifier</key><string>com.justin.hkjcedgelab</string>
  <key>CFBundleVersion</key><string>0.1.0</string>
  <key>CFBundleShortVersionString</key><string>0.1.0</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>LSMinimumSystemVersion</key><string>11.0</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>LSApplicationCategoryType</key><string>public.app-category.finance</string>
</dict></plist>
""")
    print(f"Created {app}")
    print(f"Launch: open '{app}'   (or double-click it in {dest})")


if __name__ == "__main__":
    main()

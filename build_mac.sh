#!/bin/bash
# Builds the Mac app and its installer: dist/APC-Titan-Bridge-mac-<arm64|x86_64>.dmg
# Run from this folder:  ./build_mac.sh     (needs Python 3.12: python3.12 or PYTHON=...)
set -euo pipefail
cd "$(dirname "$0")"
PY="${PYTHON:-python3.12}"
APP="dist/APC Titan Bridge.app"

"$PY" -m pip install -r requirements-build.txt
"$PY" -m PyInstaller --noconfirm --clean --windowed \
  --name "APC Titan Bridge" \
  --osx-bundle-identifier io.github.karolpasko.apc-titan-bridge \
  --add-data "apc_bridge/web:apc_bridge/web" \
  --add-data "apc_bridge/presets:apc_bridge/presets" \
  --collect-submodules mido \
  --hidden-import rtmidi \
  --collect-all webview \
  run_bridge.py

# macOS asks the user before an app may use the local network, which sACN needs.
plutil -insert NSLocalNetworkUsageDescription \
  -string "Sends sACN lighting data to Titan Go on your network." "$APP/Contents/Info.plist"
# Not signed with a paid Apple certificate: only an ad-hoc signature, so Gatekeeper
# needs "Open Anyway" the first time.
codesign --force --deep --sign - "$APP"

"$APP/Contents/MacOS/APC Titan Bridge" --self-test

DMG="dist/APC-Titan-Bridge-mac-$(uname -m).dmg"
rm -rf dist/dmg "$DMG"
mkdir dist/dmg
cp -R "$APP" dist/dmg/
ln -s /Applications dist/dmg/Applications
hdiutil create -volname "APC Titan Bridge" -srcfolder dist/dmg -format UDZO "$DMG"
echo "Done: $DMG"

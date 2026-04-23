#!/bin/bash
# Build + bundle + ad-hoc sign JarvisNative.app
# Usage: ./build_app.sh
set -euo pipefail

cd "$(dirname "$0")"

echo "[1/5] Building release binary..."
swift build -c release

BIN=".build/release/JarvisNative"
APP="JarvisNative.app"
CONTENTS="$APP/Contents"
MACOS="$CONTENTS/MacOS"
RES="$CONTENTS/Resources"

echo "[2/5] Assembling app bundle at $APP ..."
rm -rf "$APP"
mkdir -p "$MACOS" "$RES"
cp "$BIN" "$MACOS/JarvisNative"
cp Info.plist "$CONTENTS/Info.plist"
# PkgInfo so LaunchServices recognizes it as an app
printf 'APPL????' > "$CONTENTS/PkgInfo"

echo "[3/5] Ad-hoc signing with entitlements..."
codesign --force --deep --sign - \
    --entitlements Entitlements.plist \
    --options runtime \
    "$APP"

echo "[4/5] Registering with LaunchServices..."
/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister \
    -f "$(pwd)/$APP" || true

echo "[5/5] Verifying signature..."
codesign -dv --verbose=2 "$APP" 2>&1 | head -20

echo ""
echo "Built: $(pwd)/$APP"
echo "Run with: open $(pwd)/$APP"
echo "Or direct: $(pwd)/$APP/Contents/MacOS/JarvisNative"

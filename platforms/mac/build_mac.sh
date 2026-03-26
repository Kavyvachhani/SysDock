#!/bin/bash
# MacOS Build Script for SysDock
set -e

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
ROOT_DIR="$(cd "$DIR/../.." && pwd)"

echo "Building SysDock for macOS..."
cd "$ROOT_DIR"

# Clean old builds
rm -rf build/ dist/

# Install requirements if needed
echo "Verifying prerequisites..."
python3 -m pip install --upgrade --break-system-packages pyinstaller pywebview bottle rich psutil docker flask

echo "Running PyInstaller..."
# We run pyinstaller from the root directory so imports work smoothly.
pyinstaller --clean --noconfirm "$DIR/sysdock_mac.spec"

echo "Build complete! App bundle is located at $ROOT_DIR/dist/SysDock.app"

# Optional: Create a DMG or PKG wrapper
if command -v pkgbuild &> /dev/null; then
    echo "Creating PKG installer..."
    pkgbuild --root "$ROOT_DIR/dist/SysDock.app" \
             --identifier "io.sysdock.app" \
             --version "1.4.6" \
             --install-location "/Applications/SysDock.app" \
             "$ROOT_DIR/dist/SysDock_Installer.pkg"
    echo "PKG Installer created at $ROOT_DIR/dist/SysDock_Installer.pkg"
fi

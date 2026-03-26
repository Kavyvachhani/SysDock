#!/bin/bash
set -e

# Build CLI and GUI
echo "Building SysDock CLI & Native GUI..."
/opt/homebrew/bin/pyinstaller --clean SysDock_mac.spec

# Separate build for the loose CLI binary (F-mode)
/opt/homebrew/bin/pyinstaller --clean -F --name sysdock --paths . infravision_agent/__main__.py

# Prepare PKG structure in /tmp
PKG_TMP="/tmp/pkg_root_sysdock"
rm -rf "$PKG_TMP"
mkdir -p "$PKG_TMP/usr/local/bin"
mkdir -p "$PKG_TMP/Applications"

echo "Populating package root..."
cp dist/sysdock "$PKG_TMP/usr/local/bin/sysdock"
cp -R dist/SysDock.app "$PKG_TMP/Applications/"

echo "Setting proper permissions..."
chmod -R 755 "$PKG_TMP"
# Ensure the .app and binary are executable, others readable
find "$PKG_TMP" -type f ! -name "sysdock" ! -name "SysDock" -exec chmod 644 {} +
chmod 755 "$PKG_TMP/usr/local/bin/sysdock"
chmod 755 "$PKG_TMP/Applications/SysDock.app/Contents/MacOS/SysDock"

echo "Building macOS native .pkg via pkgbuild..."
mkdir -p mac
pkgbuild --root "$PKG_TMP" --identifier io.sysdock.agent --version "1.4.6" --install-location / --ownership preserve mac/SysDock_macOS.pkg

echo "✓ Created mac/SysDock_macOS.pkg with Native GUI and Cloud Icon!"

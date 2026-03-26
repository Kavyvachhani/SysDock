#!/bin/bash
# Linux Build & Package Script for SysDock
set -e

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
ROOT_DIR="$(cd "$DIR/../.." && pwd)"

VERSION="1.4.6"
PKG_DIR="$ROOT_DIR/dist/sysdock_${VERSION}_amd64"

echo "Building SysDock for Linux..."
cd "$ROOT_DIR"

# Clean old builds
rm -rf build/ dist/

# Install requirements if needed
echo "Verifying prerequisites..."
pip install --upgrade pyinstaller pywebview bottle rich psutil docker flask

echo "Running PyInstaller..."
pyinstaller --clean -y "$DIR/sysdock_linux.spec"

echo "Packaging into .deb..."
# Create Debian package structure
mkdir -p "$PKG_DIR/DEBIAN"
mkdir -p "$PKG_DIR/opt/sysdock"
mkdir -p "$PKG_DIR/usr/share/applications"
mkdir -p "$PKG_DIR/etc/systemd/system"

# Copy binary
cp "$ROOT_DIR/dist/SysDock" "$PKG_DIR/opt/sysdock/"
cp "$DIR/SysDock.png" "$PKG_DIR/opt/sysdock/"

# Copy system integrations
cp "$DIR/sysdock.desktop" "$PKG_DIR/usr/share/applications/"
cp "$DIR/sysdock.service" "$PKG_DIR/etc/systemd/system/"

# Create control file
cat <<EOF > "$PKG_DIR/DEBIAN/control"
Package: sysdock
Version: $VERSION
Architecture: amd64
Maintainer: Kavy Vachhani <kavy@vachhani.com>
Depends: libc6, libgtk-3-0, libwebkit2gtk-4.0-37
Section: utils
Priority: optional
Description: SysDock Monitoring Agent
 SysDock — Modern Linux monitoring agent with live terminal dashboard and Docker metrics
EOF

# Build package
dpkg-deb --build "$PKG_DIR"
echo "Build complete! .deb package is located at $ROOT_DIR/dist/sysdock_${VERSION}_amd64.deb"

#!/bin/bash
# SysDock Native macOS Installer Script

echo "Fetching latest SysDock macOS native package..."

if [ "$EUID" -ne 0 ]; then
  echo "Please run this installer as root (use sudo)."
  exit 1
fi

pip3 install infravision-agent --upgrade
echo "SysDock successfully installed on your Mac!"
echo "Run 'sysdock' from your terminal to start monitoring."
echo ""
echo "Note: If you'd prefer the native standalone Apple .pkg App installer,"
echo "you can download it from the GitHub Actions Artifacts tab for this repository."

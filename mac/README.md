# SysDock for macOS 🍎

Welcome to the macOS section of SysDock.

SysDock supports full native hardware monitoring on macOS, including:
- **Apple Silicon (M1/M2/M3)** native instruction sets.
- **Apple Metal API** GPU memory detection.
- **MacOS `sysctl`** integrated system metrics.

## How to use on Mac:
1. **The Automatic Installer Pipeline:**
   Every time code is pushed to this repository, GitHub Actions automatically compiles `SysDock_macOS.pkg` which you can download from the `Actions -> Artifacts` tab. Double click it on your Mac to install SysDock completely offline!

2. **The Terminal Way:**
   Run the terminal script locally or globally:
   ```bash
   sudo sh install_sysdock_mac.sh
   sysdock
   ```

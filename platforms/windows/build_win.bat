@echo off
setlocal enabledelayedexpansion
TITLE SysDock Windows Build

set DIR=%~dp0
set ROOT_DIR=%DIR%..\..
cd /d "%ROOT_DIR%"

echo Building SysDock for Windows...

:: Clean old builds
rmdir /s /q build dist >nul 2>&1

:: Install requirements
echo Verifying prerequisites...
pip install --upgrade pyinstaller pywebview bottle rich psutil docker flask Pillow pipx

echo Running PyInstaller...
pyinstaller --clean -y "%DIR%sysdock_win.spec"

echo Build complete! Executable is located at %ROOT_DIR%\dist\SysDock.exe
pause

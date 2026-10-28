@echo off
rem Builds dist\APC-Titan-Bridge.exe (a single file you can copy anywhere).
rem Run from this folder:  build_exe.bat
cd /d "%~dp0"
py -3.12 -m pip install -r requirements-build.txt || goto :error
py -3.12 -m PyInstaller --noconfirm --clean --onefile --windowed ^
  --name APC-Titan-Bridge ^
  --icon assets\icon.ico ^
  --add-data "apc_bridge\web;apc_bridge\web" ^
  --add-data "apc_bridge\presets;apc_bridge\presets" ^
  --collect-submodules mido ^
  --hidden-import rtmidi ^
  --collect-all webview ^
  run_bridge.py || goto :error
echo.
echo Done: dist\APC-Titan-Bridge.exe
exit /b 0
:error
echo.
echo Build FAILED - see the messages above.
exit /b 1

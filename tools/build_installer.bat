@echo off
rem SPDX-License-Identifier: Apache-2.0
rem Copyright (C) 2026 Arsmillis (https://github.com/Arsmillis/multiput)
rem Build build\installer\multiput-setup-<version>.exe (Windows).
rem Needs Python 3.11+ (py launcher) and the firmware built first with
rem tools/build_firmware.sh (WSL/Linux); tools\build.bat does both steps for you.
rem Installs Inno Setup 6 with winget the first time if it is missing.
setlocal
cd /d "%~dp0.."

if not exist build\firmware\multiput.uf2 goto :nofirmware
if not exist build\firmware\multiput.bin goto :nofirmware

py -3 -c "import sys; sys.exit(sys.version_info < (3, 11))" >nul 2>nul
if errorlevel 1 (
  echo Python 3.11 or newer is needed. Install it with: winget install -e --id Python.Python.3.13
  exit /b 1
)

rem Build tools go in a private venv, not your global Python.
if not exist build\venv\Scripts\python.exe (
  py -3 -m venv build\venv || exit /b 1
)
build\venv\Scripts\python -m pip install --quiet --disable-pip-version-check --upgrade pyinstaller pyserial pysdl2==0.9.17 pysdl2-dll==2.32.10 || exit /b 1

set /p VERSION=<VERSION
rem Other controllers: just SDL2.dll from pysdl2-dll (it also ships SDL_image, _mixer, _ttf... which multiput doesn't use).
rem Its import check also imports pip (optional), which would drag pip and setuptools in.
set SDL=--hidden-import sdl2dll --add-binary "%CD%\build\venv\Lib\site-packages\sdl2dll\dll\SDL2.dll;sdl2dll\dll" --exclude-module pip --exclude-module setuptools
echo Building multiput %VERSION%
build\venv\Scripts\python -m PyInstaller --noconfirm --log-level WARN --onefile --console --name multiput ^
  --add-data "%CD%\VERSION;." %SDL% ^
  --paths pc --distpath build\dist --workpath build\work --specpath build pc\multiput.py || exit /b 1
rem The same program without a console window: runs in the system tray.
build\venv\Scripts\python -m PyInstaller --noconfirm --log-level WARN --onefile --windowed --name multiputw ^
  --add-data "%CD%\VERSION;." %SDL% ^
  --paths pc --distpath build\dist --workpath build\work --specpath build pc\multiput.py || exit /b 1

call :findiscc
if not defined ISCC (
  echo == Installing Inno Setup 6 with winget ^(one time^)
  winget install -e --id JRSoftware.InnoSetup --accept-package-agreements --accept-source-agreements || exit /b 1
  call :findiscc
)
if not defined ISCC (
  echo Inno Setup 6 still not found. Install it from https://jrsoftware.org/isinfo.php and run this again.
  exit /b 1
)
"%ISCC%" /Q /DAppVersion=%VERSION% tools\multiput.iss || exit /b 1
echo Built build\installer\multiput-setup-*.exe
exit /b 0

:findiscc
set "ISCC="
if exist "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
exit /b 0

:nofirmware
echo Missing build\firmware\multiput.uf2 or multiput.bin. Build it first: tools\build.bat (or tools/build_firmware.sh in WSL)
exit /b 1

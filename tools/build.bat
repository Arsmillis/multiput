@echo off
rem SPDX-License-Identifier: Apache-2.0
rem Copyright (C) 2026 Arsmillis (https://github.com/Arsmillis/multiput)
rem One-step source build, run on Windows from a clone on a Windows drive:
rem   1. Pico firmware  (in WSL: tools/build_firmware.sh, installs its toolchain the first time)
rem   2. tests          (in WSL: tools/run_tests.sh)
rem   3. multiput.exe + installer (tools\build_installer.bat)
rem Output: build\installer\multiput-setup-<version>.exe
rem Log:    build\logs\build.log (this run's full output, replaced each run), plus
rem         build\logs\firmware.log (full compiler output). --no-log skips build.log.
setlocal
cd /d "%~dp0.."
set "ROOT=%CD%"
if /i "%~1"=="--no-log" goto :build

rem cmd can't show output and save it at once, so run this script again under
rem PowerShell, which writes each line to the terminal and to build.log (UTF-8)
rem as it arrives, and passes the exit code back.
if not exist build\logs mkdir build\logs
powershell -NoProfile -Command ^
  "$log = [IO.StreamWriter]::new('build\logs\build.log'); $log.AutoFlush = $true;" ^
  "$log.WriteLine('multiput build ' + (Get-Date -Format s));" ^
  "cmd /d /c 'tools\build.bat --no-log 2>&1' | ForEach-Object { $_; $log.WriteLine($_) };" ^
  "$code = $LASTEXITCODE; $log.Close(); exit $code"
exit /b %errorlevel%

:build
where wsl >nul 2>nul || (
  echo WSL is needed to build the Pico firmware. Install it with: wsl --install
  exit /b 1
)

echo ===== 1/3 Pico firmware (WSL)
wsl --cd "%ROOT%" bash tools/build_firmware.sh || goto :failed
echo ===== 2/3 Tests (WSL)
wsl --cd "%ROOT%" bash tools/run_tests.sh || goto :failed
echo ===== 3/3 multiput.exe and installer
call tools\build_installer.bat || goto :failed
echo ===== Done: build\installer\
exit /b 0

:failed
echo ===== Build failed; see the messages above (also in build\logs\).
exit /b 1

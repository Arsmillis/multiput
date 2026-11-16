@echo off
rem SPDX-License-Identifier: Apache-2.0
rem Copyright (C) 2026 Arsmillis (https://github.com/Arsmillis/multiput)
rem Run multiput from source (for people not using the installer).
rem Double-click it, or right-click > Send to > Desktop (create shortcut).
rem Any options are passed through, e.g.  multiput.bat --setup
py "%~dp0pc\multiput.py" %* || pause

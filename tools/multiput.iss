; SPDX-License-Identifier: Apache-2.0
; Copyright (C) 2026 Arsmillis (https://github.com/Arsmillis/multiput)
; Inno Setup script for the multiput Windows installer. Built by tools\build_installer.bat.
; Installs per user (no admin prompt) into %LOCALAPPDATA%\Programs\multiput.

; The version comes from the VERSION file: tools\build_installer.bat passes /DAppVersion=...
#ifndef AppVersion
  #define AppVersion "0.0.0-dev"
#endif

[Setup]
AppName=multiput
AppPublisher=Arsmillis
AppPublisherURL=https://github.com/Arsmillis/multiput
AppCopyright=Copyright (C) 2026 Arsmillis
InfoBeforeFile=..\NOTICE
AppVersion={#AppVersion}
DefaultDirName={autopf}\multiput
DefaultGroupName=multiput
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\build\installer
OutputBaseFilename=multiput-setup-{#AppVersion}
UninstallDisplayIcon={app}\multiput.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"

[Files]
Source: "..\build\dist\multiput.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\build\dist\multiputw.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\build\firmware\multiput.uf2"; DestDir: "{app}\firmware"; Flags: ignoreversion
Source: "..\build\firmware\multiput.bin"; DestDir: "{app}\firmware"; Flags: ignoreversion
Source: "..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\NOTICE"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\THIRD_PARTY_NOTICES.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\multiput"; Filename: "{app}\multiputw.exe"
Name: "{group}\multiput (console window)"; Filename: "{app}\multiput.exe"
Name: "{group}\multiput setup (flash the Pico)"; Filename: "{app}\multiput.exe"; Parameters: "--setup"
Name: "{group}\multiput update (Pico stays in place)"; Filename: "{app}\multiput.exe"; Parameters: "--update"
Name: "{group}\multiput button mapping"; Filename: "{app}\multiput.exe"; Parameters: "--remap"
Name: "{group}\multiput performance test"; Filename: "{app}\multiput.exe"; Parameters: "--perf-test"
Name: "{group}\Uninstall multiput"; Filename: "{uninstallexe}"
Name: "{autodesktop}\multiput"; Filename: "{app}\multiputw.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\multiput.exe"; Parameters: "--setup"; Description: "Set up the Pico now"; Flags: postinstall nowait skipifsilent

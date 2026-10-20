; Inno Setup script for the Little installer. Build after PyInstaller:
;   iscc /DAppVersion=0.1.0 packaging\little.iss
; Installs for the current user only, so it never needs an administrator.

#ifndef AppVersion
  #define AppVersion "0.1.0"
#endif

[Setup]
AppId={{7D3C9A41-5E2B-4F8A-9C61-1A2B3C4D5E6F}
AppName=Little
AppVersion={#AppVersion}
AppPublisher=Aditya Gupta
DefaultDirName={localappdata}\Programs\Little
DefaultGroupName=Little
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=LittleSetup-{#AppVersion}
SetupIconFile=..\little.ico
UninstallDisplayIcon={app}\Little.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern

[Tasks]
Name: "desktopicon"; Description: "Put Little on the desktop"
Name: "startup"; Description: "Start Little when Windows starts"; Flags: unchecked

[Files]
Source: "..\dist\Little\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion
; Your settings live in your profile and survive updates and uninstalling.
Source: "..\.env.example"; DestDir: "{localappdata}\Little"; DestName: ".env"; Flags: onlyifdoesntexist uninsneveruninstall

[Icons]
Name: "{group}\Little"; Filename: "{app}\Little.exe"
Name: "{autodesktop}\Little"; Filename: "{app}\Little.exe"; Tasks: desktopicon
Name: "{userstartup}\Little"; Filename: "{app}\Little.exe"; Tasks: startup

[Run]
Filename: "notepad.exe"; Parameters: """{localappdata}\Little\.env"""; Description: "Add your Gemini API key now"; Flags: postinstall nowait skipifsilent
Filename: "{app}\Little.exe"; Description: "Start Little"; Flags: postinstall nowait skipifsilent unchecked

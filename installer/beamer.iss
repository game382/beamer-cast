; Inno Setup script. Build with: ISCC installer\beamer.iss   (after PyInstaller has produced dist\Beamer)
#define AppName "Beamer"
#define AppVersion "0.1.5"

[Setup]
AppId={{B3A4E1D2-5C6F-4A7B-9D10-BEA3E2C0FFEE}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=Beamer
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
OutputDir=..\dist
OutputBaseFilename=Beamer-Setup
SetupIconFile=..\beamer\assets\beamer.ico
UninstallDisplayIcon={app}\Beamer.exe
Compression=lzma2
SolidCompression=yes
; Admin is needed once, to add the firewall rule that lets your TVs reach Beamer's stream.
PrivilegesRequired=admin
WizardStyle=modern
LicenseFile=..\LICENSE
CloseApplications=yes

[Files]
Source: "..\dist\Beamer\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{group}\Beamer"; Filename: "{app}\Beamer.exe"
Name: "{autodesktop}\Beamer"; Filename: "{app}\Beamer.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked

[Run]
; Let devices on your home network (and only those) reach Beamer's stream, even when Windows marks your Wi-Fi "Public".
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""Beamer"""; Flags: runhidden
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=""Beamer"" dir=in action=allow program=""{app}\Beamer.exe"" profile=any remoteip=LocalSubnet"; Flags: runhidden
Filename: "{app}\Beamer.exe"; Description: "Start Beamer"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""Beamer"""; Flags: runhidden; RunOnceId: "RemoveBeamerFirewall"

; OBS Remote's installer (Inno Setup 6). Built by installer/build.py, which passes AppVersion and BuildDir
; (BuildDir\app = the program, BuildDir\runtime = Python's embeddable package).
;
; - Installs for the current user only, in %LOCALAPPDATA%\Programs\OBS Remote: no admin prompt. The firewall step
;   in the setup window asks for admin itself.
; - After installing it runs "core.py start": on a PC where OBS Remote was set up before (any copy, e.g. a
;   downloaded folder), the server now runs from here, with Startup and the Start menu pointing here. Then it
;   offers to open the setup window.
; - The in-app Update runs a newer Setup.exe with /VERYSILENT; PrepareToInstall stops this copy first.
; - Uninstalling runs "core.py uninstall" (server, Startup, Start menu, Tailscale route, firewall rules), then
;   deletes the folder. Logs and settings in %LOCALAPPDATA%\OBS Remote stay.

#ifndef AppVersion
  #error Run installer/build.py, which passes AppVersion and BuildDir
#endif

[Setup]
; Never change AppId: Windows uses it to recognise an update to the same program.
AppId={{68935600-5442-463C-9CF9-CA108F1A2CB2}
AppName=OBS Remote
AppVersion={#AppVersion}
AppVerName=OBS Remote {#AppVersion}
; File details (Properties > Details). SignPath checks product name and version when it signs.
VersionInfoVersion={#NumVersion}
VersionInfoProductName=OBS Remote
VersionInfoProductVersion={#NumVersion}
VersionInfoProductTextVersion={#AppVersion}
VersionInfoDescription=OBS Remote installer
VersionInfoCopyright=Copyright (c) 2026 mdukasa. MIT License.
AppPublisher=OBS Remote
AppPublisherURL=https://github.com/mdukasa/obs-remote
AppSupportURL=https://github.com/mdukasa/obs-remote/issues
AppUpdatesURL=https://github.com/mdukasa/obs-remote/releases
PrivilegesRequired=lowest
DefaultDirName={autopf}\OBS Remote
DisableDirPage=auto
DisableProgramGroupPage=yes
DisableReadyPage=yes
OutputBaseFilename=OBS-Remote-Setup-{#AppVersion}
SetupIconFile=..\setup\icon.ico
UninstallDisplayIcon={app}\setup\icon.ico
UninstallDisplayName=OBS Remote
WizardStyle=modern
Compression=lzma2/max
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
CloseApplications=no
RestartApplications=no

[Messages]
FinishedLabel=OBS Remote is installed. The setup window walks you through the rest: turning on OBS's remote control, letting phones through the firewall, and the QR code for each phone.

[InstallDelete]
; A new Python replaces the old one completely.
Type: filesandordirs; Name: "{app}\runtime"

[Files]
Source: "{#BuildDir}\app\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "{#BuildDir}\runtime\*"; DestDir: "{app}\runtime"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{userprograms}\OBS Remote"; Filename: "{app}\runtime\pythonw.exe"; Parameters: """{app}\setup\core.py"" panel"; WorkingDir: "{app}"; IconFilename: "{app}\setup\icon.ico"; Comment: "OBS Remote: set up, phone QR code and status"

[Run]
Filename: "{app}\runtime\python.exe"; Parameters: """{app}\setup\core.py"" start"; WorkingDir: "{app}"; Flags: runhidden waituntilterminated; StatusMsg: "Starting OBS Remote..."
Filename: "{app}\runtime\pythonw.exe"; Parameters: """{app}\setup\core.py"" panel"; WorkingDir: "{app}"; Description: "Open OBS Remote setup"; Flags: postinstall nowait skipifsilent

[UninstallRun]
Filename: "{app}\runtime\python.exe"; Parameters: """{app}\setup\core.py"" uninstall"; WorkingDir: "{app}"; Flags: runhidden waituntilterminated; RunOnceId: "RemoveOBSRemote"

[UninstallDelete]
; Everything in the program folder, including files a source-ZIP update or Python added. Logs and settings are elsewhere.
Type: filesandordirs; Name: "{app}"

[Code]
// Before replacing files: stop this copy's server and setup window (Windows can't replace a file in use).
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  Py: String;
  Code: Integer;
begin
  Result := '';
  Py := ExpandConstant('{app}\runtime\python.exe');
  if FileExists(Py) then
    Exec(Py, '"' + ExpandConstant('{app}\setup\core.py') + '" stop', ExpandConstant('{app}'), SW_HIDE, ewWaitUntilTerminated, Code);
end;

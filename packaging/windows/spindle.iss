; Spindle installer (Inno Setup 6). Built by packaging/build.py on Windows:
;   ISCC /DAppVersion=0.1.0 /DSourceDir=build\dist\Spindle /DIconFile=... /DOutputDir=dist spindle.iss
;
; Per-user install: no administrator rights, no UAC prompt. Goes to
; %LOCALAPPDATA%\Programs\Spindle, adds Start Menu entries and an
; uninstaller (Settings > Apps). Uninstalling stops Spindle, removes
; "start with Windows" (its logon task), and asks whether to delete the
; settings and logs.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef SourceDir
  #define SourceDir "..\..\build\dist\Spindle"
#endif
#ifndef IconFile
  #define IconFile "..\..\build\icons\spindle.ico"
#endif
#ifndef Pictures
  #define Pictures "..\..\build\icons"
#endif
#ifndef OutputDir
  #define OutputDir "..\..\dist"
#endif

; Spindle was called Satsuma up to 0.1.0-rc3. The AppId is Satsuma's, so
; installing Spindle over it is an upgrade of the same app: one entry in
; Settings > Apps, now called Spindle. Before installing, a running
; Satsuma is stopped; then its old program folder, Start Menu folder and
; desktop shortcut are deleted. Spindle itself moves the settings over and
; removes Satsuma's start at login on its first start.

[Setup]
AppId={{6F0B9A52-4E0C-4D8B-9B37-5C1E2A7D3F10}
AppName=Spindle
AppVersion={#AppVersion}
AppVerName=Spindle {#AppVersion}
AppPublisher=Spindle
AppSupportURL=https://github.com/narcissus29/spindle
VersionInfoVersion={#AppVersion}
PrivilegesRequired=lowest
DefaultDirName={autopf}\Spindle
DefaultGroupName=Spindle
; never reuse Satsuma's folder / Start Menu group (same AppId)
UsePreviousAppDir=no
UsePreviousGroup=no
DisableProgramGroupPage=yes
DisableDirPage=auto
DisableReadyPage=yes
WizardStyle=modern
OutputDir={#OutputDir}
OutputBaseFilename=Spindle-Setup
SetupIconFile={#IconFile}
; the pixel-art logo on its dark tile (first / last page) and the icon (top right)
WizardImageFile={#Pictures}\installer-side.bmp,{#Pictures}\installer-side-200.bmp
WizardSmallImageFile={#Pictures}\installer-small.bmp,{#Pictures}\installer-small-200.bmp
UninstallDisplayIcon={app}\Spindle.exe
UninstallDisplayName=Spindle
Compression=lzma2/ultra64
SolidCompression=yes
LZMAUseSeparateProcess=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; Spindle keeps running in the tray: close it to update or uninstall.
CloseApplications=force
RestartApplications=no

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[InstallDelete]
; files of an older version that this one no longer has
Type: filesandordirs; Name: "{app}\_internal"
; Satsuma (the old name): its program, Start Menu folder and desktop shortcut
Type: filesandordirs; Name: "{autopf}\Satsuma"
Type: filesandordirs; Name: "{autoprograms}\Satsuma"
Type: files; Name: "{autodesktop}\Satsuma.lnk"

[Icons]
Name: "{group}\Spindle"; Filename: "{app}\Spindle.exe"
Name: "{group}\Spindle Settings"; Filename: "{app}\Spindle.exe"; Parameters: "--settings"
Name: "{autodesktop}\Spindle"; Filename: "{app}\Spindle.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Spindle.exe"; Description: "Start Spindle"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{app}\Spindle.exe"; Parameters: "--quit"; Flags: runhidden waituntilterminated; RunOnceId: "QuitSpindle"
; "Start when I log in" is a Task Scheduler logon task (or a Run value): remove it.
Filename: "{app}\Spindle.exe"; Parameters: "--remove-autostart"; Flags: runhidden waituntilterminated; RunOnceId: "RemoveAutostart"

[Registry]
; Spindle may write this value ("start with Windows", when a logon task
; isn't allowed); remove it on uninstall.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: none; ValueName: "Spindle"; Flags: uninsdeletevalue

[Code]
// Satsuma (the old name) still installed: stop it before its folder goes.
// (Its start at login is removed by Spindle on its first start, which the
// installer's last page offers.)
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  OldExe: String;
  Code: Integer;
begin
  Result := '';
  OldExe := ExpandConstant('{autopf}\Satsuma\Satsuma.exe');
  if FileExists(OldExe) then
  begin
    Exec(OldExe, '--quit', '', SW_HIDE, ewWaitUntilTerminated, Code);
    Sleep(500);
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if (CurUninstallStep = usPostUninstall) and (not UninstallSilent) then
  begin
    if MsgBox('Also delete your Spindle settings and logs?', mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
      DelTree(ExpandConstant('{localappdata}\spindle'), True, True, True);
  end;
end;

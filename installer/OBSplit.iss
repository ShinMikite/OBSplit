; OBSplit installer (Inno Setup 6). Built by installer/build.ps1.

#ifndef AppVersion
  #define AppVersion "0.1.0"
#endif
#ifndef SourceRoot
  #define SourceRoot ".."
#endif
#ifndef PythonDir
  #define PythonDir "..\build\python"
#endif

[Setup]
AppId={{6F3B2A71-8C4D-4E59-9A7B-2D1E0F5C8B34}
AppName=OBSplit
AppVersion={#AppVersion}
AppVerName=OBSplit {#AppVersion}
AppPublisher=ShinMikite
AppPublisherURL=https://github.com/ShinMikite/OBSplit
AppSupportURL=https://github.com/ShinMikite/OBSplit/issues
DefaultDirName={localappdata}\OBSplit
DisableDirPage=yes
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputBaseFilename=OBSplit-Setup-{#AppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
LicenseFile={#SourceRoot}\LICENSE
CloseApplications=yes
RestartApplications=no
UninstallDisplayName=OBSplit

[Files]
Source: "{#SourceRoot}\app\*"; DestDir: "{app}\app"; Excludes: "data,__pycache__"; Flags: recursesubdirs ignoreversion
Source: "{#SourceRoot}\obs-scripts\*"; DestDir: "{app}\obs-scripts"; Flags: ignoreversion
Source: "{#SourceRoot}\tools\*.py"; DestDir: "{app}\tools"; Flags: ignoreversion
Source: "{#PythonDir}\*"; DestDir: "{app}\python"; Flags: recursesubdirs ignoreversion
Source: "{#SourceRoot}\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#SourceRoot}\README.md"; DestDir: "{app}"; Flags: ignoreversion isreadme

[Dirs]
Name: "{app}\app\data"

[Icons]
Name: "{autoprograms}\OBSplit\OBSplit - Connect to OBS"; Filename: "{app}\python\pythonw.exe"; Parameters: """{app}\tools\obs_integration.py"" install"; WorkingDir: "{app}"; Comment: "Add the OBSplit panels and scripts to OBS Studio again"
Name: "{autoprograms}\OBSplit\Uninstall OBSplit"; Filename: "{uninstallexe}"

[Run]
Filename: "{app}\python\pythonw.exe"; Parameters: """{app}\tools\obs_integration.py"" install"; WorkingDir: "{app}"; StatusMsg: "Connecting OBSplit to OBS Studio..."; Flags: waituntilterminated; Check: not WizardSilent
; quiet installs (e.g. scripted updates) skip the "connected" message box
Filename: "{app}\python\pythonw.exe"; Parameters: """{app}\tools\obs_integration.py"" install --quiet"; WorkingDir: "{app}"; StatusMsg: "Connecting OBSplit to OBS Studio..."; Flags: waituntilterminated; Check: WizardSilent

[UninstallRun]
Filename: "{app}\python\pythonw.exe"; Parameters: """{app}\tools\obs_integration.py"" uninstall"; WorkingDir: "{app}"; Flags: waituntilterminated; RunOnceId: "OBSplitDisconnect"

[UninstallDelete]
Type: filesandordirs; Name: "{app}\app\__pycache__"
Type: filesandordirs; Name: "{app}\python\Lib\tkinter\__pycache__"
Type: filesandordirs; Name: "{app}\tools\__pycache__"

[Code]
function ObsRunning(): Boolean;
var
  Rc: Integer;
begin
  { find.exe returns 0 when obs64.exe is in the task list }
  Result := Exec(ExpandConstant('{cmd}'), '/C tasklist /FI "IMAGENAME eq obs64.exe" /NH | find /I "obs64.exe" >nul',
                 '', SW_HIDE, ewWaitUntilTerminated, Rc) and (Rc = 0);
end;

procedure StopHelper();
var
  Rc: Integer;
begin
  { OBSplit's helper stops by itself a few seconds after OBS closes; make sure it has, so no files are in use }
  Exec('powershell.exe', '-NoProfile -NonInteractive -Command "Get-CimInstance Win32_Process -Filter ''Name=''''pythonw.exe'''''' | ' +
       'Where-Object { $_.ExecutablePath -like ''*\OBSplit\python\*'' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"',
       '', SW_HIDE, ewWaitUntilTerminated, Rc);
end;

function InitializeSetup(): Boolean;
begin
  Result := True;
  { OBSplit's files and OBS's settings can only be updated while OBS is closed }
  while ObsRunning() do
  begin
    if SuppressibleMsgBox('OBS Studio is open.' + #13#10#13#10 +
        'Close OBS, then click Retry. Your panels, layout, sign-ins and settings are kept.',
        mbInformation, MB_RETRYCANCEL, IDCANCEL) = IDCANCEL then
    begin
      Result := False;
      Exit;
    end;
  end;
  StopHelper();
end;

function InitializeUninstall(): Boolean;
begin
  Result := True;
  while ObsRunning() do
  begin
    if SuppressibleMsgBox('OBS Studio is open.' + #13#10#13#10 + 'Close OBS, then click Retry.',
        mbInformation, MB_RETRYCANCEL, IDCANCEL) = IDCANCEL then
    begin
      Result := False;
      Exit;
    end;
  end;
  StopHelper();
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if (CurUninstallStep = usPostUninstall) and DirExists(ExpandConstant('{app}\app\data')) then
    if MsgBox('Also delete your OBSplit settings, YouTube sign-in and chat history?',
              mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
      DelTree(ExpandConstant('{app}'), True, True, True);
end;

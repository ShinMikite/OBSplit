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
Filename: "{app}\python\pythonw.exe"; Parameters: """{app}\tools\obs_integration.py"" install"; WorkingDir: "{app}"; StatusMsg: "Connecting OBSplit to OBS Studio..."; Flags: waituntilterminated

[UninstallRun]
Filename: "{app}\python\pythonw.exe"; Parameters: """{app}\tools\obs_integration.py"" uninstall"; WorkingDir: "{app}"; Flags: waituntilterminated; RunOnceId: "OBSplitDisconnect"

[UninstallDelete]
Type: filesandordirs; Name: "{app}\app\__pycache__"
Type: filesandordirs; Name: "{app}\python\Lib\tkinter\__pycache__"
Type: filesandordirs; Name: "{app}\tools\__pycache__"

[Code]
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if (CurUninstallStep = usPostUninstall) and DirExists(ExpandConstant('{app}\app\data')) then
    if MsgBox('Also delete your OBSplit settings, YouTube sign-in and chat history?',
              mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
      DelTree(ExpandConstant('{app}'), True, True, True);
end;

; Dial Timer 설치 스크립트 (Inno Setup 6)
;
; 빌드:  ISCC.exe installer\DialTimer.iss
; 선행:  build\dist\DialTimer\ (PyInstaller onedir 산출물)이 있어야 한다.
;
; 관리자 권한을 요구하지 않는다(PrivilegesRequired=lowest).
; 트레이 유틸리티일 뿐인데 UAC를 띄울 이유가 없고, 사용자 폴더에 설치하면
; 설정 저장·자동 시작 등록이 모두 권한 문제 없이 동작한다.

#define AppName        "Dial Timer"
#define AppVersion     "1.0.1"
#define AppPublisher   "foxnail.kr"
#define AppURL         "https://foxnail.kr"
#define AppExeName     "DialTimer.exe"
#define SrcDir         "..\build\dist\DialTimer"

[Setup]
AppId={{8F2C6A31-4D7B-4E19-9C55-DA1E7B6F0C42}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}
AppUpdatesURL={#AppURL}
VersionInfoVersion={#AppVersion}
VersionInfoCompany={#AppPublisher}
VersionInfoDescription={#AppName} — 0~99분 다이얼 타이머
VersionInfoCopyright=Copyright (C) 2026 foxnail.kr

DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog

; 설치 중 앱이 떠 있으면 알려주고 닫는다 (tray_timer.py의 뮤텍스와 같은 이름)
AppMutex=DialTimer.SingleInstance
CloseApplications=yes
RestartApplications=no

LicenseFile=..\LICENSE
SetupIconFile=..\build\dial_timer.ico
UninstallDisplayIcon={app}\{#AppExeName}
UninstallDisplayName={#AppName}
WizardStyle=modern
Compression=lzma2/ultra64
SolidCompression=yes
OutputDir=Output
OutputBaseFilename=DialTimer-{#AppVersion}-Setup
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "korean";  MessagesFile: "compiler:Languages\Korean.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; \
    GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "startupicon"; Description: "Windows 시작할 때 자동 실행"; \
    GroupDescription: "추가 옵션:"

[Files]
Source: "{#SrcDir}\{#AppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#SrcDir}\_internal\*";   DestDir: "{app}\_internal"; \
    Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\LICENSE";              DestDir: "{app}"; DestName: "LICENSE.txt"; \
    Flags: ignoreversion
Source: "..\README.md";            DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#AppName}";          Filename: "{app}\{#AppExeName}"
Name: "{group}\{cm:UninstallProgram,{#AppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}";    Filename: "{app}\{#AppExeName}"; \
    Tasks: desktopicon
Name: "{userstartup}\{#AppName}";    Filename: "{app}\{#AppExeName}"; \
    Tasks: startupicon

[Run]
Filename: "{app}\{#AppExeName}"; \
    Description: "{cm:LaunchProgram,{#AppName}}"; \
    Flags: nowait postinstall skipifsilent
Filename: "{#AppURL}"; Description: "foxnail.kr 방문"; \
    Flags: nowait postinstall skipifsilent shellexec unchecked

[UninstallDelete]
; 사용자 설정은 %APPDATA%에 있으므로 제거 시 함께 정리한다.
Type: filesandordirs; Name: "{userappdata}\DialTimer"

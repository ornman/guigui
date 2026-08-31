; 桂桂 v2 Inno Setup 安装器(由 build_guigui.bat 在 PyInstaller 之后调用)
; 数据在 %LOCALAPPDATA%\GuiGui,卸载保留(日志/配置由用户决定去留)

#define MyAppName "桂桂"
#define MyAppNameAscii "GuiGui"
#define MyAppVersion "2.0.0"
#define MyAppExeName "guigui.exe"
#define MyAppId "{{B7E4F2C9-3D5A-4E8B-9F1C-2A6D8E0B4C71}"

[Setup]
AppId={#MyAppId}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
DefaultDirName={autopf}\{#MyAppNameAscii}
DefaultGroupName={#MyAppName}
OutputDir=Output
OutputBaseFilename=guigui-setup-{#MyAppVersion}
Compression=lzma2
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64compatible
; HKCU 协议注册 + 每用户任务计划,免管理员
PrivilegesRequired=lowest
WizardStyle=modern
DisableProgramGroupPage=yes
SetupIconFile=guigui.ico
UninstallDisplayIcon={app}\{#MyAppExeName}

[Files]
Source: "..\dist\guigui\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion
Source: "安装说明.txt"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"

[Registry]
; guigui:// 协议唤回通道(应用首次运行时也会幂等注册一遍)
Root: HKCU; Subkey: "Software\Classes\guigui"; ValueType: string; ValueData: "URL:guigui protocol"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\guigui"; ValueType: string; ValueName: "URL Protocol"; ValueData: ""; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\guigui\shell\open\command"; ValueType: string; ValueData: """{app}\{#MyAppExeName}"" ""%1"""; Flags: uninsdeletekey

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "启动桂桂"; Flags: nowait postinstall skipifsilent

[UninstallRun]
; 计划任务无意义残留(exe 已删,任务只会报错),卸载必删;被安全软件拦则留着也无害
Filename: "{sys}\schtasks.exe"; Parameters: "/delete /tn GuiGui /f"; Flags: runhidden; RunOnceId: "DelTaskMain"
Filename: "{sys}\schtasks.exe"; Parameters: "/delete /tn GuiGui-Patrol /f"; Flags: runhidden; RunOnceId: "DelTaskPatrol"

[Code]
var
  DelUserData: Boolean;

function WebView2Installed(): Boolean;
var
  v: String;
begin
  Result :=
    RegQueryStringValue(HKLM, 'SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', v) or
    RegQueryStringValue(HKCU, 'SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', v);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if (CurStep = ssInstall) and not WebView2Installed() then
    MsgBox(
      '桂桂需要 WebView2 运行时(Windows 11 已内置,一般无需安装)。' + #13#10 +
      '如启动异常,请到这里安装后重试:' + #13#10 +
      'https://developer.microsoft.com/microsoft-edge/webview2/',
      mbInformation, MB_OK);
end;

procedure CurUninstallStepChanged(CurStep: TUninstallStep);
var
  dataDir: String;
  rc: Integer;
begin
  if CurStep = usUninstall then
  begin
    dataDir := ExpandConstant('{localappdata}') + '\GuiGui';
    DelUserData :=
      DirExists(dataDir) and
      (SuppressibleMsgBox(
        '是否同时删除配置、日志和已保存的密码?' + #13#10 + #13#10 +
        '选「否」则保留(重装桂桂时不用重新配置);' + #13#10 +
        '选「是」则彻底清干净,包括凭据管理器里的密码。',
        mbConfirmation, MB_YESNO, IDNO) = IDYES);
    if DelUserData then
    begin
      // 凭据目标名是「学号@GuiGui」(keyring Windows 后端格式),学号只有
      // 桂桂自己认得 —— 趁 exe 还没删,让它清(顺序:先清凭据再删数据)
      Exec(ExpandConstant('{app}\guigui.exe'), '--clear-creds', '',
           SW_HIDE, ewWaitUntilTerminated, rc);
      DelTree(dataDir, True, True, True);
    end;
  end;
end;

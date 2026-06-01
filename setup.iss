; SchoolAutoLogin Inno Setup Installer Script

#define AppName "SchoolAutoLogin"
#define AppVersion "1.0.0"
#define AppPublisher "SchoolAutoLogin"
#define AppExeName "SchoolAutoLogin.exe"
#define TaskName "SchoolAutoLogin"

[Setup]
AppId={{B7E3F2A1-4D5C-6E8F-9A0B-1C2D3E4F5A6B}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={userappdata}\{#AppName}
DefaultGroupName={#AppName}
UninstallDisplayIcon={app}\{#AppExeName}
OutputDir=installer_output
OutputBaseFilename=SchoolAutoLogin_Setup_{#AppVersion}
Compression=lzma2/ultra64
SolidCompression=yes
PrivilegesRequired=lowest
DisableProgramGroupPage=yes
DisableDirPage=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
Source: "dist\{#AppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "dist\config.json"; DestDir: "{app}"; Flags: confirmoverwrite

[Tasks]
Name: "createtask"; Description: "创建每日定时登录任务（06:55）"; GroupDescription: "定时任务:"; \
    Flags: checkedonce

[Run]
Filename: "powershell.exe"; \
    Parameters: "-ExecutionPolicy Bypass -Command ""$exe = '{app}\{#AppExeName}'; $action = New-ScheduledTaskAction -Execute $exe -Argument '--silent'; $trigger = New-ScheduledTaskTrigger -Daily -At '06:55:00'; $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -WakeToRun -ExecutionTimeLimit (New-TimeSpan -Minutes 5); Register-ScheduledTask -TaskName '{#TaskName}' -Action $action -Trigger $trigger -Settings $settings -Force"""; \
    Flags: runhidden; \
    Tasks: createtask; \
    StatusMsg: "正在配置定时登录任务..."

[Code]
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
    ResultCode: Integer;
begin
    if CurUninstallStep = usPostUninstall then
    begin
        Exec('schtasks.exe', '/delete /tn "{#TaskName}" /f',
             '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
    end;
end;

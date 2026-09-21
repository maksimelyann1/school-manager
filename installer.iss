[Setup]
AppName=School Manager
AppVersion=2.8
DefaultDirName={autopf}\SchoolManager
DefaultGroupName=School Manager
UninstallDisplayIcon={app}\SchoolManager.exe
SetupIconFile=app.ico
Compression=lzma2
SolidCompression=yes
OutputDir=dist
OutputBaseFilename=SchoolManager_Setup
PrivilegesRequired=admin
CloseApplications=yes
RestartApplications=no
DisableProgramGroupPage=yes
LanguageDetectionMethod=uilanguage
WizardStyle=modern
DisableWelcomePage=no

[Languages]
Name: "ukrainian"; MessagesFile: "compiler:Languages\Ukrainian.isl"

[Messages]
WelcomeLabel1=Вітаємо у встановленні School Manager
WelcomeLabel2=1-авторизуватися в програмі через телеграм, в налаштуваннях%n2-натиснути кнопку групи телеграм синхронізувати%n3-створити потрібні категорії для зручності%n4-налаштувати автоповідомлення (якщо потрібно)%n5-користуватися%n%nП.С програма сучасна, в ній можна перетягувати об'єкти, вставляти, копіювати%nП.П.С це Beta версія, можливі баги

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
; The main executable and all its dependencies created by PyInstaller
Source: "dist\SchoolManager\*"; DestDir: "{app}"; Excludes: "*.db,*.db-shm,*.db-wal,*.session,*.session-journal,*.session-wal,*.session-shm,*.log,school_manager.db*,user_session*"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\School Manager"; Filename: "{app}\SchoolManager.exe"
Name: "{autodesktop}\School Manager"; Filename: "{app}\SchoolManager.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\SchoolManager.exe"; Description: "{cm:LaunchProgram,School Manager}"; Flags: nowait postinstall runasoriginaluser; Check: not WizardSilent
Filename: "{app}\SchoolManager.exe"; Flags: nowait runasoriginaluser; Check: WizardSilent

[Code]
var
  DeleteUserDataOnUninstall: Boolean;

function InitializeUninstall(): Boolean;
begin
  DeleteUserDataOnUninstall := False;

  if not UninstallSilent then
  begin
    DeleteUserDataOnUninstall :=
      MsgBox(
        'Видалити також особисті дані School Manager?'#13#10#13#10 +
        'Якщо натиснути "Так", буде видалено базу, Telegram-сесію, шаблони, файли автоповідомлень і логи з папки:'#13#10 +
        ExpandConstant('{localappdata}\SchoolManager') + #13#10#13#10 +
        'Якщо натиснути "Ні", програма видалиться, але ваші дані залишаться.',
        mbConfirmation,
        MB_YESNO
      ) = IDYES;
  end;

  Result := True;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  DataDir: string;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    RegDeleteValue(HKEY_CURRENT_USER, 'Software\Microsoft\Windows\CurrentVersion\Run', 'SchoolManager');
    RegDeleteValue(HKEY_CURRENT_USER, 'Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run', 'SchoolManager');
    RegDeleteValue(HKEY_LOCAL_MACHINE, 'Software\Microsoft\Windows\CurrentVersion\Run', 'SchoolManager');

    if DeleteUserDataOnUninstall then
    begin
      DataDir := ExpandConstant('{localappdata}\SchoolManager');
      if DirExists(DataDir) then
      begin
        DelTree(DataDir, True, True, True);
      end;
    end;
  end;
end;

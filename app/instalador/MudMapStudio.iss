; Instalador do MudMap Studio (Inno Setup 6) — por usuário, sem pedir administrador.
; Instala em %LOCALAPPDATA%\Programs\MudMap Studio, cria atalho no Menu Iniciar (Área de Trabalho opcional),
; associa .mudmap ao app (duplo clique abre o pacote) e mostra a licença MIT.
;
; Uso (depois do app\build_exe.ps1):
;   iscc /DVersao=0.5.0 /DOrigem=C:\MudMapStudio\dist\MudMapStudio /OC:\MudMapStudio app\instalador\MudMapStudio.iss
;   -> C:\MudMapStudio\MudMapStudio-setup.exe
; Instalação silenciosa (testes/CI): MudMapStudio-setup.exe /VERYSILENT /SUPPRESSMSGBOXES /CURRENTUSER /TASKS="associar"

#ifndef Versao
  #define Versao "0.0.0"
#endif
#ifndef Origem
  #error Informe /DOrigem=<pasta dist\MudMapStudio gerada pelo app\build_exe.ps1>
#endif
#define Raiz AddBackslash(SourcePath) + "..\.."

[Setup]
AppId={{7B4E2C1A-6D3F-4E8B-9A51-2C0F8D6E4B13}
AppName=MudMap Studio
AppVersion={#Versao}
AppVerName=MudMap Studio {#Versao}
AppPublisher=MudMap
AppPublisherURL=https://github.com/mateusandrade-geo/MudMap
AppSupportURL=https://github.com/mateusandrade-geo/MudMap/issues
AppUpdatesURL=https://github.com/mateusandrade-geo/MudMap/releases
VersionInfoVersion={#Versao}
DefaultDirName={autopf}\MudMap Studio
DefaultGroupName=MudMap Studio
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputBaseFilename=MudMapStudio-setup
SetupIconFile={#Raiz}\app\mudmap_studio\recursos\mudmap.ico
UninstallDisplayIcon={app}\MudMapStudio.exe
UninstallDisplayName=MudMap Studio {#Versao}
LicenseFile={#Raiz}\LICENSE
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
ChangesAssociations=yes
CloseApplications=yes

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "associar"; Description: "Abrir arquivos .mudmap com o MudMap Studio"; GroupDescription: "Arquivos:"

[Files]
Source: "{#Origem}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#Raiz}\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#Raiz}\LICENSE-DADOS.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\MudMap Studio"; Filename: "{app}\MudMapStudio.exe"
Name: "{autodesktop}\MudMap Studio"; Filename: "{app}\MudMapStudio.exe"; Tasks: desktopicon

[Registry]
; HKA = HKCU na instalação por usuário (HKLM se instalado como administrador)
Root: HKA; Subkey: "Software\Classes\.mudmap"; ValueType: string; ValueName: ""; ValueData: "MudMap.Pacote"; Flags: uninsdeletevalue; Tasks: associar
Root: HKA; Subkey: "Software\Classes\.mudmap\OpenWithProgids"; ValueType: string; ValueName: "MudMap.Pacote"; ValueData: ""; Flags: uninsdeletevalue; Tasks: associar
Root: HKA; Subkey: "Software\Classes\MudMap.Pacote"; ValueType: string; ValueName: ""; ValueData: "Pacote MudMap"; Flags: uninsdeletekey; Tasks: associar
Root: HKA; Subkey: "Software\Classes\MudMap.Pacote\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\MudMapStudio.exe,0"; Tasks: associar
Root: HKA; Subkey: "Software\Classes\MudMap.Pacote\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\MudMapStudio.exe"" ""%1"""; Tasks: associar

[Run]
Filename: "{app}\MudMapStudio.exe"; Description: "{cm:LaunchProgram,MudMap Studio}"; Flags: nowait postinstall skipifsilent

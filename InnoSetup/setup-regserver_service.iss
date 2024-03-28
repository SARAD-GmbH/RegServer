; Script generated by the Inno Setup Script Wizard.
; SEE THE DOCUMENTATION FOR DETAILS ON CREATING INNO SETUP SCRIPT FILES!

#define MyAppName "RegServer-Service"
#define MyAppVersion "2.3.1"
#define MyAppPublisher "SARAD"
#define MyAppURL "https://www.sarad.de"
#define MyOutputDir "..\dist"
#define Source "..\dist\regserver-service"
#define Destination "{commonpf64}\SARAD\RegServer-Service"
#define Config "{commonappdata}\SARAD\RegServer-Service"
#define Distribution "\\server\system\distribution"
#define DriverExeName "CDM212364_Setup.exe"

[Setup]
; NOTE: The value of AppId uniquely identifies this application.
; Do not use the same AppId value in installers for other applications.
; (To generate a new GUID, click Tools | Generate GUID inside the IDE.)
AppId = {{EFFB1B8D-B6DB-417D-B137-0CB0D919E907}
AppPublisher=SARAD GmbH
AppPublisherURL = {#MyAppURL}
AppSupportURL = {#MyAppURL}
AppUpdatesURL = {#MyAppURL}
DefaultGroupName = {#MyAppPublisher}\{#MyAppName}
OutputDir = {#MyOutputDir}
OutputBaseFilename = "setup-regserver_service"
SetupIconFile = {#Source}\network.ico
Compression = lzma
SolidCompression = yes
ChangesAssociations = yes
UsePreviousAppDir = no
LicenseFile = {#Source}\eula.txt
AppCopyright=SARAD GmbH, 2024
SignTool=signtool
FlatComponentsList=False
AlwaysShowComponentsList=False
ShowComponentSizes=False
DisableReadyPage=True
DisableReadyMemo=True
DisableFinishedPage=True
AppName=SARAD Registration Server Service
AppVersion={#MyAppVersion}
DefaultDirName={#Destination}
DisableDirPage=yes
AllowUNCPath=False

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"
Name: "catalan"; MessagesFile: "compiler:Languages\Catalan.isl"
Name: "corsican"; MessagesFile: "compiler:Languages\Corsican.isl"
Name: "czech"; MessagesFile: "compiler:Languages\Czech.isl"
Name: "danish"; MessagesFile: "compiler:Languages\Danish.isl"
Name: "dutch"; MessagesFile: "compiler:Languages\Dutch.isl"
Name: "finnish"; MessagesFile: "compiler:Languages\Finnish.isl"
Name: "french"; MessagesFile: "compiler:Languages\French.isl"
Name: "german"; MessagesFile: "compiler:Languages\German.isl"
Name: "hebrew"; MessagesFile: "compiler:Languages\Hebrew.isl"
Name: "italian"; MessagesFile: "compiler:Languages\Italian.isl"
Name: "japanese"; MessagesFile: "compiler:Languages\Japanese.isl"
Name: "norwegian"; MessagesFile: "compiler:Languages\Norwegian.isl"
Name: "polish"; MessagesFile: "compiler:Languages\Polish.isl"
Name: "portuguese"; MessagesFile: "compiler:Languages\Portuguese.isl"
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "slovenian"; MessagesFile: "compiler:Languages\Slovenian.isl"
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"
Name: "turkish"; MessagesFile: "compiler:Languages\Turkish.isl"
Name: "ukrainian"; MessagesFile: "compiler:Languages\Ukrainian.isl"

[Files]
; Source: "{#Distribution}\{#DriverExeName}"; DestDir: "{tmp}"; Flags: deleteafterinstall; Components: Drivers
Source: "{#Source}\*"; DestDir: "{#Destination}"; Flags: createallsubdirs recursesubdirs promptifolder restartreplace uninsrestartdelete; Components: RS
Source: "{#Source}\config.example.toml"; DestDir: "{#Config}"; Components: RS
; NOTE: Don't use "Flags: ignoreversion" on any shared system files

[Run]
Filename: "{#Destination}\setup-rss.bat"; Flags: nowait hidewizard runhidden runascurrentuser; Components: RS
; Filename: "{tmp}\{#DriverExeName}"; Flags: nowait hidewizard skipifdoesntexist skipifsilent; Description: "{cm:LaunchProgram,{#StringChange(DriverExeName, '&', '&&')}}"; Components: Drivers

[Components]
; Name: "Drivers"; Description: "FTDI Drivers"; Types: custom full
Name: "RS"; Description: "SARAD Registration Server"; Types: custom full compact; Flags: fixed

[UninstallRun]
Filename: "{app}\remove-rss.bat"; Flags: skipifdoesntexist runascurrentuser; Components: RS

[PostCompile]
Name: "post-compile.bat"; Flags: abortonerror cmdprompt redirectoutput

[PreCompile]
Name: "pre-compile.bat"; Flags: abortonerror cmdprompt redirectoutput

; [InstallDelete]
; Type: files; Name: "{app}\{#DriverExeName}"; Components: Drivers

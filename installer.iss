; ===========================================================================
;  Instalador de QuoteTrip  (Inno Setup 6)
;  Empaqueta la carpeta autocontenida dist\QuoteTrip\ en un unico
;  Setup.exe que instala la app, crea accesos directos y desinstalador.
;  NO requiere Python ni dependencias en el equipo destino.
;
;  Compilar:  abre este archivo con Inno Setup y pulsa "Compile",
;             o ejecuta  build_installer.bat
; ===========================================================================

#define MyAppName "QuoteTrip"
#define MyAppVersion "1.4.9"
#define MyAppPublisher "QuoteTrip"
#define MyAppExeName "QuoteTrip.exe"

[Setup]
; AppId identifica la app para actualizaciones/desinstalacion (no lo cambies)
AppId={{A4B5A28E-DC27-4ACB-B8EC-66F81687B0A8}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\QuoteTrip
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
UninstallDisplayIcon={app}\{#MyAppExeName}
OutputDir=Output
OutputBaseFilename=QuoteTrip-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
; Instalacion por-usuario: sin pedir permisos de administrador
PrivilegesRequired=lowest
; Icono del propio instalador (opcional; solo si existe)
#if FileExists("assets\logo.ico")
SetupIconFile=assets\logo.ico
#endif

[Languages]
Name: "es"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "desktopicon"; Description: "Crear un acceso directo en el escritorio"; GroupDescription: "Accesos directos:"

[Files]
; Toda la carpeta autocontenida generada por PyInstaller
Source: "dist\QuoteTrip\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion
; Copia del icono en la raiz para usarlo en los accesos directos
#if FileExists("assets\logo.ico")
Source: "assets\logo.ico"; DestDir: "{app}"; Flags: ignoreversion
#endif
; (Opcional) Instalador de WebView2: incluyelo solo si pones este archivo
; junto al .iss. Da la ventana nativa en Windows 10 que no lo tenga.
#if FileExists("MicrosoftEdgeWebview2Setup.exe")
Source: "MicrosoftEdgeWebview2Setup.exe"; DestDir: "{tmp}"; Flags: deleteafterinstall
#endif

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\logo.ico"
Name: "{group}\Desinstalar {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\logo.ico"; Tasks: desktopicon

[Run]
; Instalar WebView2 en silencio si hace falta (solo si se incluyo el bootstrapper)
#if FileExists("MicrosoftEdgeWebview2Setup.exe")
Filename: "{tmp}\MicrosoftEdgeWebview2Setup.exe"; Parameters: "/silent /install"; StatusMsg: "Instalando componente WebView2..."; Check: NeedsWebView2; Flags: waituntilterminated
#endif
; Ofrecer abrir la app al terminar
Filename: "{app}\{#MyAppExeName}"; Description: "Ejecutar {#MyAppName} ahora"; Flags: nowait postinstall skipifsilent

[Code]
function WebView2Installed(): Boolean;
var
  v: string;
begin
  Result :=
    RegQueryStringValue(HKLM, 'SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', v) or
    RegQueryStringValue(HKLM, 'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', v) or
    RegQueryStringValue(HKCU, 'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', v);
end;

function NeedsWebView2(): Boolean;
begin
  Result := not WebView2Installed();
end;

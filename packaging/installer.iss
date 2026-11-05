; Inno Setup script for BoneChilling (Windows installer).
; Packages the PyInstaller one-folder build (dist\BoneChilling) into a single
; Setup.exe. Build:  ISCC.exe packaging\installer.iss  (from the repo root)

#define AppName "BoneChilling"
#define AppVersion "0.2.0"
#define AppPublisher "BoneChilling"
#define AppExe "BoneChilling.exe"

[Setup]
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
OutputDir=Output
OutputBaseFilename=BoneChilling-Setup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupFlags: unchecked

[Files]
; PyInstaller one-folder output (relative to the repo root where ISCC runs).
Source: "..\dist\BoneChilling\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent

; NOTE: pywebview renders via Microsoft Edge WebView2 (preinstalled on Windows 11
; and most Windows 10). For older machines, bundle the Evergreen bootstrapper
; (MicrosoftEdgeWebview2Setup.exe) and add a [Run] entry to install it here.

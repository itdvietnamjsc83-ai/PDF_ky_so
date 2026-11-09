; ===== Bộ cài PDF Ký Số – Inno Setup 6 (miễn phí, https://jrsoftware.org) =====
; Biên dịch: build_windows.bat tự gọi ISCC nếu máy có Inno Setup. Hoặc: ISCC installer\setup.iss
; Sửa AppPublisher / URL cho đúng thông tin nhà phát triển (app\branding.py).
#define AppName "PDF Ky So"
#define AppVersion GetEnv("PDFKYSO_VERSION")
#if AppVersion == ""
  #define AppVersion "0.6.0"
#endif
#define AppExe "PdfKySo.exe"

[Setup]
; AppId phải trùng APP_ID trong app\install_check.py (phần mềm kiểm tra đã được cài bằng bộ cài này)
AppId={{6E2B1F0C-7A41-4C7E-9E1B-5D2A9C0F4B11}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=Cong ty co phan Cong nghe ITD Viet Nam
AppPublisherURL=https://itdvietnam.com.vn
AppSupportURL=https://itdvietnam.com.vn
DefaultDirName={autopf}\PdfKySo
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
OutputDir=..\dist
OutputBaseFilename=PdfKySo-Setup-{#AppVersion}
SetupIconFile=..\assets\app.ico
UninstallDisplayIcon={app}\{#AppExe}
Compression=lzma2/ultra64
SolidCompression=yes
LZMANumBlockThreads=4
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
PrivilegesRequired=admin
WizardStyle=modern
CloseApplications=yes
RestartApplications=no
ChangesAssociations=yes
VersionInfoVersion={#AppVersion}

[Languages]
Name: "vi"; MessagesFile: "Vietnamese.isl"

[CustomMessages]
vi.TaskPrinters=Tạo máy in ảo "PDF Ky so" và "PDF Khay ghep" (in từ Word ra thẳng phần mềm)
vi.TaskAssoc=Thêm "PDF Ký Số" vào mục "Mở bằng" của file PDF
vi.TaskDefault=Đặt làm phần mềm mở file PDF mặc định
vi.TaskOffice=Thêm menu chuột phải cho file Word/Excel/PDF: "Mở bằng PDF Ký Số (giữ nguyên khổ giấy)", "Thêm vào khay ghép"
vi.RunActivate=Mở phần mềm để chọn Dùng thử 15 ngày hoặc nhập mã kích hoạt

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "printers"; Description: "{cm:TaskPrinters}"
Name: "assoc"; Description: "{cm:TaskAssoc}"
Name: "assoc\default"; Description: "{cm:TaskDefault}"; Flags: unchecked
Name: "officemenu"; Description: "{cm:TaskOffice}"

[Files]
Source: "..\dist\main.dist\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "cai_may_in_ao.ps1"; DestDir: "{app}\installer"; Flags: ignoreversion
Source: "go_may_in_ao.ps1"; DestDir: "{app}\installer"; Flags: ignoreversion

[Dirs]
; thư mục chung cho máy in ảo (script cấp quyền sửa cho nhóm Users)
Name: "{commonappdata}\PdfKySo\spool"

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\Kích hoạt bản quyền"; Filename: "{app}\{#AppExe}"; Parameters: "--activate"
Name: "{group}\{cm:UninstallProgram,{#AppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Registry]
; "Mở bằng" (không chiếm quyền phần mềm PDF khác trừ khi chọn mặc định)
Root: HKA; Subkey: "Software\Classes\PdfKySo.Document"; ValueType: string; ValueName: ""; ValueData: "Tài liệu PDF"; Flags: uninsdeletekey; Tasks: assoc
Root: HKA; Subkey: "Software\Classes\PdfKySo.Document\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\{#AppExe},0"; Tasks: assoc
Root: HKA; Subkey: "Software\Classes\PdfKySo.Document\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" ""%1"""; Tasks: assoc
Root: HKA; Subkey: "Software\Classes\.pdf\OpenWithProgids"; ValueType: string; ValueName: "PdfKySo.Document"; ValueData: ""; Flags: uninsdeletevalue; Tasks: assoc
Root: HKA; Subkey: "Software\Classes\.pdf"; ValueType: string; ValueName: ""; ValueData: "PdfKySo.Document"; Flags: uninsdeletevalue; Tasks: assoc\default
Root: HKA; Subkey: "Software\Classes\Applications\{#AppExe}\SupportedTypes"; ValueType: string; ValueName: ".pdf"; ValueData: ""; Tasks: assoc

; Menu chuột phải cho file Word/Excel/PowerPoint: chuyển bằng chính Office -> PDF giữ nguyên khổ giấy
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.doc\shell\PdfKySo.Open"; ValueType: string; ValueName: "MUIVerb"; ValueData: "Mở bằng PDF Ký Số (giữ nguyên khổ giấy)"; Flags: uninsdeletekey; Tasks: officemenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.doc\shell\PdfKySo.Open"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\{#AppExe},0"; Tasks: officemenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.doc\shell\PdfKySo.Open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" ""%1"""; Tasks: officemenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.doc\shell\PdfKySo.Tray"; ValueType: string; ValueName: "MUIVerb"; ValueData: "Thêm vào khay ghép PDF Ký Số"; Flags: uninsdeletekey; Tasks: officemenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.doc\shell\PdfKySo.Tray"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\{#AppExe},0"; Tasks: officemenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.doc\shell\PdfKySo.Tray\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" --tray ""%1"""; Tasks: officemenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.docx\shell\PdfKySo.Open"; ValueType: string; ValueName: "MUIVerb"; ValueData: "Mở bằng PDF Ký Số (giữ nguyên khổ giấy)"; Flags: uninsdeletekey; Tasks: officemenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.docx\shell\PdfKySo.Open"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\{#AppExe},0"; Tasks: officemenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.docx\shell\PdfKySo.Open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" ""%1"""; Tasks: officemenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.docx\shell\PdfKySo.Tray"; ValueType: string; ValueName: "MUIVerb"; ValueData: "Thêm vào khay ghép PDF Ký Số"; Flags: uninsdeletekey; Tasks: officemenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.docx\shell\PdfKySo.Tray"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\{#AppExe},0"; Tasks: officemenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.docx\shell\PdfKySo.Tray\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" --tray ""%1"""; Tasks: officemenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.rtf\shell\PdfKySo.Open"; ValueType: string; ValueName: "MUIVerb"; ValueData: "Mở bằng PDF Ký Số (giữ nguyên khổ giấy)"; Flags: uninsdeletekey; Tasks: officemenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.rtf\shell\PdfKySo.Open"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\{#AppExe},0"; Tasks: officemenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.rtf\shell\PdfKySo.Open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" ""%1"""; Tasks: officemenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.rtf\shell\PdfKySo.Tray"; ValueType: string; ValueName: "MUIVerb"; ValueData: "Thêm vào khay ghép PDF Ký Số"; Flags: uninsdeletekey; Tasks: officemenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.rtf\shell\PdfKySo.Tray"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\{#AppExe},0"; Tasks: officemenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.rtf\shell\PdfKySo.Tray\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" --tray ""%1"""; Tasks: officemenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.odt\shell\PdfKySo.Open"; ValueType: string; ValueName: "MUIVerb"; ValueData: "Mở bằng PDF Ký Số (giữ nguyên khổ giấy)"; Flags: uninsdeletekey; Tasks: officemenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.odt\shell\PdfKySo.Open"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\{#AppExe},0"; Tasks: officemenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.odt\shell\PdfKySo.Open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" ""%1"""; Tasks: officemenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.odt\shell\PdfKySo.Tray"; ValueType: string; ValueName: "MUIVerb"; ValueData: "Thêm vào khay ghép PDF Ký Số"; Flags: uninsdeletekey; Tasks: officemenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.odt\shell\PdfKySo.Tray"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\{#AppExe},0"; Tasks: officemenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.odt\shell\PdfKySo.Tray\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" --tray ""%1"""; Tasks: officemenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.xls\shell\PdfKySo.Open"; ValueType: string; ValueName: "MUIVerb"; ValueData: "Mở bằng PDF Ký Số (giữ nguyên khổ giấy)"; Flags: uninsdeletekey; Tasks: officemenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.xls\shell\PdfKySo.Open"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\{#AppExe},0"; Tasks: officemenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.xls\shell\PdfKySo.Open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" ""%1"""; Tasks: officemenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.xls\shell\PdfKySo.Tray"; ValueType: string; ValueName: "MUIVerb"; ValueData: "Thêm vào khay ghép PDF Ký Số"; Flags: uninsdeletekey; Tasks: officemenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.xls\shell\PdfKySo.Tray"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\{#AppExe},0"; Tasks: officemenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.xls\shell\PdfKySo.Tray\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" --tray ""%1"""; Tasks: officemenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.xlsx\shell\PdfKySo.Open"; ValueType: string; ValueName: "MUIVerb"; ValueData: "Mở bằng PDF Ký Số (giữ nguyên khổ giấy)"; Flags: uninsdeletekey; Tasks: officemenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.xlsx\shell\PdfKySo.Open"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\{#AppExe},0"; Tasks: officemenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.xlsx\shell\PdfKySo.Open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" ""%1"""; Tasks: officemenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.xlsx\shell\PdfKySo.Tray"; ValueType: string; ValueName: "MUIVerb"; ValueData: "Thêm vào khay ghép PDF Ký Số"; Flags: uninsdeletekey; Tasks: officemenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.xlsx\shell\PdfKySo.Tray"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\{#AppExe},0"; Tasks: officemenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.xlsx\shell\PdfKySo.Tray\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" --tray ""%1"""; Tasks: officemenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.ods\shell\PdfKySo.Open"; ValueType: string; ValueName: "MUIVerb"; ValueData: "Mở bằng PDF Ký Số (giữ nguyên khổ giấy)"; Flags: uninsdeletekey; Tasks: officemenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.ods\shell\PdfKySo.Open"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\{#AppExe},0"; Tasks: officemenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.ods\shell\PdfKySo.Open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" ""%1"""; Tasks: officemenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.ods\shell\PdfKySo.Tray"; ValueType: string; ValueName: "MUIVerb"; ValueData: "Thêm vào khay ghép PDF Ký Số"; Flags: uninsdeletekey; Tasks: officemenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.ods\shell\PdfKySo.Tray"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\{#AppExe},0"; Tasks: officemenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.ods\shell\PdfKySo.Tray\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" --tray ""%1"""; Tasks: officemenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.ppt\shell\PdfKySo.Open"; ValueType: string; ValueName: "MUIVerb"; ValueData: "Mở bằng PDF Ký Số (giữ nguyên khổ giấy)"; Flags: uninsdeletekey; Tasks: officemenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.ppt\shell\PdfKySo.Open"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\{#AppExe},0"; Tasks: officemenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.ppt\shell\PdfKySo.Open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" ""%1"""; Tasks: officemenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.ppt\shell\PdfKySo.Tray"; ValueType: string; ValueName: "MUIVerb"; ValueData: "Thêm vào khay ghép PDF Ký Số"; Flags: uninsdeletekey; Tasks: officemenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.ppt\shell\PdfKySo.Tray"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\{#AppExe},0"; Tasks: officemenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.ppt\shell\PdfKySo.Tray\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" --tray ""%1"""; Tasks: officemenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.pptx\shell\PdfKySo.Open"; ValueType: string; ValueName: "MUIVerb"; ValueData: "Mở bằng PDF Ký Số (giữ nguyên khổ giấy)"; Flags: uninsdeletekey; Tasks: officemenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.pptx\shell\PdfKySo.Open"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\{#AppExe},0"; Tasks: officemenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.pptx\shell\PdfKySo.Open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" ""%1"""; Tasks: officemenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.pptx\shell\PdfKySo.Tray"; ValueType: string; ValueName: "MUIVerb"; ValueData: "Thêm vào khay ghép PDF Ký Số"; Flags: uninsdeletekey; Tasks: officemenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.pptx\shell\PdfKySo.Tray"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\{#AppExe},0"; Tasks: officemenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.pptx\shell\PdfKySo.Tray\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" --tray ""%1"""; Tasks: officemenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.odp\shell\PdfKySo.Open"; ValueType: string; ValueName: "MUIVerb"; ValueData: "Mở bằng PDF Ký Số (giữ nguyên khổ giấy)"; Flags: uninsdeletekey; Tasks: officemenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.odp\shell\PdfKySo.Open"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\{#AppExe},0"; Tasks: officemenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.odp\shell\PdfKySo.Open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" ""%1"""; Tasks: officemenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.odp\shell\PdfKySo.Tray"; ValueType: string; ValueName: "MUIVerb"; ValueData: "Thêm vào khay ghép PDF Ký Số"; Flags: uninsdeletekey; Tasks: officemenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.odp\shell\PdfKySo.Tray"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\{#AppExe},0"; Tasks: officemenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.odp\shell\PdfKySo.Tray\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" --tray ""%1"""; Tasks: officemenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.pdf\shell\PdfKySo.Tray"; ValueType: string; ValueName: "MUIVerb"; ValueData: "Thêm vào khay ghép PDF Ký Số"; Flags: uninsdeletekey; Tasks: officemenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.pdf\shell\PdfKySo.Tray"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\{#AppExe},0"; Tasks: officemenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.pdf\shell\PdfKySo.Tray\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" --tray ""%1"""; Tasks: officemenu

[Run]
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\installer\cai_may_in_ao.ps1"" -Root ""{commonappdata}\PdfKySo\spool"""; StatusMsg: "Đang tạo máy in ảo…"; Flags: runhidden waituntilterminated; Tasks: printers
Filename: "{app}\{#AppExe}"; Parameters: "--activate"; Description: "{cm:RunActivate}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\installer\go_may_in_ao.ps1"""; Flags: runhidden waituntilterminated; RunOnceId: "GoMayInAo"

[UninstallDelete]
Type: filesandordirs; Name: "{commonappdata}\PdfKySo\spool"
; Dữ liệu người dùng (thư viện dấu, bản quyền) KHÔNG xóa khi gỡ -> cài lại vẫn còn.

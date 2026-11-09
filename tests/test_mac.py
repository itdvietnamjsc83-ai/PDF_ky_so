"""Bản macOS: kiểm thử phần không phụ thuộc máy Mac (giả lập sys.platform / osascript).
Chạy thật trên Mac: build_mac.sh chạy toàn bộ bộ kiểm thử + --selftest trên gói .app."""
import os
import plistlib
import subprocess
import sys
import xml.dom.minidom

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "installer", "mac"))

import mac_bundle  # noqa: E402

from app import install_check, macintegration, osutil  # noqa: E402
from .test_gui_phase5 import qapp  # noqa: F401,E402


# ------------------------------------------------------------------ osutil
def test_kbd_mac_symbols(monkeypatch):
    monkeypatch.setattr(osutil, "IS_MAC", True)
    assert osutil.kbd("Ctrl+Z để hoàn tác") == "⌘Z để hoàn tác"
    assert osutil.kbd("Giữ Alt để tắt hút") == "Giữ ⌥ để tắt hút"
    assert osutil.kbd("(Alt+kéo)") == "(⌥kéo)"
    monkeypatch.setattr(osutil, "IS_MAC", False)
    assert osutil.kbd("Ctrl+Z") == "Ctrl+Z"


@pytest.mark.skipif(sys.platform == "win32", reason="đường dẫn kiểu Mac")
def test_mac_data_dirs(monkeypatch, tmp_path):
    monkeypatch.setattr(osutil, "IS_MAC", True)
    for k in ("APPDATA", "LOCALAPPDATA"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    assert osutil.roaming_base() == str(tmp_path / "Library" / "Application Support")
    assert osutil.local_base() == str(tmp_path / "Library" / "Application Support")
    assert osutil.logs_base() == str(tmp_path / "Library" / "Logs")


def test_mac_reveal_and_open_use_finder(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(osutil, "IS_WIN", False)
    monkeypatch.setattr(osutil, "IS_MAC", True)
    monkeypatch.setattr(osutil.subprocess, "Popen", lambda a, **k: calls.append(a))
    f = tmp_path / "a.pdf"
    f.write_bytes(b"%PDF")
    osutil.reveal(str(f))
    osutil.open_path(str(f))
    assert calls == [["open", "-R", str(f)], ["open", str(f)]]


def test_mac_machine_ids_parse(monkeypatch):
    out = ('+-o J314sAP  <class IOPlatformExpertDevice>\n    "IOPlatformSerialNumber" = "C02XYZ123"\n'
           '    "IOPlatformUUID" = "12345678-ABCD-EF00-1111-222233334444"\n')
    monkeypatch.setattr(osutil.subprocess, "run",
                        lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout=out, stderr=""))
    assert set(osutil.mac_machine_ids()) == {"C02XYZ123", "12345678-ABCD-EF00-1111-222233334444"}


# ------------------------------------------------------------------ install_check
@pytest.mark.skipif(sys.platform == "win32", reason="đường dẫn kiểu Mac")
def test_check_mac_translocation():
    ok, msg = install_check.check_mac("/Volumes/PDF Ký Số 1.0/PDF Ký Số.app")
    assert not ok and "Applications" in msg
    ok, _ = install_check.check_mac("/private/var/folders/x/AppTranslocation/ABC/d/PDF Ký Số.app")
    assert not ok
    assert install_check.check_mac("/Applications/PDF Ký Số.app") == (True, "")
    assert install_check.mac_bundle_path("/Applications/PDF Ký Số.app/Contents/MacOS/PdfKySo") == \
        "/Applications/PDF Ký Số.app"


# ------------------------------------------------------------------ PDF Services
def test_pdf_services_install_idempotent(monkeypatch, tmp_path):
    monkeypatch.setattr(macintegration, "services_dir", lambda: str(tmp_path / "PDF Services"))
    spool = tmp_path / "spool"
    made = macintegration.install_pdf_services(str(spool))
    assert len(made) == 2
    for kind, title in macintegration.SERVICES.items():
        p = tmp_path / "PDF Services" / title
        s = p.read_text(encoding="utf-8")
        assert s.startswith("#!/bin/sh") and str(spool / kind) in s and macintegration.BUNDLE_ID in s
        assert os.access(p, os.X_OK)
    m = os.path.getmtime(made[0])
    assert macintegration.install_pdf_services(str(spool)) == made
    assert os.path.getmtime(made[0]) == m
    assert "PDF Services: có" in macintegration.selftest()
    macintegration.remove_pdf_services()
    assert not os.listdir(tmp_path / "PDF Services")


@pytest.mark.skipif(sys.platform == "win32", reason="script sh")
def test_pdf_service_script_copies_file(monkeypatch, tmp_path):
    monkeypatch.setattr(macintegration, "services_dir", lambda: str(tmp_path / "svc"))
    spool = tmp_path / "spool"
    macintegration.install_pdf_services(str(spool))
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "open").write_text("#!/bin/sh\nexit 0\n")
    os.chmod(bindir / "open", 0o755)
    src = tmp_path / "in.pdf"
    src.write_bytes(b"%PDF-1.4 test")
    env = dict(os.environ, PATH=f"{bindir}{os.pathsep}{os.environ['PATH']}")
    script = tmp_path / "svc" / macintegration.SERVICES["tray"]
    subprocess.run([str(script), "Hợp đồng: số 1/2026", "", str(src)], check=True, env=env)
    got = os.listdir(spool / "tray")
    assert len(got) == 1 and got[0].endswith(".pdf") and "/" not in got[0] and ":" not in got[0]
    assert (spool / "tray" / got[0]).read_bytes() == b"%PDF-1.4 test"


# ------------------------------------------------------------------ Office cho Mac (AppleScript giả lập)
def test_office_to_pdf_applescript(monkeypatch, tmp_path):
    monkeypatch.setattr(macintegration, "OFFICE_GROUP", str(tmp_path / "group"))
    monkeypatch.setattr(macintegration, "office_app_installed", lambda k: True)
    seen = {}

    def fake_run(args, **k):
        seen["args"] = args
        with open(args[4], "wb") as f:              # "Excel" ghi ra file PDF
            f.write(b"%PDF-1.7 ok")
        return subprocess.CompletedProcess(args, 0, stdout="OK", stderr="")
    monkeypatch.setattr(macintegration.subprocess, "run", fake_run)
    src = tmp_path / "bang tinh.xlsx"
    src.write_bytes(b"PK")
    dst = tmp_path / "out.pdf"
    used = macintegration.office_to_pdf(str(src), str(dst), "excel",
                                        {"sheets": ["Sheet1", "Tổng hợp"], "fit": "width", "orientation": "landscape"})
    assert used == "Microsoft Excel" and dst.read_bytes() == b"%PDF-1.7 ok"
    a = seen["args"]
    assert a[0] == "/usr/bin/osascript" and "Microsoft Excel" in a[2]
    assert a[3].startswith(str(tmp_path / "group")) and a[5:] == ["Sheet1|Tổng hợp", "width", "landscape"]
    assert not os.listdir(tmp_path / "group" / "PdfKySo")          # dọn thư mục tạm


def test_office_to_pdf_permission_message(monkeypatch, tmp_path):
    from app.office import OfficeError
    monkeypatch.setattr(macintegration, "OFFICE_GROUP", str(tmp_path / "group"))
    monkeypatch.setattr(macintegration, "office_app_installed", lambda k: True)
    monkeypatch.setattr(macintegration.subprocess, "run", lambda args, **k: subprocess.CompletedProcess(
        args, 1, stdout="", stderr="execution error: Not authorized to send Apple events to Microsoft Word. (-1743)"))
    src = tmp_path / "a.docx"
    src.write_bytes(b"PK")
    with pytest.raises(OfficeError, match="Tự động hóa"):
        macintegration.office_to_pdf(str(src), str(tmp_path / "a.pdf"), "word")


def test_office_to_pdf_not_installed(monkeypatch, tmp_path):
    monkeypatch.setattr(macintegration, "office_app_installed", lambda k: False)
    assert macintegration.office_to_pdf(__file__, str(tmp_path / "x.pdf"), "word") is None


def test_office_module_uses_mac_path(monkeypatch, tmp_path):
    from app import office
    monkeypatch.setattr(office.sys, "platform", "darwin")
    called = {}

    def fake(src, dst, kind, excel):
        called.update(kind=kind, excel=excel)
        open(dst, "wb").write(b"%PDF")
        return "Microsoft Word"
    monkeypatch.setattr(macintegration, "office_to_pdf", fake)
    src = tmp_path / "hop dong.docx"
    src.write_bytes(b"PK")
    out, used = office.to_pdf(str(src), str(tmp_path / "o.pdf"))
    assert used == "Microsoft Word" and called == {"kind": "word", "excel": None}


def test_fix_shortcut_texts(monkeypatch, qapp):  # noqa: F811
    from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget
    monkeypatch.setattr(osutil, "IS_MAC", True)
    w = QWidget()
    lay = QVBoxLayout(w)
    b = QPushButton("Hoàn tác (Ctrl+Z)")
    b.setToolTip("Giữ Alt để xoay tự do")
    lbl = QLabel("Ctrl+F: tìm")
    lay.addWidget(b)
    lay.addWidget(lbl)
    macintegration.fix_shortcut_texts(w)
    assert b.text() == "Hoàn tác (⌘Z)" and b.toolTip() == "Giữ ⌥ để xoay tự do" and lbl.text() == "⌘F: tìm"
    w.deleteLater()


# ------------------------------------------------------------------ main.py: mở file từ Finder / Dock
def test_file_open_event_buffer_then_deliver(qapp):  # noqa: F811
    import main
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QFileOpenEvent
    c = main.FileOpenCatcher()
    assert c.handle(QFileOpenEvent("/Users/a/hop dong.pdf")) is True
    assert c.handle(QEvent(QEvent.Type.Show)) is False
    assert c.take_pending() == ["/Users/a/hop dong.pdf"] and c.pending == []
    got = []
    c.handler = got.extend
    c.handle(QFileOpenEvent("/Users/a/b.docx"))
    assert got == ["/Users/a/b.docx"] and c.pending == []
    assert main.clean_args(["PdfKySo", "-psn_0_123456", "a.pdf"]) == ["PdfKySo", "a.pdf"]


# ------------------------------------------------------------------ đóng gói
def test_info_plist(tmp_path):
    p = tmp_path / "Info.plist"
    with open(p, "wb") as f:
        plistlib.dump({"CFBundleExecutable": "PdfKySo", "NuitkaKey": 1}, f)
    d = mac_bundle.patch_info_plist(str(p), "1.2.3")
    with open(p, "rb") as f:
        back = plistlib.load(f)
    assert back == d and back["NuitkaKey"] == 1
    assert back["CFBundleIdentifier"] == macintegration.BUNDLE_ID == mac_bundle.BUNDLE_ID
    assert back["CFBundleShortVersionString"] == "1.2.3" and back["LSMinimumSystemVersion"] == "11.0"
    assert back["NSAppleEventsUsageDescription"]
    utis = {u for t in back["CFBundleDocumentTypes"] for u in t["LSItemContentTypes"]}
    assert {"com.adobe.pdf", "org.openxmlformats.wordprocessingml.document",
            "org.openxmlformats.spreadsheetml.sheet", "public.png"} <= utis
    assert all(t["LSHandlerRank"] == "Alternate" for t in back["CFBundleDocumentTypes"])
    # mọi đuôi file phần mềm mở được đều khai báo cho Finder
    from app.office import OFFICE_EXT
    from main import OPEN_EXT
    exts = {e for t in back["CFBundleDocumentTypes"] for e in t["CFBundleTypeExtensions"]}
    assert {e.lstrip(".") for e in OFFICE_EXT + OPEN_EXT + (".pdf",)} <= exts


def test_entitlements_and_icns(tmp_path):
    e = tmp_path / "e.plist"
    mac_bundle.write_entitlements(str(e))
    with open(e, "rb") as f:
        d = plistlib.load(f)
    assert d["com.apple.security.cs.disable-library-validation"] is True       # driver token hãng khác ký
    assert d["com.apple.security.automation.apple-events"] is True
    out = mac_bundle.make_icns(os.path.join(ROOT, "assets", "app.png"), str(tmp_path / "a.icns"))
    assert open(out, "rb").read(4) == b"icns"
    assert os.path.isfile(os.path.join(ROOT, "assets", "app.icns"))


def test_installer_files():
    mac = os.path.join(ROOT, "installer", "mac")
    txt = open(os.path.join(mac, "pkg", "distribution.xml"), encoding="utf-8").read()
    xml.dom.minidom.parseString(txt.replace("@VERSION@", "1.0").replace("@ARCH@", "arm64").encode("utf-8"))
    for f in ("welcome.html", "conclusion.html", "background.png"):
        assert os.path.isfile(os.path.join(mac, "pkg", "resources", f))
    post = os.path.join(mac, "pkg", "scripts", "postinstall")
    assert open(post, encoding="utf-8").read().startswith("#!/bin/bash")
    guide = open(os.path.join(mac, "HUONG_DAN_CAI_MAC.txt"), encoding="utf-8").read()
    assert "Applications" in guide and "Vẫn mở" in guide
    sh = os.path.join(ROOT, "build_mac.sh")
    body = open(sh, encoding="utf-8").read()
    assert "keygen.py init" in body and "--selftest" in body and "notarytool" in body
    assert "keygen" not in body.split("nuitka main.py", 1)[1].split("--output-dir", 1)[0]  # không đóng gói keygen
    if sys.platform != "win32":
        subprocess.run(["bash", "-n", sh], check=True)
        subprocess.run(["bash", "-n", post], check=True)

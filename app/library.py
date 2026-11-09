"""Thư viện con dấu & chữ ký ảnh.

Lưu trong MỘT file (library.pdf) dạng PDF có file đính kèm:
- index.json : danh sách (id, tên, loại, cỡ mặc định mm)
- <id>.png   : ảnh RGBA đã tách nền
Khi đặt mật khẩu, file được mã hóa AES-256 (chuẩn PDF 2.0, qua pikepdf/qpdf) -> không cần cài thêm
thư viện mã hóa, và file vẫn mở kiểm tra được bằng phần mềm PDF thường nếu biết mật khẩu.
Ghi file theo kiểu an toàn: ghi ra file tạm rồi đổi tên, giữ 1 bản sao lưu (.bak).
"""
from __future__ import annotations

import csv
import json
import os
import shutil
import time
import uuid
from dataclasses import asdict, dataclass

STAMP, SIGNATURE = "stamp", "signature"
HAND, HANDSET = "hand", "handset"          # mẫu chữ viết tay (một cụm chữ) / bộ chữ tay (từ phiếu mẫu)
DEFAULT_WIDTH_MM = {STAMP: 38.0, SIGNATURE: 45.0, HAND: 50.0, HANDSET: 0.0}
KIND_LABEL = {STAMP: "Con dấu", SIGNATURE: "Chữ ký", HAND: "Chữ viết tay", HANDSET: "Bộ chữ tay"}
KINDS = [STAMP, SIGNATURE, HAND]           # loại chọn được khi nhập ảnh


def data_dir() -> str:
    from . import portable
    if portable.is_portable():                      # bản portable: dữ liệu nằm cạnh file .exe
        return portable.data_dir()
    from .osutil import roaming_base
    d = os.path.join(roaming_base(), "PdfKySo")
    os.makedirs(d, exist_ok=True)
    return d


class LibraryLocked(Exception):
    pass


@dataclass
class LibItem:
    id: str
    name: str
    kind: str = STAMP
    width_mm: float = 38.0
    created: float = 0.0


class Library:
    def __init__(self, path: str | None = None):
        self.path = path or os.path.join(data_dir(), "library.pdf")
        self.items: list[LibItem] = []
        self._images: dict[str, bytes] = {}
        self._password: str | None = None
        self.locked = False
        self.encrypted = False
        self.load()

    # ---------- đọc / ghi ----------
    def load(self, password: str | None = None):
        import pikepdf
        self.items, self._images = [], {}
        if not os.path.exists(self.path):
            self.locked = False
            self.encrypted = password is not None
            self._password = password
            return
        try:
            pdf = pikepdf.open(self.path, password=password or "")
        except pikepdf.PasswordError:
            self.locked, self.encrypted = True, True
            if password:
                raise LibraryLocked("Sai mật khẩu thư viện")
            return
        with pdf:
            self.encrypted = pdf.is_encrypted
            att = pdf.attachments
            if "index.json" in att:
                meta = json.loads(att["index.json"].get_file().read_bytes().decode("utf-8"))
                for d in meta.get("items", []):
                    it = LibItem(**d)
                    key = f"{it.id}.png"
                    if key in att:
                        self._images[it.id] = att[key].get_file().read_bytes()
                        self.items.append(it)
        self._password = password
        self.locked = False

    @classmethod
    def open_safe(cls, path: str | None = None) -> tuple["Library", str | None]:
        """Mở thư viện; nếu file hỏng thì cất file hỏng sang .hong và dùng bản sao lưu .bak."""
        try:
            return cls(path), None
        except Exception as e:
            lib = cls.__new__(cls)
            lib.path = path or os.path.join(data_dir(), "library.pdf")
            broken = lib.path + time.strftime(".hong-%Y%m%d%H%M%S")
            try:
                os.replace(lib.path, broken)
            except OSError:
                pass
            if os.path.exists(lib.path + ".bak"):
                shutil.copy2(lib.path + ".bak", lib.path)
            try:
                return cls(lib.path), f"File thư viện bị hỏng ({e}); đã khôi phục từ bản sao lưu gần nhất."
            except Exception:
                if os.path.exists(lib.path):
                    os.replace(lib.path, lib.path + ".hong-bak")
                return cls(lib.path), f"File thư viện bị hỏng ({e}); đã tạo thư viện mới, file cũ giữ ở {broken}."

    def unlock(self, password: str) -> bool:
        try:
            self.load(password)
            return True
        except LibraryLocked:
            return False

    def lock(self):
        """Khóa lại (xóa ảnh khỏi bộ nhớ). Chỉ có tác dụng khi thư viện có mật khẩu."""
        if self.encrypted:
            self.items, self._images, self._password = [], {}, None
            self.locked = True

    def _require_open(self):
        if self.locked:
            raise LibraryLocked("Thư viện đang khóa bằng mật khẩu")

    def save(self):
        import pikepdf
        self._require_open()
        pdf = pikepdf.new()
        pdf.add_blank_page(page_size=(200, 200))
        index = {"version": 1, "items": [asdict(it) for it in self.items]}
        pdf.attachments["index.json"] = pikepdf.AttachedFileSpec(
            pdf, json.dumps(index, ensure_ascii=False).encode("utf-8"), mime_type="application/json")
        for it in self.items:
            pdf.attachments[f"{it.id}.png"] = pikepdf.AttachedFileSpec(pdf, self._images[it.id],
                                                                       mime_type="image/png")
        enc = None
        if self._password:
            enc = pikepdf.Encryption(owner=self._password, user=self._password, R=6,
                                     allow=pikepdf.Permissions(extract=False, modify_other=False))
        tmp = self.path + ".tmp"
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        pdf.save(tmp, encryption=enc if enc else False)
        pdf.close()
        if os.path.exists(self.path):
            shutil.copy2(self.path, self.path + ".bak")
        os.replace(tmp, self.path)
        self.encrypted = bool(self._password)

    def set_password(self, new_password: str | None):
        """Đặt / đổi / bỏ mật khẩu (None hoặc rỗng = bỏ)."""
        self._require_open()
        self._password = new_password or None
        self.save()

    # ---------- thao tác ----------
    def add(self, name: str, png: bytes, kind: str = STAMP, width_mm: float | None = None) -> LibItem:
        self._require_open()
        it = LibItem(uuid.uuid4().hex[:12], name.strip() or "Không tên", kind,
                     width_mm or DEFAULT_WIDTH_MM.get(kind, 40.0), time.time())
        self.items.append(it)
        self._images[it.id] = png
        self.save()
        return it

    def remove(self, item_id: str):
        self._require_open()
        self.items = [it for it in self.items if it.id != item_id]
        self._images.pop(item_id, None)
        self.save()

    def update(self, item_id: str, **kw):
        self._require_open()
        it = self.get(item_id)
        for k, v in kw.items():
            setattr(it, k, v)
        self.save()

    def move(self, item_id: str, delta: int):
        self._require_open()
        i = next(k for k, it in enumerate(self.items) if it.id == item_id)
        j = max(0, min(len(self.items) - 1, i + delta))
        self.items.insert(j, self.items.pop(i))
        self.save()

    def get(self, item_id: str) -> LibItem:
        return next(it for it in self.items if it.id == item_id)

    def image(self, item_id: str) -> bytes:
        self._require_open()
        return self._images[item_id]

    def of_kind(self, kind: str | None = None) -> list[LibItem]:
        return [it for it in self.items if kind is None or it.kind == kind]


# ---------- nhật ký dùng dấu ----------
USAGE_LOG_ENABLED = True          # tắt khi người dùng đặt thời hạn "Không lưu" cho nhật ký dùng dấu


def log_usage(item: LibItem, document: str, pages: list[int], action: str = "đóng dấu",
              path: str | None = None):
    if not USAGE_LOG_ENABLED and path is None:
        return
    path = path or os.path.join(data_dir(), "nhat_ky_dung_dau.csv")
    new = not os.path.exists(path)
    with open(path, "a", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["Thời gian", "Người dùng máy", "Hành động", "Mẫu", "Loại", "Tài liệu", "Trang"])
        w.writerow([time.strftime("%Y-%m-%d %H:%M:%S"), os.environ.get("USERNAME") or os.environ.get("USER", ""),
                    action, item.name, KIND_LABEL.get(item.kind, item.kind), document,
                    ", ".join(str(p + 1) for p in pages)])


__all__ = ["Library", "LibItem", "LibraryLocked", "STAMP", "SIGNATURE", "log_usage", "data_dir"]

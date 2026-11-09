"""Thư mục tự xử lý: thả file PDF vào thư mục -> phần mềm tự đóng dấu chữ, nén, bảo vệ, rồi đặt bản kết quả
vào thư mục con "da_xu_ly". File gốc giữ nguyên. Chạy khi phần mềm đang mở.

(Không tự ký số: ký số cần người dùng nhập PIN / cắm token – dùng "Ký hàng loạt".)"""
from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass, field

OUT_DIR = "da_xu_ly"


@dataclass
class AutoConfig:
    folder: str = ""
    enabled: bool = False
    stamp_text: str = ""              # trống = không đóng dấu chữ
    stamp_style: str = "box"
    compress_mb: float = 0.0          # 0 = không nén
    protect: dict = field(default_factory=dict)     # ProtectOptions.to_dict(); trống = không bảo vệ
    owner_password: str = ""          # lưu cùng cấu hình (máy của người dùng) để còn gỡ bảo vệ/ký sau

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)

    @classmethod
    def from_json(cls, s: str | None) -> "AutoConfig":
        try:
            d = json.loads(s or "{}")
            return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})
        except (TypeError, ValueError):
            return cls()

    def summary(self) -> str:
        acts = []
        if self.stamp_text:
            acts.append(f"đóng dấu chữ “{self.stamp_text}”")
        if self.compress_mb:
            acts.append(f"nén ≤ {self.compress_mb:g} MB")
        if self.protect:
            acts.append("bảo vệ")
        return ", ".join(acts) or "chưa chọn thao tác"


def process_file(path: str, cfg: AutoConfig) -> str:
    from . import protect, tools
    from .document import PdfDocument
    with open(path, "rb") as f:
        head = f.read()
    if b"/ByteRange" in head and b"/Sig" in head:
        raise ValueError("file đã có chữ ký số – bỏ qua để không làm chữ ký mất hiệu lực (xử lý tay nếu cần)")
    d = PdfDocument(path)
    try:
        if cfg.stamp_text:
            tools.text_stamp(d, list(range(d.page_count)), cfg.stamp_text, cfg.stamp_style)
        data = d.to_bytes()
    finally:
        d.close()
    if cfg.compress_mb:
        data, _ = tools.compress_to_size(data, int(cfg.compress_mb * 1024 * 1024))
    if cfg.protect:
        opts = protect.ProtectOptions.from_dict(cfg.protect)
        opts.owner_password = cfg.owner_password or opts.owner_password
        data, _ = protect.protect_pdf(data, opts)
    out_dir = os.path.join(os.path.dirname(path), OUT_DIR)
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, os.path.basename(path))
    tmp = out + ".tmp"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, out)
    return out


class Watcher:
    """Quét thư mục định kỳ (nhẹ, không cần dịch vụ nền). Chỉ xử lý file đã ghi xong (kích thước ổn định)."""

    def __init__(self, cfg: AutoConfig, state_path: str | None = None, on_done=None, on_error=None):
        self.cfg = cfg
        self.state_path = state_path or os.path.join(cfg.folder, OUT_DIR, ".da_xu_ly.json")
        self.on_done = on_done
        self.on_error = on_error
        self._sizes: dict[str, int] = {}
        self._done = self._load()

    def _load(self) -> dict:
        try:
            with open(self.state_path, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def _save(self):
        os.makedirs(os.path.dirname(self.state_path), exist_ok=True)
        with open(self.state_path, "w", encoding="utf-8") as f:
            json.dump(self._done, f, ensure_ascii=False)

    def scan(self) -> list[str]:
        if not (self.cfg.enabled and self.cfg.folder and os.path.isdir(self.cfg.folder)):
            return []
        out = []
        for name in sorted(os.listdir(self.cfg.folder)):
            p = os.path.join(self.cfg.folder, name)
            if not name.lower().endswith(".pdf") or not os.path.isfile(p):
                continue
            st = os.stat(p)
            key = f"{st.st_size}:{int(st.st_mtime)}"
            if self._done.get(name) == key:
                continue
            if self._sizes.get(p) != st.st_size or time.time() - st.st_mtime < 1.0:
                self._sizes[p] = st.st_size       # đang ghi dở -> đợi lượt sau
                continue
            try:
                res = process_file(p, self.cfg)
                out.append(res)
                if self.on_done:
                    self.on_done(p, res)
            except Exception as e:
                if self.on_error:
                    self.on_error(p, e)
            self._done[name] = key
            self._sizes.pop(p, None)
        if out or self._done:
            self._save()
        return out

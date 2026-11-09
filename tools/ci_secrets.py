"""GitHub Actions: nạp khóa bản quyền / thương hiệu / bộ cài THẬT từ GitHub Secrets (không để trong kho mã).

Secrets (Settings -> Secrets and variables -> Actions), giá trị là NỘI DUNG FILE mã hóa base64:
  PDFKYSO_LICENSE_KEY_PY  -> app/license_key.py   (khóa công khai thật, DEMO = False)
  PDFKYSO_BRANDING_PY     -> app/branding.py      (tên công ty, điện thoại, email...)
  PDFKYSO_SETUP_ISS       -> installer/setup.iss  (AppPublisher, URL...)
Tạo base64 trên Windows (PowerShell):  [Convert]::ToBase64String([IO.File]::ReadAllBytes("app\\license_key.py"))
Không có secret nào -> build bản dùng KHÓA MẪU để thử (không bán được).
Có khóa thật -> đặt PDFKYSO_RELEASE=1 (build dừng nếu lỡ còn khóa mẫu)."""
import base64
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FILES = {"PDFKYSO_LICENSE_KEY_PY": "app/license_key.py", "PDFKYSO_BRANDING_PY": "app/branding.py",
         "PDFKYSO_SETUP_ISS": "installer/setup.iss"}


def main() -> int:
    got = []
    for env, rel in FILES.items():
        val = (os.environ.get(env) or "").strip()
        if not val:
            continue
        try:
            data = base64.b64decode(val, validate=True)
        except Exception:
            print(f"LOI: secret {env} khong phai base64 hop le")
            return 1
        with open(os.path.join(ROOT, rel), "wb") as f:
            f.write(data)
        got.append(rel)
        print(f"Da nap {rel} tu secret {env} ({len(data)} byte)")
    if "app/license_key.py" in got:
        gh = os.environ.get("GITHUB_ENV")
        if gh:
            with open(gh, "a", encoding="utf-8") as f:
                f.write("PDFKYSO_RELEASE=1\n")
        print("Ban ban (PDFKYSO_RELEASE=1)")
    else:
        print("Khong co secret khoa that -> dong goi ban dung KHOA MAU (chi de thu, khong ban cho khach).")
    return 0


if __name__ == "__main__":
    sys.exit(main())

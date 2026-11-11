"""Giao diện "Ấn triện": mực xanh đêm, đỏ son con dấu, nền giấy. Bảng màu sáng/tối + stylesheet Qt + phông."""
import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFontDatabase, QGuiApplication, QPalette

LIGHT = {
    "bg": "#F3F0E8", "bar": "#ECE8DE", "card": "#FFFFFF", "card2": "#FAF8F3",
    "stroke": "#E3DED3", "strong": "#B9B2A3", "text": "#182033", "text2": "#4A5163",
    "accent": "#B8322A", "accent2": "#9E2A23", "onaccent": "#FFFFFF", "hover": "#F1EDE4", "press": "#E8E3D8",
    "sel": "#FBE7E4", "canvas": "#E6E1D6",
    "rail": "#16203A", "railtext": "#AEB6C9", "railsel": "#2A3658", "railmark": "#E0473C",
    "cert": "#16203A", "certtext": "#EEF0F6", "ok": "#1F7A5A", "warn": "#7A4A00",
}
DARK = {
    "bg": "#12182A", "bar": "#0F1424", "card": "#1C2438", "card2": "#182033",
    "stroke": "#2C3652", "strong": "#56607C", "text": "#EEF0F6", "text2": "#B4BBCB",
    "accent": "#E0584D", "accent2": "#C9483E", "onaccent": "#FFFFFF", "hover": "#243049", "press": "#2C3858",
    "sel": "#3A2230", "canvas": "#0E1322",
    "rail": "#0B1020", "railtext": "#8F99B3", "railsel": "#1E2945", "railmark": "#E0584D",
    "cert": "#202B4D", "certtext": "#EEF0F6", "ok": "#4CC08F", "warn": "#E6B34D",
}

# nền nhạt / màu nét cho ô công cụ theo nhóm màu
TILES_LIGHT = {"red": ("#FBE7E4", "#B8322A"), "blue": ("#E4E9F6", "#24407E"), "green": ("#E3F1EB", "#1F7A5A"),
               "violet": ("#EEE6F7", "#5B3A94"), "amber": ("#FDF1D8", "#7A4A00"), "gray": ("#EFECE5", "#4A5163")}
TILES_DARK = {"red": ("#3A2230", "#F08A80"), "blue": ("#1F2B4A", "#9DB4F0"), "green": ("#16332B", "#6FD3A8"),
              "violet": ("#2C2445", "#C3A8F0"), "amber": ("#382C16", "#F0C46F"), "gray": ("#263048", "#C4CADA")}

FONT_FAMILY = "Be Vietnam Pro"
_fonts_loaded = None


def tiles(c: dict) -> dict:
    return TILES_DARK if c is DARK else TILES_LIGHT


def load_fonts() -> str:
    """Nạp phông giao diện Be Vietnam Pro đi kèm (OFL). Trả về tên họ phông dùng được."""
    global _fonts_loaded
    if _fonts_loaded is not None:
        return _fonts_loaded
    from .fonts import assets_dir
    d = os.path.join(assets_dir(), "fonts", "ui")
    fam = ""
    if os.path.isdir(d):
        for f in sorted(os.listdir(d)):
            if f.lower().endswith(".ttf"):
                i = QFontDatabase.addApplicationFont(os.path.join(d, f))
                if i >= 0 and not fam:
                    fams = QFontDatabase.applicationFontFamilies(i)
                    fam = fams[0] if fams else ""
    _fonts_loaded = fam or "Segoe UI"
    return _fonts_loaded


def _arrows(color: str) -> tuple[str, str]:
    """File SVG mũi tên cho QComboBox/QSpinBox (stylesheet Qt chỉ nhận ảnh từ file)."""
    import tempfile
    d = os.path.join(tempfile.gettempdir(), "pdfkyso-ui")
    os.makedirs(d, exist_ok=True)
    out = []
    for name, path in (("down", "M3 5.5 8 10.5l5-5"), ("up", "M3 10.5 8 5.5l5 5")):
        f = os.path.join(d, f"{name}_{color.lstrip('#')}.svg")
        if not os.path.exists(f):
            with open(f, "w", encoding="utf-8") as fh:
                fh.write(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16"><path d="{path}" fill="none" '
                         f'stroke="{color}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>')
        out.append(f.replace("\\", "/"))
    return out[0], out[1]


def system_is_dark() -> bool:
    try:
        return QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark
    except Exception:  # Qt < 6.5
        return False


def ui_is_dark() -> bool:
    """Giao diện đang dùng là tối? (theo bảng màu đã áp cho ứng dụng – đúng cả khi người dùng tự đổi sáng/tối)."""
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance()
    if app is None:
        return False
    return app.palette().color(QPalette.Window).lightness() < 128


def ui_color(name: str) -> str:
    """Màu giao diện hiện tại ("text", "text2", "card"...) cho các hình vẽ tự tô (biểu tượng hình, bút, nhãn)."""
    return (DARK if ui_is_dark() else LIGHT).get(name, "#808080")


def resolve(pref: str) -> dict:
    """pref: 'system' | 'light' | 'dark'."""
    dark = system_is_dark() if pref == "system" else pref == "dark"
    return DARK if dark else LIGHT


def stylesheet(c: dict) -> str:
    fam = load_fonts() if QGuiApplication.instance() else FONT_FAMILY
    try:
        down, up = _arrows(c["text2"])
    except OSError:
        down = up = ""
    return f"""
* {{ font-family: "{fam}", "Segoe UI Variable Text", "Segoe UI", sans-serif; font-size: 13px; font-weight: 300;
  color: {c['text']}; }}
QMainWindow, QWidget#root, QDialog {{ background: {c['bg']}; }}
QToolTip {{ background: {c['rail']}; color: #FFFFFF; border: 0; padding: 5px 9px; border-radius: 6px; }}

/* ---- thanh điều hướng trái ---- */
QFrame#rail {{ background: {c['rail']}; border: 0; }}
QLabel#raillogo {{ background: transparent; }}
QToolButton#pivot {{ border: 0; border-radius: 7px; padding: 4px 0 3px 0; margin: 0 2px;
  color: {c['railtext']}; background: transparent; font-size: 10px; font-weight: 400; }}
QToolButton#pivot:hover {{ background: {c['railsel']}; color: #FFFFFF; }}
QToolButton#pivot:checked {{ background: {c['railsel']}; color: #FFFFFF;
  border-left: 2px solid {c['railmark']}; }}
QToolButton#railbtn {{ border: 0; border-radius: 9px; padding: 6px; margin: 0 5px; background: transparent; }}
QToolButton#railbtn:hover {{ background: {c['railsel']}; }}

/* ---- hàng tiêu đề ---- */
QFrame#topbar {{ background: {c['bg']}; border: 0; }}
QLabel#title {{ font-size: 18px; font-weight: 700; }}
QLabel#chip {{ background: {c['sel']}; color: {c['accent']}; border-radius: 12px; padding: 4px 12px;
  font-size: 12px; font-weight: 500; }}
QLabel#chip[state="ok"] {{ background: {tiles(c)['green'][0]}; color: {tiles(c)['green'][1]}; }}
QLabel#chip[state="warn"] {{ background: {tiles(c)['amber'][0]}; color: {tiles(c)['amber'][1]}; }}
QToolButton#flat {{ border: 1px solid {c['stroke']}; border-radius: 8px; padding: 4px; background: {c['card']}; }}
QToolButton#flat:hover {{ background: {c['hover']}; }}
QToolButton#flat:checked {{ background: {c['sel']}; border-color: {c['accent']}; }}

/* ---- tab file ---- */
QTabBar {{ background: {c['bg']}; qproperty-drawBase: 0; border: 0; }}
QToolButton#tabclose {{ border: 0; border-radius: 4px; padding: 2px; background: transparent; }}
QToolButton#tabclose:hover {{ background: {c['hover']}; }}
QTabBar::tab {{ background: {c['hover']}; padding: 2px 6px 2px 10px; margin: 2px 0 0 1px; border: 1px solid {c['stroke']};
  border-bottom: 0; border-top-left-radius: 7px; border-top-right-radius: 7px; min-width: 140px; max-width: 230px;
  color: {c['text2']}; font-size: 12px; font-weight: 300; }}
QTabBar::tab:selected {{ background: {c['card']}; color: {c['text']}; margin-top: 1px;
  border-top: 2px solid {c['accent']}; }}
QTabBar QToolButton {{ background: {c['card']}; border: 1px solid {c['stroke']}; border-radius: 4px; margin: 2px 0; }}
QToolButton#tablist {{ border: 1px solid {c['stroke']}; border-radius: 5px; padding: 0 2px; margin: 2px 4px 0 2px;
  background: {c['card']}; color: {c['text']}; font-size: 11px; }}
QToolButton#tablist::menu-indicator {{ image: none; width: 0; }}
QToolButton#tablist:hover {{ background: {c['hover']}; }}
QTabBar::tab:hover:!selected {{ background: {c['card']}; color: {c['text']}; }}
QTabWidget::pane {{ border-top: 1px solid {c['stroke']}; }}
QToolButton#starttab {{ background: {c['hover']}; border: 1px solid {c['stroke']}; border-bottom: 0;
  border-top-left-radius: 7px; border-top-right-radius: 7px; padding: 2px 10px; margin: 2px 0 0 6px;
  color: {c['text2']}; font-size: 12px; font-weight: 300; }}
QToolButton#starttab:hover {{ background: {c['card']}; color: {c['text']}; }}
QToolButton#starttab:checked {{ background: {c['card']}; color: {c['text']};
  border-top: 2px solid {c['accent']}; }}

/* ---- dải cảnh báo trên tài liệu ---- */
QFrame#banner {{ border: 0; border-bottom: 1px solid {c['stroke']}; background: {tiles(c)['amber'][0]}; }}
QFrame#banner[level="danger"] {{ background: {tiles(c)['red'][0]}; }}
QFrame#banner[level="info"] {{ background: {tiles(c)['blue'][0]}; }}
QLabel#bannericon {{ font-size: 18px; background: transparent; color: {tiles(c)['amber'][1]}; }}
QFrame#banner[level="danger"] QLabel#bannericon {{ color: {tiles(c)['red'][1]}; }}
QFrame#banner[level="info"] QLabel#bannericon {{ color: {tiles(c)['blue'][1]}; }}
QLabel#bannertext {{ background: transparent; font-size: 12px; }}
QPushButton#bannerbtn {{ padding: 4px 10px; font-size: 12px; }}
QToolButton#bannerclose {{ border: 0; background: transparent; padding: 2px 4px; }}

/* ---- dải công cụ ---- */
QFrame#ribbon {{ background: {c['card']}; border: 1px solid {c['stroke']}; border-radius: 7px; }}
QFrame#toolbar {{ background: transparent; border: 0; }}
QToolButton#tool {{ border: 1px solid transparent; border-radius: 6px; padding: 1px 3px;
  font-size: 11px; font-weight: 400; background: transparent; color: {c['text']}; }}
QToolButton#tool:hover {{ background: {c['hover']}; border-color: {c['stroke']}; }}
QToolButton#tool:pressed {{ background: {c['press']}; }}
QToolButton#tool[primary="true"] {{ background: {c['accent']}; color: {c['onaccent']}; border-radius: 12px;
  padding: 4px 12px; font-size: 12px; font-weight: 600; }}
QToolButton#tool[primary="true"]:hover {{ background: {c['accent2']}; }}
QFrame#vsep {{ background: {c['stroke']}; max-width: 1px; min-width: 1px; margin: 6px 4px; }}
QSplitter#docsplit::handle {{ background: transparent; border-left: 1px solid {c['stroke']}; margin: 0; }}
QSplitter#docsplit::handle:hover {{ background: {c['accent']}; }}
QFrame#quickrow {{ background: {c['bg']}; border: 0; }}
QToolButton#qa {{ border: 0; border-radius: 5px; padding: 0; margin: 0; background: transparent; }}
QToolButton#qa:hover {{ background: {c['hover']}; }}
QToolButton#qa:disabled {{ background: transparent; }}
QToolButton#modetab {{ border: 0; border-bottom: 2px solid transparent; padding: 4px 8px 3px 8px;
  background: transparent; color: {c['text2']}; font-size: 12px; font-weight: 500; }}
QToolButton#modetab:hover {{ color: {c['text']}; background: {c['hover']}; border-radius: 5px; }}
QToolButton#modetab:checked {{ color: {c['accent']}; border-bottom: 2px solid {c['accent']}; }}
QToolButton#stripbtn {{ border: 1px solid {c['strong']}; border-radius: 5px; padding: 1px; background: {c['hover']}; }}
QToolButton#stripbtn:hover {{ background: {c['sel']}; border-color: {c['accent']}; }}
QToolButton#edgebtn {{ border: 1px solid {c['strong']}; border-radius: 4px; padding: 0; background: {c['hover']};
  color: {c['text']}; font-size: 15px; font-weight: 600; }}
QToolButton#edgebtn:hover {{ background: {c['accent']}; border-color: {c['accent']}; color: {c['onaccent']}; }}
QToolButton#striphandle {{ border: 1px solid {c['strong']}; border-radius: 6px;
  padding: 1px 10px; font-size: 11px; font-weight: 500; background: {c['hover']}; color: {c['text']}; }}
QToolButton#striphandle:hover {{ background: {c['hover']}; }}

/* ---- vùng xem, thumbnail ---- */
QScrollArea#viewer, QWidget#pages {{ background: {c['canvas']}; border: 0; }}
QListWidget#thumbs {{ background: {c['bg']}; border: 0; outline: 0; }}
QListWidget#thumbs::item {{ border-radius: 8px; padding: 6px; color: {c['text2']}; }}
QListWidget#thumbs::item:selected {{ background: {c['sel']}; color: {c['accent']}; }}
QListWidget#thumbs::item:hover:!selected {{ background: {c['hover']}; }}

/* ---- bảng bên phải ---- */
QFrame#side {{ background: {c['bg']}; border-left: 1px solid {c['stroke']}; }}
QScrollArea#sidescroll, QWidget#sideinner {{ background: {c['bg']}; border: 0; }}
QFrame#card {{ background: {c['card']}; border: 1px solid {c['stroke']}; border-radius: 10px; }}
QFrame#cert {{ background: {c['cert']}; border: 0; border-radius: 10px; }}
QFrame#cert QLabel {{ color: {c['certtext']}; background: transparent; }}
QFrame#cert QLabel#certcap {{ color: #AEB6C9; font-size: 10px; font-weight: 600; letter-spacing: 1px; }}
QFrame#cert QLabel#certname {{ font-size: 14px; font-weight: 600; }}
QFrame#cert QLabel#certsub {{ color: #AEB6C9; font-size: 11px; }}
QFrame#cert QPushButton {{ background: #2A3658; color: #FFFFFF; border: 0; border-radius: 8px; padding: 5px 10px;
  font-size: 12px; }}
QFrame#cert QPushButton:hover {{ background: #34426B; }}
QLabel#h {{ font-weight: 600; }}
QLabel#cap {{ color: {c['text2']}; font-size: 10px; font-weight: 600; letter-spacing: 1px; }}
QLabel#lbl {{ color: {c['text2']}; font-size: 12px; }}
QLabel#badge {{ background: {c['sel']}; color: {c['accent']}; border-radius: 10px; padding: 2px 9px;
  font-size: 11px; font-weight: 500; }}

/* ---- trang bắt đầu ---- */
QScrollArea#start {{ background: {c['bg']}; border: 0; }}
QLabel#hero {{ font-size: 26px; font-weight: 700; }}
QFrame#drop {{ background: {c['rail']}; border-radius: 18px; }}
QFrame#drop QLabel {{ color: #FFFFFF; background: transparent; }}
QFrame#drop QLabel#dropsub {{ color: #AEB6C9; }}
QFrame#drop QPushButton {{ background: {c['accent']}; color: #FFFFFF; border: 0; border-radius: 10px;
  padding: 9px 20px; font-weight: 600; }}
QFrame#drop QPushButton:hover {{ background: {c['accent2']}; }}
QToolButton#quick {{ background: {c['card']}; border: 1px solid {c['stroke']}; border-radius: 14px;
  padding: 12px 8px; font-weight: 500; }}
QToolButton#quick:hover {{ border-color: {c['accent']}; background: {c['card2']}; }}
QPushButton#link {{ background: transparent; border: 0; padding: 0 2px; color: {c['accent']}; font-size: 12px;
  font-weight: 500; }}
QPushButton#link:hover {{ text-decoration: underline; background: transparent; }}
QListWidget#recent {{ background: {c['card']}; border: 1px solid {c['stroke']}; border-radius: 14px; outline: 0;
  padding: 6px; }}
QListWidget#recent::item {{ border-radius: 8px; padding: 8px 10px; }}
QListWidget#recent::item:hover {{ background: {c['hover']}; }}
QListWidget#recent::item:selected {{ background: {c['sel']}; color: {c['text']}; }}

/* ---- thanh trạng thái ---- */
QStatusBar {{ background: {c['card']}; border-top: 1px solid {c['stroke']}; }}
QStatusBar QLabel {{ color: {c['text2']}; font-size: 12px; padding: 0 6px; }}
QStatusBar QToolButton {{ border: 0; border-radius: 6px; padding: 3px; background: transparent; }}
QStatusBar QToolButton:hover {{ background: {c['hover']}; }}
QLineEdit#pagebox {{ background: {c['card2']}; border: 1px solid {c['stroke']}; border-radius: 6px;
  padding: 1px 4px; }}
QSlider::groove:horizontal {{ height: 2px; background: {c['stroke']}; border-radius: 1px; }}
QSlider::sub-page:horizontal {{ background: {c['accent']}; border-radius: 1px; }}
QSlider::handle:horizontal {{ width: 12px; height: 12px; margin: -6px 0; border-radius: 6px;
  background: {c['card']}; border: 2px solid {c['accent']}; }}

/* ---- điều khiển chung ---- */
/* chữ đậm hơn ở trạng thái mặc định / đang chọn làm chữ dài ra mà khung nút không nở theo -> bị cắt chữ;
   nên mọi trạng thái giữ CÙNG độ đậm, chỉ đổi màu nền / viền */
QPushButton {{ background: {c['card']}; border: 1px solid {c['stroke']}; border-radius: 8px; padding: 6px 14px;
  font-weight: 400; }}
QPushButton:hover {{ background: {c['hover']}; }}
QPushButton:disabled {{ color: {c['strong']}; }}
QPushButton:default, QPushButton[accent="true"] {{ background: {c['accent']}; color: {c['onaccent']};
  border-color: {c['accent']}; }}
QPushButton:default:hover, QPushButton[accent="true"]:hover {{ background: {c['accent2']}; }}
QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {{ background: {c['card']};
  border: 1px solid {c['stroke']}; border-radius: 8px; padding: 4px 8px; }}
QLineEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{
  border: 1px solid {c['accent']}; }}
QComboBox::drop-down {{ subcontrol-origin: padding; subcontrol-position: center right; width: 22px; border: 0; }}
QComboBox::down-arrow {{ image: url("{down}"); width: 12px; height: 12px; }}
QComboBox QAbstractItemView {{ background: {c['card']}; border: 1px solid {c['stroke']}; border-radius: 8px;
  selection-background-color: {c['sel']}; selection-color: {c['text']}; outline: 0; padding: 4px; }}
QSpinBox, QDoubleSpinBox {{ padding-right: 20px; }}
QSpinBox::up-button, QDoubleSpinBox::up-button {{ subcontrol-origin: border; subcontrol-position: top right;
  width: 18px; border: 0; background: transparent; }}
QSpinBox::down-button, QDoubleSpinBox::down-button {{ subcontrol-origin: border; subcontrol-position: bottom right;
  width: 18px; border: 0; background: transparent; }}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{ image: url("{up}"); width: 10px; height: 10px; }}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{ image: url("{down}"); width: 10px; height: 10px; }}
QLineEdit#search {{ border-radius: 14px; padding: 4px 12px; background: {c['card']}; }}
QCheckBox::indicator:checked, QRadioButton::indicator:checked {{ background: {c['accent']}; border: 1px solid {c['accent']}; }}
QCheckBox::indicator, QRadioButton::indicator {{ width: 14px; height: 14px; border: 1px solid {c['strong']};
  background: {c['card']}; border-radius: 4px; }}
QRadioButton::indicator {{ border-radius: 8px; }}
QGroupBox {{ border: 1px solid {c['stroke']}; border-radius: 10px; margin-top: 10px; padding-top: 8px; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; font-weight: 500; }}
QMenu {{ background: {c['card']}; border: 1px solid {c['stroke']}; border-radius: 10px; padding: 4px; }}
QMenu::item {{ padding: 6px 24px 6px 12px; border-radius: 6px; }}
QMenu::item:selected {{ background: {c['sel']}; color: {c['text']}; }}
QMenu::separator {{ height: 1px; background: {c['stroke']}; margin: 4px 8px; }}
QScrollBar:vertical {{ width: 10px; background: transparent; }}
QScrollBar::handle:vertical {{ background: {c['strong']}; border-radius: 3px; min-height: 30px; margin: 2px; }}
QScrollBar:horizontal {{ height: 10px; background: transparent; }}
QScrollBar::handle:horizontal {{ background: {c['strong']}; border-radius: 3px; min-width: 30px; margin: 2px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
"""


def palette(c: dict) -> QPalette:
    p = QPalette()
    for role, key in ((QPalette.Window, "bg"), (QPalette.Base, "card"), (QPalette.AlternateBase, "card2"),
                      (QPalette.Text, "text"), (QPalette.WindowText, "text"), (QPalette.Button, "card"),
                      (QPalette.ButtonText, "text"), (QPalette.Highlight, "accent"),
                      (QPalette.HighlightedText, "onaccent"), (QPalette.PlaceholderText, "strong"),
                      (QPalette.ToolTipBase, "rail")):
        p.setColor(role, QColor(c[key]))
    p.setColor(QPalette.ToolTipText, QColor("#FFFFFF"))
    return p

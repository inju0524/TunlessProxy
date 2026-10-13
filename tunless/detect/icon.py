"""图标提取：从 exe/dll 里取出图标并保存成 PNG，供 GUI 使用。

实现要点（都踩过坑，别改）：
  * `win32gui.ExtractIconEx` 支持 `imageres.dll,-114` 这种带索引的形式；
  * 拿到的 HICON 用 `GetIconInfo` 取出**图标自己的位图**，再 `GetDIBits` 成 32bpp，
    这样 alpha 通道是完整的（直接往 DC 上 DrawIconEx 会把透明区合成成黑色）；
  * pywin32 返回的是 `PyHANDLE`，且值是符号扩展过的 32 位句柄 —— 传给 ctypes
    必须 `int(h) & 0xFFFFFFFF`，且**不能**自己 DeleteObject（PyHANDLE 析构时会删）；
  * 先空跑一次 GetDIBits 拿到位图真实尺寸，否则 32x32 的图标会被按 48x48 读出乱码。
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import os
import re
from pathlib import Path

_INDEX_RE = re.compile(r"^(?P<path>.+?)(?:,(?P<index>-?\d+))?$")

_gdi32 = ctypes.WinDLL("gdi32")
_user32 = ctypes.WinDLL("user32")
_gdi32.GetDIBits.restype = ctypes.c_int
_gdi32.GetDIBits.argtypes = [
    ctypes.c_void_p, ctypes.c_void_p, wt.UINT, wt.UINT,
    ctypes.c_void_p, ctypes.c_void_p, wt.UINT,
]
_gdi32.DeleteObject.argtypes = [ctypes.c_void_p]
_user32.GetDC.restype = ctypes.c_void_p
_user32.GetDC.argtypes = [ctypes.c_void_p]
_user32.ReleaseDC.argtypes = [ctypes.c_void_p, ctypes.c_void_p]

BI_RGB = 0


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wt.DWORD), ("biWidth", wt.LONG), ("biHeight", wt.LONG),
        ("biPlanes", wt.WORD), ("biBitCount", wt.WORD), ("biCompression", wt.DWORD),
        ("biSizeImage", wt.DWORD), ("biXPelsPerMeter", wt.LONG),
        ("biYPelsPerMeter", wt.LONG), ("biClrUsed", wt.DWORD), ("biClrImportant", wt.DWORD),
    ]


class _BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", _BITMAPINFOHEADER), ("bmiColors", wt.DWORD * 3)]


def parse_icon_source(source: str) -> tuple[str, int]:
    """把 `C:\\a\\b.exe,0` / `%windir%\\system32\\imageres.dll,-114` 拆成 (路径, 索引)。"""
    if not source:
        return "", 0
    text = os.path.expandvars(source.strip().strip('"'))
    match = _INDEX_RE.match(text)
    if not match:
        return text, 0
    path = match.group("path") or ""
    try:
        index = int(match.group("index") or 0)
    except (TypeError, ValueError):
        index = 0
    return path, index


def _as_handle(value) -> ctypes.c_void_p:
    return ctypes.c_void_p(int(value) & 0xFFFFFFFF)


def _hicon_to_qimage(hicon: int):
    """HICON -> QImage（保留 alpha）。失败返回 None。"""
    import win32gui  # type: ignore
    from PyQt6.QtGui import QImage

    try:
        _f_icon, _xhot, _yhot, hbm_mask, hbm_color = win32gui.GetIconInfo(hicon)
    except Exception:
        return None

    hbmp = hbm_color if int(hbm_color or 0) else hbm_mask
    if not hbmp or not int(hbmp):
        return None

    bmi = _BITMAPINFO()
    bmi.bmiHeader.biSize = ctypes.sizeof(_BITMAPINFOHEADER)

    hdc = _user32.GetDC(None)
    try:
        # 第一次空跑：拿位图真实尺寸
        if _gdi32.GetDIBits(hdc, _as_handle(hbmp), 0, 0, None, ctypes.byref(bmi), BI_RGB) == 0:
            return None
        width = int(bmi.bmiHeader.biWidth)
        height = abs(int(bmi.bmiHeader.biHeight))
        if width <= 0 or height <= 0 or width > 512 or height > 512:
            return None

        bmi.bmiHeader.biWidth = width
        bmi.bmiHeader.biHeight = -height  # 负数 = 自顶向下
        bmi.bmiHeader.biPlanes = 1
        bmi.bmiHeader.biBitCount = 32
        bmi.bmiHeader.biCompression = BI_RGB
        bmi.bmiHeader.biSizeImage = width * height * 4

        buffer = ctypes.create_string_buffer(width * height * 4)
        lines = _gdi32.GetDIBits(
            hdc, _as_handle(hbmp), 0, height, buffer, ctypes.byref(bmi), BI_RGB
        )
        if lines <= 0:
            return None
        image = QImage(
            buffer.raw, width, height, width * 4, QImage.Format.Format_ARGB32
        ).copy()
        return image
    finally:
        _user32.ReleaseDC(None, hdc)


def png_to_ico(png_path: Path, ico_path: Path) -> bool:
    """把缓存的 PNG 转成 .ico。

    快捷方式的 IconLocation 指 PNG 时 Explorer 经常不认，指 .ico 才稳。
    """
    try:
        from PyQt6.QtGui import QImage

        image = QImage(str(png_path))
        if image.isNull():
            return False
        ico_path.parent.mkdir(parents=True, exist_ok=True)
        return bool(image.save(str(ico_path), "ICO"))
    except Exception:
        return False


def extract_icon(source: str, out_path: Path, size: int = 48) -> bool:
    """尝试把图标写到 out_path。返回是否成功。"""
    path, index = parse_icon_source(source)
    if not path or not os.path.isfile(path):
        return False

    # 1) ExtractIconEx + GetIconInfo/GetDIBits（保留 alpha，支持 dll 索引）
    try:
        import win32gui  # type: ignore
        from PyQt6.QtCore import Qt

        large, small = win32gui.ExtractIconEx(path, index)
        handles = list(large) + list(small)
        if handles:
            try:
                image = _hicon_to_qimage(handles[0])
                if image is not None and not image.isNull():
                    if image.width() != size or image.height() != size:
                        image = image.scaled(
                            size, size,
                            Qt.AspectRatioMode.KeepAspectRatio,
                            Qt.TransformationMode.SmoothTransformation,
                        )
                    out_path.parent.mkdir(parents=True, exist_ok=True)
                    if image.save(str(out_path), "PNG"):
                        return True
            finally:
                for handle in handles:
                    try:
                        win32gui.DestroyIcon(handle)
                    except Exception:
                        pass
    except Exception:
        pass

    # 2) 退回 Qt 的图标提供器（需要已有 QApplication，无 GUI 时跳过以免崩溃）
    try:
        from PyQt6.QtCore import QFileInfo, QSize
        from PyQt6.QtWidgets import QApplication, QFileIconProvider

        if QApplication.instance() is None:
            return False
        provider = QFileIconProvider()
        icon = provider.icon(QFileInfo(path))
        if icon.isNull():
            return False
        pixmap = icon.pixmap(QSize(size, size))
        if pixmap.isNull():
            return False
        out_path.parent.mkdir(parents=True, exist_ok=True)
        return bool(pixmap.save(str(out_path), "PNG"))
    except Exception:
        return False

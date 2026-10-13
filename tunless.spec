# PyInstaller 打包配置（PyInstaller 6.x）
#
#   pyinstaller --noconfirm --clean tunless.spec
#
# 产物：dist/TunlessProxy/
#   TunlessProxy.exe   窗口化：双击开界面，`--run <id>` 静默启动应用（快捷方式指向它）
#   tunless.exe        控制台：给命令行用，能看见 --list / --doctor / --test 的输出
#
# 两个 exe 共用同一份依赖，所以总量只比单 exe 多几百 KB。
# 刻意用 onedir 而不是 onefile，也刻意不开 UPX：onefile 每次启动都要解压到临时目录，
# 既慢又更容易被杀软误报，而本程序本来就是常驻托盘的工具。

from pathlib import Path

ROOT = Path(SPECPATH)

COMMON_HIDDEN = [
    "win32com.client",
    "win32gui",
    "win32ui",
    "win32file",
    "win32con",
    "win32api",
    "pythoncom",
    "pywintypes",
    "pefile",
    "PyQt6.QtNetwork",
]

COMMON_EXCLUDES = [
    "tkinter",
    "unittest",
    "pydoc",
    "doctest",
    "matplotlib",
    "numpy",
    "pandas",
    "scipy",
    "PIL",
    "setuptools",
    "pip",
    "Pythonwin",            # pywin32 自带的 IDE，我们只用 win32com/win32gui/win32ui
    "pywin.dialogs",
    "PyQt6.QtWebEngineCore",
    "PyQt6.QtWebEngineWidgets",
    "PyQt6.QtWebEngineQuick",
    "PyQt6.QtQuick",
    "PyQt6.QtQuick3D",
    "PyQt6.QtQml",
    "PyQt6.QtQuickWidgets",
    "PyQt6.Qt3DCore",
    "PyQt6.Qt3DRender",
    "PyQt6.QtMultimedia",
    "PyQt6.QtMultimediaWidgets",
    "PyQt6.QtBluetooth",
    "PyQt6.QtDesigner",
    "PyQt6.QtHelp",
    "PyQt6.QtOpenGL",
    "PyQt6.QtOpenGLWidgets",
    "PyQt6.QtPdf",
    "PyQt6.QtPdfWidgets",
    "PyQt6.QtPositioning",
    "PyQt6.QtSerialPort",
    "PyQt6.QtSpatialAudio",
    "PyQt6.QtSql",
    "PyQt6.QtSvgWidgets",
    "PyQt6.QtTest",
    "PyQt6.QtTextToSpeech",
    "PyQt6.QtWebChannel",
    "PyQt6.QtWebSockets",
]

# 这些二进制 PyInstaller 会照搬进来，但本程序一行都用不到：
#   opengl32sw.dll  Qt 的软件 OpenGL 回退，20MB —— 纯 Widgets 程序用不上
#   Qt6Pdf.dll      没有 PDF 功能
#   mfc140u.dll     Pythonwin 的依赖
DROP_BINARIES = {
    "opengl32sw.dll",
    "qt6pdf.dll",
    "mfc140u.dll",
    "mfcm140u.dll",
}

# imageformats 插件：Qt6 里 PNG/BMP 是内置的，ICO 需要插件。
# 我们只存 PNG 和 ICO，其余（gif/jpeg/tiff/webp/tga/wbmp）都不需要。
KEEP_IMAGE_PLUGINS = {"qico.dll", "qpng.dll"}


def _keep_binary(entry) -> bool:
    name = str(entry[0]).replace("\\", "/")
    base = name.rsplit("/", 1)[-1].lower()
    if base in DROP_BINARIES:
        return False
    if name.lower().startswith("pythonwin/"):
        return False
    if "/imageformats/" in name.lower() and base not in KEEP_IMAGE_PLUGINS:
        return False
    return True

a = Analysis(
    [str(ROOT / "tunless_entry.py")],
    pathex=[str(ROOT)],
    binaries=[],
    hiddenimports=COMMON_HIDDEN,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=COMMON_EXCLUDES,
    noarchive=False,
    optimize=0,
)

# 裁掉用不到的二进制（见 DROP_BINARIES 注释）
a.binaries = [entry for entry in a.binaries if _keep_binary(entry)]

pyz = PYZ(a.pure)

exe_gui = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="TunlessProxy",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,          # 托盘程序：双击不要弹黑框
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

exe_cli = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="tunless",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,           # 命令行版：--list / --doctor / --test 要看得见输出
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe_gui,
    exe_cli,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="TunlessProxy",
)

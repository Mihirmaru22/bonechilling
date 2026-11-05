# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for BoneChilling (v2 package).

Bundles the desktop shell (pywebview) + FastAPI backend + the static webui/
assets into one executable. Build:  pyinstaller BoneChilling.spec
"""
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

# Packages with dynamic/plugin imports PyInstaller can't see statically.
hidden = []
for pkg in ("uvicorn", "websockets", "fastapi", "starlette", "anyio",
            "keyring", "keyring.backends", "pydicom", "webview", "encodings"):
    hidden += collect_submodules(pkg)
hidden += [
    "bonechiling", "bonechiling.api.server", "bonechiling.desktop.app",
    "cv2", "numpy", "PIL.Image", "pytesseract", "openpyxl", "requests",
    "pydantic", "uvicorn.lifespan.on", "uvicorn.loops.auto",
    "uvicorn.protocols.http.auto", "uvicorn.protocols.websockets.auto",
]

# Ship the SPA static files next to the package so server.py finds webui/.
datas = [("src/bonechiling/webui", "bonechiling/webui")]
datas += collect_data_files("pydicom")  # VR/dictionary data files

a = Analysis(
    ["packaging/launcher.py"],
    pathex=["src"],
    binaries=[],
    datas=datas,
    hiddenimports=hidden,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "PySide6", "PyQt5", "scipy"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="BoneChilling",
    console=False,            # windowed app (no terminal). Use console=True to debug startup.
    disable_windowed_traceback=False,
)

coll = COLLECT(
    exe, a.binaries, a.datas,
    strip=False, upx=True, upx_exclude=[],
    name="BoneChilling",      # one-folder dist (smaller/faster than one-file)
)

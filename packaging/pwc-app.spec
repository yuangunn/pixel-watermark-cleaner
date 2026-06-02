# PyInstaller spec for the pixel-watermark-cleaner desktop app.
#
# Build a single-file, windowed executable:
#     pyinstaller packaging/pwc-app.spec
# Output: dist/pwc-app(.exe on Windows).
#
# The core (engine/app/picker) is opencv + numpy + stdlib Tkinter only, so the
# bundle stays small. The optional LaMa backend (torch) is intentionally NOT
# bundled -- it's a heavy opt-in install, not part of the shipped app.
import os

block_cipher = None

# The spec lives in packaging/, so the project root is one level up.
# PyInstaller injects SPECPATH (the spec's directory) as a global.
try:
    root = os.path.abspath(os.path.join(SPECPATH, ".."))  # noqa: F821
except NameError:
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

a = Analysis(
    [os.path.join(root, "app.py")],
    pathex=[root],
    binaries=[],
    datas=[],
    hiddenimports=["engine", "app_core", "picker_core"],
    hookspath=[],
    runtime_hooks=[],
    # Keep the binary lean: exclude torch/ML and test tooling even if present.
    excludes=["torch", "simple_lama_inpainting", "pytest", "tkinter.test"],
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="pwc-app",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    runtime_tmpdir=None,
    console=False,            # windowed app, no terminal
    disable_windowed_traceback=False,
    icon=None,
)

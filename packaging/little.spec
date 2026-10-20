# PyInstaller recipe for the installed app. Build from the project root:
#   pyinstaller packaging/little.spec --noconfirm
# The result is dist/Little/Little.exe; packaging/little.iss wraps it in an installer.
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH).parent

# Most of Little imports inside the function that needs it, so a missing
# optional package costs one feature, not the start. PyInstaller only sees
# top-level imports, so everything is named here.
hidden = (
    collect_submodules("jarvis")
    + collect_submodules("pyttsx3")
    + ["speech_recognition", "pyaudio", "edge_tts", "playsound3", "pyautogui",
       "pytesseract", "PIL.Image", "pypdf", "docx", "psutil", "playwright.sync_api"]
)

a = Analysis(
    [str(ROOT / "launcher_web.py")],
    pathex=[str(ROOT)],
    datas=[
        (str(ROOT / "ui"), "ui"),
        (str(ROOT / "little.ico"), "."),
        (str(ROOT / ".env.example"), "."),
    ],
    hiddenimports=hidden,
    excludes=["pytest", "tkinter.test"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Little",
    icon=str(ROOT / "little.ico"),
    console=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="Little")

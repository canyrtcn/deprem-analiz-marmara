"""Portable build script: python build.py (proje kokunden calistirin).

PyInstaller ile tek klasorluk (onedir) penceresiz exe uretir.
Cikti: dist/deprem-izleme/deprem-izleme.exe + data/ klasoru.
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("PyInstaller kurulu degil: pip install pyinstaller")
        return 1

    sep = os.pathsep
    icon_ico = os.path.join(HERE, "assets", "icon.ico")
    icon_png = os.path.join(HERE, "assets", "icon.png")
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--name", "deprem-izleme",
        "--onedir",
        "--windowed",
        "--icon", icon_ico,
        "--add-data", f"{icon_ico}{sep}.",
        "--add-data", f"{icon_png}{sep}.",
        os.path.join(HERE, "run_gui.py"),
    ]
    print("Calistiriliyor:", " ".join(cmd))
    r = subprocess.run(cmd, cwd=HERE)
    if r.returncode != 0:
        print("Build BASARISIZ.")
        return r.returncode
    out = os.path.join(HERE, "dist", "deprem-izleme", "deprem-izleme.exe")
    print("Build tamam:", out)
    print("Not: ilk calistirmada data/ klasoru exe yaninda otomatik olusur.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

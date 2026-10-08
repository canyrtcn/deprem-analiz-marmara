"""Portable build script: python build.py (proje kokunden calistirin).

PyInstaller ile tek klasorluk (onedir) penceresiz exe uretir.
Cikti: dist/deprem-izleme/deprem-izleme.exe + data/ klasoru.
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def _backup_user_data():
    """Build dist klasörünü siler; kullanıcının data/ klasörünü yedekle."""
    import shutil
    import tempfile
    data_dir = os.path.join(HERE, "dist", "deprem-izleme", "data")
    if not os.path.isdir(data_dir):
        return None
    backup = tempfile.mkdtemp(prefix="deprem_data_")
    shutil.copytree(data_dir, os.path.join(backup, "data"))
    print(f"Kullanıcı verisi yedeklendi: {data_dir} -> {backup}")
    return backup


def _restore_user_data(backup):
    """Yedeği yeni build'in data/ klasörüne geri koy."""
    import shutil
    if not backup:
        return
    src = os.path.join(backup, "data")
    dst = os.path.join(HERE, "dist", "deprem-izleme", "data")
    try:
        shutil.copytree(src, dst, dirs_exist_ok=True)
        print(f"Kullanıcı verisi geri yüklendi: {dst}")
    finally:
        shutil.rmtree(backup, ignore_errors=True)


def main():
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("PyInstaller kurulu degil: pip install pyinstaller")
        return 1

    sep = os.pathsep
    icon_ico = os.path.join(HERE, "assets", "icon.ico")
    icon_png = os.path.join(HERE, "assets", "icon.png")
    backup = _backup_user_data()
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
        _restore_user_data(backup)
        return r.returncode
    _restore_user_data(backup)
    out = os.path.join(HERE, "dist", "deprem-izleme", "deprem-izleme.exe")
    print("Build tamam:", out)
    print("Not: ilk calistirmada data/ klasoru exe yaninda otomatik olusur.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

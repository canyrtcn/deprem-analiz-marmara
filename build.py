"""Portable build script: python build.py (proje kokunden calistirin).

PyInstaller ile tek klasorluk (onedir) penceresiz exe uretir.
Cikti: dist/deprem-izleme/deprem-izleme.exe + data/ klasoru.
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
APP_DIRNAME = "deprem-analiz-marmara"  # dist/<bu>/deprem-analiz-marmara.exe
LEGACY_DIRNAME = "deprem-izleme"  # eski build klasörü (verisi taşınır)
EXE_NAME = "deprem-analiz-marmara.exe"
RELEASE_ZIP = "deprem-analiz-marmara-win64.zip"


def _dist_dir():
    return os.path.join(HERE, "dist", APP_DIRNAME)


def _migrate_legacy_data():
    """Eski klasördeki kullanıcı verisini yeni klasöre taşı (tek seferlik)."""
    import shutil
    legacy = os.path.join(HERE, "dist", LEGACY_DIRNAME, "data")
    new_data = os.path.join(_dist_dir(), "data")
    if os.path.isdir(legacy) and not os.path.isdir(new_data):
        try:
            shutil.copytree(legacy, new_data)
            print(f"Eski veri taşındı: {legacy} -> {new_data}")
        except Exception as e:
            print(f"Eski veri taşınamadı: {e}")


def _backup_user_data():
    """Build dist klasörünü siler; kullanıcının data/ klasörünü yedekle."""
    import shutil
    import tempfile
    data_dir = os.path.join(_dist_dir(), "data")
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
    dst = os.path.join(_dist_dir(), "data")
    try:
        shutil.copytree(src, dst, dirs_exist_ok=True)
        print(f"Kullanıcı verisi geri yüklendi: {dst}")
    finally:
        shutil.rmtree(backup, ignore_errors=True)


def main():
    release = "--release" in sys.argv
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("PyInstaller kurulu degil: pip install pyinstaller")
        return 1

    sep = os.pathsep
    icon_ico = os.path.join(HERE, "assets", "icon.ico")
    icon_png = os.path.join(HERE, "assets", "icon.png")
    _migrate_legacy_data()
    backup = _backup_user_data()
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--name", APP_DIRNAME,
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
    out = os.path.join(_dist_dir(), EXE_NAME)
    print("Build tamam:", out)
    print("Not: ilk calistirmada data/ klasoru exe yaninda otomatik olusur.")
    if release:
        return make_release_package()
    return 0


def make_release_package():
    """GitHub Release'e eklenecek zip'i üret (updater bunu indirir)."""
    import shutil
    import subprocess
    import tempfile
    # Release kapısı: gizli-bilgi taraması temiz değilse paket üretilmez.
    chk = subprocess.run([sys.executable, "scripts/check_secrets.py"],
                         capture_output=True, text=True)
    print(chk.stdout.strip().splitlines()[-1] if chk.stdout.strip() else "")
    if chk.returncode != 0:
        print("Release DURDURULDU: gizli-bilgi taramasi bulgu verdi.")
        return 1
    dist_dir = _dist_dir()
    zip_base = os.path.join(HERE, "dist", "deprem-analiz-marmara-win64")
    # data/ pakete GİRMEZ (kullanıcı verisi); exe + _internal girer
    tmp = tempfile.mkdtemp(prefix="deprem_release_")
    try:
        pkg_root = os.path.join(tmp, APP_DIRNAME)
        shutil.copytree(dist_dir, pkg_root,
                        ignore=shutil.ignore_patterns("data"))
        if os.path.exists(zip_base + ".zip"):
            os.remove(zip_base + ".zip")
        shutil.make_archive(zip_base, "zip", tmp, APP_DIRNAME)
        print("Release paketi:", zip_base + ".zip")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

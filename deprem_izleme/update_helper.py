"""Guncelleme yardimcisi (ayri surec, stdlib-only).

Kullanim:
    python update_helper.py --staging DIR --appdir DIR --pid N
        --exe AD --version X [--wait 60]

Akis:
1. Tek-instance kilidi (staging/update.lock).
2. Beklenen PID'in gercekten hedef exe oldugunu dogrula, bitmesini bekle.
3. Program dosyalarinin yedegini al (SADECE exe + _internal; data/ HARIC).
4. Yeni dosyalari kur (allowlist: exe + _internal; data/ asla ezilmez).
5. Yeni exe --update-probe ile surum+saglik dogrula.
6. Basarisizsa rollback (yedekten geri), sonuc JSON'u yaz, temizlen.

Cikis kodu: 0 basari, 1 basarisizlik (rollback denenmis), 2 kritik
(yedek alinamadi -> HICBIR dosyaya dokunulmadi).
"""
import argparse
import ctypes
import json
import os
import shutil
import subprocess
import sys
import time

PROGRAM_ITEMS = ("exe", "_internal")
DATA_NAMES = ("data",)


def _log(staging, msg):
    try:
        with open(os.path.join(staging, "helper.log"), "a",
                  encoding="utf-8") as f:
            f.write(f"{time.strftime('%H:%M:%S')} {msg}\n")
    except Exception:
        pass


def _pid_exe_path(pid):
    """PID'in calistirildigi dosya yolu (dogrulama icin; None=belli degil)."""
    try:
        kernel32 = ctypes.windll.kernel32
        PROCESS_QUERY_LIMITED = 0x1000
        h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED, False, int(pid))
        if not h:
            return None
        try:
            buf = ctypes.create_unicode_buffer(1024)
            n = ctypes.windll.psapi.GetModuleFileNameExW(h, None, buf, 1024)
            if n:
                return os.path.normcase(os.path.abspath(buf.value))
        finally:
            kernel32.CloseHandle(h)
    except Exception:
        pass
    return None


def _pid_alive(pid):
    try:
        os.kill(int(pid), 0)
        return True
    except Exception:
        return False


def _copy_allowlist(src, dst):
    """SADECE exe + _internal kopyala; data/ ve yabanci dosya gecemez.

    Staging kokundeki calisan yardimci kopyasi (update-helper.exe)
    atlanir: yardimci paketteki _internal/update-helper.exe ile guncellenir.
    """
    copied = []
    for name in os.listdir(src):
        low = name.lower()
        if low in DATA_NAMES:
            continue
        if low == "update-helper.exe":
            continue
        s = os.path.join(src, name)
        d = os.path.join(dst, name)
        if low.endswith(".exe") or low == "_internal":
            if os.path.isdir(s):
                if os.path.exists(d):
                    shutil.rmtree(d)
                shutil.copytree(s, d)
            else:
                shutil.copy2(s, d)
            copied.append(name)
    return copied


def _file_locked(path):
    try:
        with open(path, "r+b"):
            return False
    except Exception:
        return True


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--staging", required=True)
    ap.add_argument("--appdir", required=True)
    ap.add_argument("--pid", required=True)
    ap.add_argument("--exe", required=True)
    ap.add_argument("--version", required=True)
    ap.add_argument("--wait", type=int, default=60)
    ap.add_argument("--alive-check", type=int, default=12,
                    help="yeni islemin yasama dogrulama suresi (sn)")
    a = ap.parse_args(argv)
    staging = os.path.abspath(a.staging)
    appdir = os.path.abspath(a.appdir)
    result = {"ok": False, "step": "baslangic"}
    lock_path = os.path.join(staging, "update.lock")

    def fail(step, msg, code=1):
        result["step"] = step
        result["error"] = msg
        _log(staging, f"HATA [{step}]: {msg}")
        try:
            with open(os.path.join(staging, "update-result.json"), "w",
                      encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False)
        except Exception:
            pass
        return code

    # 1. tek-instance
    try:
        fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.close(fd)
    except Exception:
        return fail("kilit", "baska bir guncelleme zaten calisiyor")
    _log(staging, "yardimci basladi")

    # staging icerigi baska klasorden mi? (guvenlik: appdir != staging)
    if os.path.normcase(staging) == os.path.normcase(appdir):
        return fail("dogrulama", "staging ve appdir ayni olamaz")

    # 2. PID dogrula + bekle
    try:
        pid = int(a.pid)
    except Exception:
        return fail("dogrulama", "gecersiz pid")
    if pid <= 0:
        return fail("dogrulama", "gecersiz pid")
    if _pid_alive(pid):
        ppath = _pid_exe_path(pid)
        expect = os.path.normcase(os.path.join(appdir, a.exe))
        if ppath is not None and ppath != expect:
            return fail("dogrulama",
                        "beklenen islem degil (baska exe etkilenmeyecek)")
        _log(staging, f"eski islem bekleniyor (pid={pid})")
        deadline = time.monotonic() + max(10, a.wait)
        while _pid_alive(pid) and time.monotonic() < deadline:
            time.sleep(0.5)
        if _pid_alive(pid):
            # Kullaniciyi habersiz oldurme: guvenli dur.
            return fail("bekleme",
                        "uygulama kapanmadi (sure asimi); hicbir dosya degismedi")
    _log(staging, "eski islem bitti")

    exe_path = os.path.join(appdir, a.exe)
    if _file_locked(exe_path):
        return fail("bekleme",
                    "exe hâlâ kilitli; hicbir dosya degismedi")

    # 3. yedek (SADECE program dosyalari)
    backup = os.path.join(staging, "backup")
    try:
        os.makedirs(backup, exist_ok=True)
        for name in os.listdir(appdir):
            low = name.lower()
            if low in DATA_NAMES:
                continue
            if low.endswith(".exe") or low == "_internal":
                s = os.path.join(appdir, name)
                d = os.path.join(backup, name)
                if os.path.isdir(s):
                    if os.path.exists(d):
                        shutil.rmtree(d)
                    shutil.copytree(s, d)
                else:
                    shutil.copy2(s, d)
        _log(staging, "yedek alindi")
    except Exception as e:
        return fail("yedek", f"yedek alinamadi: {e}", code=2)

    # 4. kur (allowlist; data/ staging'de olsa bile atlanir)
    try:
        new_root = staging
        _WORK = (".lock", ".log", ".json", "update-helper.exe")
        entries = [os.path.join(staging, e) for e in os.listdir(staging)
                   if not e.lower().endswith(_WORK)
                   and e.lower() != "backup"]
        dirs = [e for e in entries if os.path.isdir(e)
                and os.path.basename(e).lower() not in ("backup",)]
        if len(dirs) == 1 and len(entries) == 1:
            new_root = dirs[0]
        names = {e.lower() for e in os.listdir(new_root)}
        if not any(n.endswith(".exe") for n in names):
            raise RuntimeError("pakette exe bulunamadi")
        if a.exe.lower() not in names:
            raise RuntimeError(
                f"pakette beklenen exe yok ({a.exe})")
        if "_internal" not in names:
            raise RuntimeError("pakette _internal bulunamadi (eksik paket)")
        copied = _copy_allowlist(new_root, appdir)
        _log(staging, f"kuruldu: {copied}")
        result["installed"] = copied
    except Exception as e:
        _rollback(appdir, backup, staging)
        return fail("kurulum", f"kurulum basarisiz, geri alindi: {e}")

    # 5. saglik: yeni exe --update-probe (kilit gecikmesine karsi tekrarli)
    probed = ""
    _perr = ""
    for _try in range(3):
        try:
            p = subprocess.run([exe_path, "--update-probe"], capture_output=True,
                               text=True, timeout=25)
            got = (p.stdout or "").strip().split()
            probed = got[0] if got else ""
            if p.returncode == 0 and probed == a.version:
                break
            _perr = f"cikti={probed!r} rc={p.returncode}"
            time.sleep(3)
        except Exception as e:
            _perr = str(e)[:100]
            time.sleep(3)
    if probed != a.version:
        _rollback(appdir, backup, staging, installed=result.get("installed"))
        return fail("saglik",
                    f"yeni surum acilamadi, geri alindi: {_perr or 'surum uyusmadi'}")
    _log(staging, f"saglik OK (v{probed})")

    # 6. yeni surumu baslat (ayrilmis surec) + yasama dogrulamasi.
    # Baslatma veya erken olum -> ROLLBACK + basarisizlik (asla ok=True).
    try:
        proc = subprocess.Popen([exe_path],
                                creationflags=getattr(subprocess, "DETACHED_PROCESS", 0),
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                stdin=subprocess.DEVNULL, close_fds=True)
    except Exception as e:
        _rollback(appdir, backup, staging)
        return fail("baslatma", f"yeni surum baslatilamadi, geri alindi: {e}")
    try:
        alive = max(1, int(a.alive_check))
    except Exception:
        alive = 12
    _log(staging, f"yeni islem yasama dogrulamasi ({alive}sn)")
    deadline = time.monotonic() + alive
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            _rollback(appdir, backup, staging)
            return fail("yasama",
                        f"yeni surum erken kapandi (rc={proc.returncode}), geri alindi")
        time.sleep(0.5)
    if proc.poll() is not None:
        _rollback(appdir, backup, staging)
        return fail("yasama",
                    f"yeni surum erken kapandi (rc={proc.returncode}), geri alindi")
    _log(staging, "yasama OK")
    result["ok"] = True
    result["step"] = "tamamlandi"
    result["version"] = a.version
    _log(staging, "guncelleme tamamlandi")
    try:
        with open(os.path.join(staging, "update-result.json"), "w",
                  encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False)
    except Exception:
        pass
    return 0


def _rollback(appdir, backup, staging, installed=None):
    try:
        # Kurulumun ekledigi yedek-disi yeni dosyalari temizle.
        for name in installed or []:
            try:
                bkp = os.path.join(backup, name)
                if not os.path.exists(bkp):
                    d = os.path.join(appdir, name)
                    if os.path.isdir(d):
                        shutil.rmtree(d)
                    elif os.path.exists(d):
                        os.remove(d)
            except Exception:
                pass
        for name in os.listdir(backup):
            s = os.path.join(backup, name)
            d = os.path.join(appdir, name)
            if os.path.isdir(s):
                if os.path.exists(d):
                    shutil.rmtree(d)
                shutil.copytree(s, d)
            else:
                shutil.copy2(s, d)
        _log(staging, "rollback tamamlandi")
    except Exception as e:
        _log(staging, f"KRITIK: rollback basarisiz: {e}")


if __name__ == "__main__":
    sys.exit(main())

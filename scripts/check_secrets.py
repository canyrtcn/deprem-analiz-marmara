"""Commit/release oncesi gizli-bilgi taramasi (yalnizca stdlib).

Kullanim:
    python scripts/check_secrets.py [--staged] [--history]

Varsayilan: takip edilen dosyalar (git ls-files). --staged: stage'lenmis
dosyalarin INDEX ICERIGI (commit'e girecek hali; `git show :0:dosya`).
--history: erisilebilir TUM blob'lar (tum branch/tag gecmisi).

Bulgu varsa cikis kodu 1; okuma/listeleme hatasinda 2 (fail-closed).
Degerler ASLA acik yazilmaz (redakte gosterim).
Bu betik "desen bulunamadi" der; "kesinlikle gizli bilgi yok" garantisi
vermez (ozellikle ikili dosyalar, eski release paketleri ve GitHub
asset'leri ayrica incelenmelidir).
"""
import re
import subprocess
import sys

SECRET_PATTERNS = [
    ("telegram-bot-token", re.compile(r"bot\d{4,}:[\w-]{20,}")),
    ("github-token", re.compile(r"gh[pousr]_[A-Za-z0-9]{10,}")),
    ("openai-key", re.compile(r"sk-[A-Za-z0-9]{16,}")),
    ("google-api-key", re.compile(r"AIza[A-Za-z0-9_-]{16,}")),
    ("private-key", re.compile(r"BEGIN [A-Z ]*PRIVATE KEY")),
]

PII_PATTERNS = [
    ("eposta", re.compile(r"[A-Za-z0-9._%+-]+@(?:gmail|hotmail|outlook|yahoo)\.[A-Za-z]{2,}")),
    ("win-kullanici-yolu", re.compile(r"C:\\+Users\\+[^\\\"\s:/]+", re.IGNORECASE)),
    ("win-kullanici-yolu-slash", re.compile(r"C:/Users/[^/\"\s:]+", re.IGNORECASE)),
    ("unix-ev-dizini", re.compile(r"/home/[^/\"\s]+")),
]

# Tarayicinin kendisi (kendi desenleri yanlis alarmdir) atlanir.
SELF_FILE = "scripts/check_secrets.py"


def _tracked(staged):
    cmd = (["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"]
           if staged else ["git", "ls-files"])
    try:
        out = subprocess.run(cmd, capture_output=True, text=True,
                             timeout=60, check=True).stdout
    except Exception as e:
        # FAIL-CLOSED: dosya listesi alinamazsa tarama BASARISIZ sayilir.
        print(f"HATA: git dosya listesi okunamadi ({e}); tarama guvenilmez.")
        return None
    return [p for p in out.splitlines() if p.strip()]


def _read_text(path, staged):
    """Commit'e girecek icerik: staged ise index blob'u, degilse disk.

    Donus: (text|None, okunamama-nedeni|None). Ikili atlama ile gercek
    hata ayri raporlanir; hata sessiz basari sayilmaz.
    """
    if staged:
        try:
            r = subprocess.run(["git", "show", f":0:{path}"],
                               capture_output=True, timeout=60, check=True)
            try:
                return r.stdout.decode("utf-8"), None
            except UnicodeDecodeError:
                return None, "ikili-atlandi"
        except Exception:
            return None, "blob-okunamadi"
    try:
        with open(path, "r", encoding="utf-8", errors="strict") as f:
            return f.read(), None
    except UnicodeDecodeError:
        return None, "ikili-atlandi"
    except FileNotFoundError:
        return None, "dosya-yok"
    except Exception:
        return None, "okuma-hatasi"


def _redact(match):
    s = match.group(0)
    return (s[:4] + "***<redakte>") if len(s) > 8 else "***<redakte>"


def scan_file(path, staged=False):
    """(bulgular, durum): durum ok|ikili-atlandi|hata-nedeni."""
    findings = []
    text, why = _read_text(path, staged)
    if text is None:
        return [], (why or "okuma-hatasi")
    for i, line in enumerate(text.splitlines(), 1):
        if "re.compile" in line or "<kullanici>" in line or "<redakte" in line:
            continue  # desen tanimi / redaksiyon ciktisi ornegi
        for name, rx in SECRET_PATTERNS + PII_PATTERNS:
            m = rx.search(line)
            if m:
                findings.append((name, path, i, rx.sub(_redact, line.strip())[:80]))
    return findings, "ok"


def _history_blobs():
    """Tum erisilebilir blob'lar: [(sha, ornek-yol)]. Hata -> None."""
    try:
        out = subprocess.run(["git", "rev-list", "--all", "--objects"],
                             capture_output=True, text=True, timeout=300,
                             check=True).stdout
    except Exception as e:
        print(f"HATA: gecmis listelenemedi ({e}).")
        return None
    blobs = {}
    for line in out.splitlines():
        parts = line.split(" ", 1)
        if len(parts) != 2:
            continue
        sha, path = parts
        if path and sha not in blobs:
            blobs[sha] = path
    return list(blobs.items())


def _scan_history():
    blobs = _history_blobs()
    if blobs is None:
        print("TARAMA BASARISIZ: gecmis okunamadi.")
        return 2
    findings = 0
    scanned = 0
    skipped = 0
    for sha, path in blobs:
        try:
            r = subprocess.run(["git", "cat-file", "-s", sha],
                               capture_output=True, text=True, timeout=60,
                               check=True)
            if int(r.stdout.strip() or 0) > 1000000:
                skipped += 1
                continue
            c = subprocess.run(["git", "cat-file", "-p", sha],
                               capture_output=True, timeout=60, check=True)
            text = c.stdout.decode("utf-8")
        except UnicodeDecodeError:
            skipped += 1
            continue
        except Exception:
            print(f"TARAMA BASARISIZ: blob okunamadi ({sha[:8]}).")
            return 2
        scanned += 1
        for i, line in enumerate(text.splitlines(), 1):
            if "re.compile" in line or "<kullanici>" in line or "<redakte" in line:
                continue
            for name, rx in SECRET_PATTERNS + PII_PATTERNS:
                m = rx.search(line)
                if m:
                    findings += 1
                    if findings <= 20:
                        print(f"  [{name}] {path}@{sha[:8]}:{i}: "
                              f"{rx.sub(_redact, line.strip())[:60]}")
    if findings:
        print(f"GECMIS: {findings} bulgu ({scanned} blob tarandi, "
              f"{skipped} atlandi). Degerler redakte.")
        return 1
    print(f"Gecmis temiz ({scanned} blob tarandi, {skipped} ikili/buyuk atlandi). "
          "Bu, kesin garanti degildir.")
    return 0


def main():
    staged = "--staged" in sys.argv
    import os
    os.chdir(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
    if "--history" in sys.argv:
        return _scan_history()
    files = _tracked(staged)
    if files is None:
        print("TARAMA BASARISIZ: dosya listesi alinamadi.")
        return 2
    all_findings = []
    skipped = 0
    errors = {}
    for p in files:
        if p.replace("\\", "/") == SELF_FILE:
            continue  # betigin kendi desenleri yanlis alarmdir
        res, status = scan_file(p, staged=staged)
        if status == "ikili-atlandi":
            skipped += 1
            continue
        if status != "ok":
            errors[status] = errors.get(status, 0) + 1
            continue
        all_findings.extend(res)
    if errors:
        print(f"TARAMA BASARISIZ: {sum(errors.values())} dosya okunamadi {errors}.")
        return 2
    if all_findings:
        print(f"{len(all_findings)} bulgu (degerler redakte):")
        for name, path, line, ctx in all_findings[:50]:
            print(f"  [{name}] {path}:{line}: {ctx}")
        return 1
    print(f"Desen bulunamadi ({len(files)} dosya tarandi, {skipped} ikili atlandi). "
          "Bu, kesin gizli-bilgi-yok garantisi degildir.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

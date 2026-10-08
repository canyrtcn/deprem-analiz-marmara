"""Commit/release oncesi gizli-bilgi taramasi (yalnizca stdlib).

Kullanim:
    python scripts/check_secrets.py [--staged]

Varsayilan: takip edilen dosyalar (git ls-files). --staged: stage'lenmis
dosyalarin INDEX ICERIGI (commit'e girecek hali; `git show :0:dosya`).

Bulgu varsa cikis kodu 1; degerler ASLA acik yazilmaz (redakte gosterim).
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
        print(f"git okunamadi: {e}")
        return []
    return [p for p in out.splitlines() if p.strip()]


def _read_text(path, staged):
    """Commit'e girecek icerik: staged ise index blob'u, degilse disk."""
    if staged:
        try:
            r = subprocess.run(["git", "show", f":0:{path}"],
                               capture_output=True, timeout=60, check=True)
            return r.stdout.decode("utf-8")
        except Exception:
            return None  # silinmis/okunamaz blob
    try:
        with open(path, "r", encoding="utf-8", errors="strict") as f:
            return f.read()
    except Exception:
        return None  # ikili/okunamaz


def _redact(match):
    s = match.group(0)
    return (s[:4] + "***<redakte>") if len(s) > 8 else "***<redakte>"


def scan_file(path, staged=False):
    findings = []
    text = _read_text(path, staged)
    if text is None:
        return None  # ikili/okunamaz: atlanir (ozette sayilir)
    for i, line in enumerate(text.splitlines(), 1):
        if "re.compile" in line or "<kullanici>" in line or "<redakte" in line:
            continue  # desen tanimi / redaksiyon ciktisi ornegi
        for name, rx in SECRET_PATTERNS + PII_PATTERNS:
            m = rx.search(line)
            if m:
                findings.append((name, path, i, rx.sub(_redact, line.strip())[:80]))
    return findings


def main():
    staged = "--staged" in sys.argv
    import os
    os.chdir(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
    files = _tracked(staged)
    all_findings = []
    skipped = 0
    for p in files:
        if p.replace("\\", "/") == SELF_FILE:
            continue  # betigin kendi desenleri yanlis alarmdir
        res = scan_file(p, staged=staged)
        if res is None:
            skipped += 1
            continue
        all_findings.extend(res)
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

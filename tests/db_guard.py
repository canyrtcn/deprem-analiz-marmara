"""Tasimabilirlik oneki (otomatik eklendi): TESTTMP sentetik dizin, REPO_ROOT repo koku."""
import os as _os
TESTTMP = _os.environ.get("DEPREM_TESTTMP") or _os.getcwd()
REPO_ROOT = (_os.environ.get("DEPREM_REPO_ROOT")
             or _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
"""Test izolasyon kapisi (scratch-only; uretime girmez).

Kullanim (test dosyasinin EN USTUNDE, repo importlarindan ONCE):
    import os
    os.environ["DEPREM_SKIP_DB_INIT"] = "1"
    import db_guard
    db_guard.install()

Etkiler:
- sqlite3.connect: canli DB yollarina (normalizasyonlu karsilastirma)
  erisim denemesi RuntimeError ile reddedilir; okuma DAHIL (fail-closed).
- Bypass bayragi YOKTUR; kaldirmanin tek yolu install()'u cagirmamak.
- Ayri test sureci duzeyinde calisir (her python sureci kendi kurar).
- Sinir: isletim-sistemi duzeyinde ACL degisikligi yapmaz; ayni makinede
  baska surecler (uygulamanin kendisi) etkilenmez.
"""
import os
import sqlite3 as _sq

_LIVE_FILES = ("depremler.db",)
_LIVE_BASENAMES = set(_LIVE_FILES)
_guarded = False


def _norm(path):
    try:
        s = str(path)
        if s.startswith("file:"):
            s = s[5:].split("?", 1)[0]
        s = os.path.normcase(os.path.abspath(os.path.realpath(s)))
        return s
    except Exception:
        return str(path)


class LiveDBBlockedError(RuntimeError):
    pass


def install(extra_names=None):
    """sqlite3.connect sarmalayiciyi kur (fail-closed, baypassiz)."""
    global _guarded, _real_connect
    names = set(_LIVE_BASENAMES)
    if extra_names:
        names.update(extra_names)
    real_connect = _sq.connect
    _real_connect = real_connect

    def guarded_connect(database=None, *args, **kwargs):
        if database is not None and database != ":memory:":
            try:
                base = os.path.basename(_norm(database))
            except Exception:
                base = ""
            if base in names:
                raise LiveDBBlockedError(
                    "canli DB erisimi testte yasak: " + base)
        return real_connect(database, *args, **kwargs)

    _sq.connect = guarded_connect
    _guarded = True
    return True


def release(audit_reason=""):
    """Koruma kaldirma: YALNIZCA acik onayli islemler (G1-B snapshot gibi)
    cagirir; sebep stdout'a yazilir (denetim izi)."""
    global _guarded
    print("db_guard RELEASED: %s" % audit_reason)
    _sq.connect = _real_connect or _sq.connect
    _guarded = False


def is_installed():
    return _guarded

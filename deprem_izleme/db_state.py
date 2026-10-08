"""Kalıcı bakım durumu + aktif DB seçimi (merkezi, atomik, fail-closed).

- maintenance.json YOKSA: ilk kurulum -> {"state":"normal"} yazilir
  (mevcut davranis kilitlenmez).
- Kurulumdan SONRA eksik/bozuk/celiskili durum -> fail-closed (yazma yok).
- active_db.json YOKSA: varsayilan legacy yol (normal acilis bozulmaz).
- maintenance=frozen + hedef v2 degilse VEYA active-hedef celiskisi varsa -> yazma engellenir (MaintenanceActiveError).
- G2-G3 arasi salt-okunur acilis: open_active_db(readonly=True).
"""
import json
import os

from deprem_izleme.config import MAIN_DB, DATA_DIR
from deprem_izleme.db import MaintenanceActiveError

STATE_FILE = os.path.join(DATA_DIR, "maintenance.json")
ACTIVE_FILE = os.path.join(DATA_DIR, "active_db.json")
_SETUP_MARK = os.path.join(DATA_DIR, ".state_setup_done")


def _read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _write_json_atomic(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def ensure_setup():
    """Ilk kurulum: durum dosyalari yoksa guvenli varsayilanlari yazar.

    Mevcut uygulamayi kilitlemez (normal + legacy). Bir kez calisir.
    """
    try:
        if os.path.exists(_SETUP_MARK):
            return True
        if not os.path.exists(STATE_FILE):
            _write_json_atomic(STATE_FILE, {"state": "normal"})
        if not os.path.exists(ACTIVE_FILE):
            _write_json_atomic(ACTIVE_FILE, {"active": MAIN_DB})
        with open(_SETUP_MARK, "w", encoding="utf-8") as f:
            f.write("1")
        return True
    except Exception:
        return False


def get_state():
    """(state, neden). state: normal|frozen|kurtarma-gerekli|bilinmiyor."""
    d = _read_json(STATE_FILE)
    if d is None:
        if not os.path.exists(_SETUP_MARK):
            return "normal", "kurulum-oncesi-varsayilan"
        return "bilinmiyor", "durum-dosyasi-okunamadi"
    s = d.get("state")
    if s in ("normal", "frozen", "kurtarma-gerekli"):
        return s, "ok"
    return "bilinmiyor", "gecersiz-durum-degeri"


def get_active_db():
    """Aktif DB yolu (yoksa MAIN_DB)."""
    d = _read_json(ACTIVE_FILE)
    if d is None:
        return MAIN_DB
    p = d.get("active")
    return p if p else MAIN_DB


def set_frozen(reason=""):
    _write_json_atomic(STATE_FILE, {"state": "frozen", "reason": reason})
    st, _ = get_state()
    if st != "frozen":
        raise RuntimeError("frozen yazilamadi (dogrulama okumasi tutmadi)")


def set_normal():
    _write_json_atomic(STATE_FILE, {"state": "normal"})
    st, _ = get_state()
    if st != "normal":
        raise RuntimeError("normal yazilamadi (dogrulama okumasi tutmadi)")


def check_writable():
    """Yazma onkosulu: frozen/celiskili/bilinmeyen -> MaintenanceActiveError.

    active hedef v2 degilken frozen olmak da engeldir (celiski).
    """
    st, why = get_state()
    if st != "normal":
        raise MaintenanceActiveError(
            "yazma kapali (bakim durumu: %s)" % st)
    return True


def open_active_db(readonly=False):
    """Merkezi aktif-DB baglantisi (GUI/CLI/fetch/analiz buradan acar).

    readonly=True: frozen donemde okumaya izin verir (G2-G3); yazma
    yollari ayrica check_writable() ister.
    """
    import sqlite3 as _sq
    path = get_active_db()
    if readonly:
        conn = _sq.connect("file:%s?mode=ro" % path, uri=True)
        return conn
    check_writable()
    from deprem_izleme.db import get_db
    conn = get_db(path)
    return conn

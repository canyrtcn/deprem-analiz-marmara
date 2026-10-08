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
from deprem_izleme.db import MaintenanceActiveError, maintenance_hold

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


def get_active_db(strict=False):
    """Aktif DB yolu (yoksa MAIN_DB).

    strict=True: dosya VAR ama bozuk/gecersizse sessiz fallback YOK,
    MaintenanceActiveError yukselir (yazma yollari fail-closed).
    Okuma yollari strict=False ile legacy varsayilani korur.
    """
    if not os.path.exists(ACTIVE_FILE):
        return MAIN_DB
    d = _read_json(ACTIVE_FILE)
    p = (d or {}).get("active") if isinstance(d, dict) else None
    if p:
        return p
    if strict:
        raise MaintenanceActiveError(
            "aktif DB durumu okunamadi (bozuk dosya) — yazma kapali")
    try:
        import logging as _lg
        _lg.getLogger(__name__).warning(
            "active_db.json bozuk; salt-okunur legacy varsayilani kullaniliyor")
    except Exception:
        pass
    return MAIN_DB


def set_frozen(reason="", _lock_path=None):
    """frozen gecisi: surecler-arasi bakim kilidi altinda atomik yaz+dogla."""
    with maintenance_hold(_lock_path or MAIN_DB, timeout_s=30):
        _write_json_atomic(STATE_FILE, {"state": "frozen", "reason": reason})
        st, _ = get_state()
        if st != "frozen":
            raise RuntimeError("frozen yazilamadi (dogrulama okumasi tutmadi)")


def set_normal(_lock_path=None):
    """normal gecisi: surecler-arasi bakim kilidi altinda atomik yaz+dogla."""
    with maintenance_hold(_lock_path or MAIN_DB, timeout_s=30):
        _write_json_atomic(STATE_FILE, {"state": "normal"})
        st, _ = get_state()
        if st != "normal":
            raise RuntimeError("normal yazilamadi (dogrulama okumasi tutmadi)")


def check_writable():
    """Yazma onkosulu: frozen/celiskili/bilinmeyen -> MaintenanceActiveError.

    frozen her durumda engeldir. Kurulum sonrasi kayip/bozuk durum
    dosyalari ile bozuk aktif-DB dosyasi da yazmayi engeller
    (fail-closed; sessiz normal donusu yok).
    """
    st, why = get_state()
    if st != "normal":
        raise MaintenanceActiveError(
            "yazma kapali (bakim durumu: %s)" % st)
    get_active_db(strict=True)  # bozuk hedef dosyasi da yazmayi engeller
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

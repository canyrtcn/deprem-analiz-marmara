"""Hata kayit defteri - sessiz gecistirilen hatalarin izi (data/error.log)."""
import os
import re
import traceback
from datetime import datetime


_BS = chr(92)  # ters slash (re.sub degistirme metninde ham kullanilmaz)

_REDACT_RES = [
    (re.compile(r"bot\d+:[\w-]{10,}"), "bot<redakte-token>"),
    (re.compile(r"Bearer\s+[\w\-.~+/=]{8,}"), "Bearer <redakte>"),
    (re.compile(r"(api[_-]?key\s*[:=]\s*['\"]?)[\w\-.~+/=]{8,}", re.IGNORECASE),
     r"\1<redakte>"),
    # Ters slash sayisindan bagimsiz (traceback kaynak satirlari cift yazar)
    (re.compile(r"C:\\+Users\\+[^\\\"\s:/]+", re.IGNORECASE),
     lambda m: "C:" + _BS + "Users" + _BS + "<kullanici>"),
    (re.compile(r"C:/Users/[^/\"\s:]+", re.IGNORECASE),
     "C:/Users/<kullanici>"),
    (re.compile(r"/home/[^/\"\s:]+"), "/home/<kullanici>"),
    (re.compile(r"[A-Za-z0-9._%+-]+@(?:gmail|hotmail|outlook|yahoo)\.[A-Za-z]{2,}"),
     "<redakte-eposta>"),
]


def redact(text):
    """Log/ekran metninden sir ve kisisel yolu temizler.

    Teshis degeri korunur: hata tipi, status kodu ve sabit aciklamalar
    aynen kalir; yalnizca gizli degerler maskelenir.
    """
    try:
        s = str(text)
    except Exception:
        return "<redakte-edilemedi>"
    for rx, repl in _REDACT_RES:
        try:
            s = rx.sub(repl, s)
        except Exception:
            pass
    return s


def _log_path():
    try:
        from deprem_izleme.config import DATA_DIR
        return os.path.join(DATA_DIR, "error.log")
    except Exception:
        return "deprem_error.log"


def diag(msg):
    """Yaşam döngüsü izi (data/diag.log) - sessiz kalma sorunlarında teşhis için."""
    try:
        from deprem_izleme.config import DATA_DIR
        p = os.path.join(DATA_DIR, "diag.log")
    except Exception:
        p = "deprem_diag.log"
    try:
        with open(p, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now().isoformat(timespec='milliseconds')}] {msg}\n")
    except Exception:
        pass


def log_error(ex, context=""):
    """Hatayi dosyaya ekle, konsola da yaz (exe'de konsol yoktur).

    Dosya ve konsol KOPYALARININ ikisi de redakte edilir (ham traceback
    konsola sizmaz).
    """
    try:
        line = (f"[{datetime.now().isoformat(timespec='seconds')}] "
                f"{redact(context)}: {redact(ex)!r}\n")
        tb = redact("".join(traceback.format_exception(type(ex), ex, ex.__traceback__)))
    except Exception:
        line, tb = "[hata]", ""
    try:
        with open(_log_path(), "a", encoding="utf-8") as f:
            f.write(line + tb + "\n")
    except Exception:
        pass
    try:
        print(line + tb)
    except Exception:
        pass


def read_error_log(limit=30):
    """Son hata kayitlari (yeniden eskiye)."""
    try:
        with open(_log_path(), "r", encoding="utf-8") as f:
            lines = f.read().strip().split("\n")
        return list(reversed(lines[-limit:]))
    except Exception:
        return []

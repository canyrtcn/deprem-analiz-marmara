"""Hata kayit defteri - sessiz gecistirilen hatalarin izi (data/error.log)."""
import os
import traceback
from datetime import datetime


def _log_path():
    try:
        from deprem_izleme.config import DATA_DIR
        return os.path.join(DATA_DIR, "error.log")
    except Exception:
        return "deprem_error.log"


def log_error(ex, context=""):
    """Hatayi dosyaya ekle, konsola da yaz (exe'de konsol yoktur)."""
    try:
        line = f"[{datetime.now().isoformat(timespec='seconds')}] {context}: {ex!r}\n"
        tb = "".join(traceback.format_exception(type(ex), ex, ex.__traceback__))
        with open(_log_path(), "a", encoding="utf-8") as f:
            f.write(line + tb + "\n")
    except Exception:
        pass
    try:
        traceback.print_exc()
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

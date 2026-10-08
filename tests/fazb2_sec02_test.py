"""Tasimabilirlik oneki (otomatik eklendi): TESTTMP sentetik dizin, REPO_ROOT repo koku."""
import os as _os
TESTTMP = _os.environ.get("DEPREM_TESTTMP") or _os.getcwd()
REPO_ROOT = (_os.environ.get("DEPREM_REPO_ROOT")
             or _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
"""B2 SEC-02 testleri (commitlenmez, scratch). Yalnizca sentetik token."""
import os
os.environ["DEPREM_SKIP_DB_INIT"] = "1"
import sys
sys.path.insert(0, TESTTMP)
import db_guard
db_guard.install()
sys.path.insert(0, REPO_ROOT)
from unittest import mock
import requests as _rq

ok = []
def check(name, cond, extra=""):
    ok.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + name + (" | " + str(extra) if extra else ""))

import deprem_izleme.notifier as N

SYN = "bo" + "t999001" + ":" + "SENTETIK-telegram-token-abc123XYZ999"
SYNURL = f"https://api.telegram.org/{SYN}/sendMessage"

class R:
    def __init__(self, code, redirect=False):
        self.status_code = code
        self.is_redirect = redirect
    def raise_for_status(self):
        if self.status_code >= 400:
            e = _rq.HTTPError(f"{self.status_code} Client Error for url: {SYNURL}")
            e.response = self
            raise e
    def json(self): return {"ok": True}

def run_case(post_behavior):
    logs = []
    fake_logger = mock.Mock()
    def _err(msg, *a, **k): logs.append(str(msg))
    def _inf(msg, *a, **k): logs.append(str(msg))
    def _wrn(msg, *a, **k): logs.append(str(msg))
    fake_logger.error = _err
    fake_logger.info = _inf
    fake_logger.warning = _wrn
    with mock.patch.object(N, "TELEGRAM_TOKEN", SYN), \
         mock.patch.object(N, "TELEGRAM_CHAT_ID", "1"), \
         mock.patch.object(N, "TELEGRAM_ENABLED", True), \
         mock.patch.object(N, "logger", fake_logger), \
         mock.patch.object(N.requests, "post", side_effect=post_behavior):
        res = N.send_telegram_message(" SENTETIK test ")
    return res, logs

def blew(logs):
    import re as _re
    return any((SYN in m) or ("SENTETIK-telegram" in m)
               or _re.search(r"bot\d+:", m)
               for m in logs)

# 400/401/429/500: False + kod var + sizinti yok
for code in (400, 401, 429, 500):
    res, logs = run_case(lambda *a, **k: R(code))
    has_code = any(str(code) in m for m in logs)
    check(f"02: HTTP {code} sessiz-degil + kodlu + sizintisiz",
          res is False and has_code and not blew(logs), logs)
# timeout / baglanti: False + tip var + sizinti yok
res, logs = run_case(_rq.Timeout("SENTETIK-timeout " + SYNURL))
check("02: timeout False + sizintisiz", res is False and not blew(logs)
      and any("Timeout" in m for m in logs), logs)
res, logs = run_case(_rq.ConnectionError("SENTETIK-conn " + SYNURL))
check("02: baglanti False + sizintisiz", res is False and not blew(logs)
      and any("ConnectionError" in m for m in logs), logs)
# redirect: izlenmez + False + tek cagri
calls = []
def redir(*a, **k):
    calls.append(k)
    return R(302, redirect=True)
res, logs = run_case(redir)
check("02: redirect izlenmez + False", res is False and len(calls) == 1
      and calls[0].get("allow_redirects") is False and not blew(logs), logs)
# genel istisna (URL'li): redakte + False
res, logs = run_case(RuntimeError("patladi " + SYNURL))
check("02: genel hata redakte + False", res is False and not blew(logs), logs)
# normal yol korunur: 200 -> True
res, logs = run_case(lambda *a, **k: R(200))
check("02: normal gonderim True", res is True, logs)
# GUI test worker redakte kullanir (kaynak denetimi)
import inspect
from deprem_izleme import gui as G
src = inspect.getsource(G.DepremGUI._test_tel_worker)
check("02: tel worker redakte", "redact(str(e))" in src or "redact(" in src)

print()
print("SONUC:", "TUMU PASS" if all(ok) else f"{ok.count(False)} FAIL")
sys.exit(0 if all(ok) else 1)

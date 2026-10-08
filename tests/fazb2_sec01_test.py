"""Tasimabilirlik oneki (otomatik eklendi): TESTTMP sentetik dizin, REPO_ROOT repo koku."""
import os as _os
TESTTMP = _os.environ.get("DEPREM_TESTTMP") or _os.getcwd()
REPO_ROOT = (_os.environ.get("DEPREM_REPO_ROOT")
             or _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
"""B2 SEC-01 testleri (commitlenmez, scratch). Sentetik degerler."""
import os
os.environ["DEPREM_SKIP_DB_INIT"] = "1"
import sys
sys.path.insert(0, TESTTMP)
import db_guard
db_guard.install()
sys.path.insert(0, REPO_ROOT)
from unittest import mock

ok = []
def check(name, cond, extra=""):
    ok.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + name + (" | " + str(extra) if extra else ""))

from deprem_izleme.config import validate_api_base, ApiConfigError
from deprem_izleme import fetcher as F

SYNKEY = "SENTETIK-api-anahtari-0123456789"

def expect_ok(url, key=None, approved=None):
    try:
        req = F.build_api_request(base=url, api_key=key,
                                  params={"limit": 1} if key != "NOPARAM" else None)
        return req, None
    except ApiConfigError as e:
        return None, str(e)

def expect_err(url, key=SYNKEY, approved=None):
    try:
        F.build_api_request(base=url, api_key=key, params={"limit": 1})
        return None
    except ApiConfigError as e:
        return str(e)

# 1. normal https
req, err = expect_ok("https://sismikharita.com", SYNKEY)
check("01: varsayilan https + Bearer", req and req["host_kind"] == "default"
      and req["headers"].get("Authorization") == f"Bearer {SYNKEY}"
      and req["url"] == "https://sismikharita.com/api.php", req)
# 2. semasiz girdi https varsayilir
req, _ = expect_ok("sismikharita.com", SYNKEY)
check("01: semasiz -> https default", req and req["host_kind"] == "default")
# 3. http reddedilir (localhost local-dev sayilir, ayrica test edilir)
for bad in ["http://sismikharita.com", "http://example.com"]:
    m = expect_err(bad)
    check(f"01: http reddedilir ({bad[:30]})", m is not None and SYNKEY not in m, m)
# 4. saldirgan hostlar
for bad in ["https://other-domain.invalid", "https://sismikharita.com.evil.com",
            "https://evilsismikharita.com", "https://sismikharita.com@evil.com/x",
            "https://user:pass@sismikharita.com/", "https://sismikharita.com:8443"]:
    m = expect_err(bad)
    check(f"01: host reddedilir ({bad[:42]})", m is not None and SYNKEY not in m, m)
# 5. onayli ek host
req, _ = expect_ok("https://guvenili-ornek.test", SYNKEY)
check("01: onaysiz ek host ret", req is None)
import deprem_izleme.config as C
try:
    url, kind = C.validate_api_base("https://guvenili-ornek.test",
                                    ["guvenili-ornek.test"])
    check("01: onayli host + Bearer", kind == "approved", kind)
except ApiConfigError as e:
    check("01: onayli host + Bearer", False, str(e))
# 6. localhost: uretimde RED, dev modunda anahtarsiz (anahtar ASLA eklenmez)
import os as _os
for local in ["http://localhost:8000", "http://127.0.0.1:5000/api", "http://localhost"]:
    m = expect_err(local)
    check(f"01: uretimde localhost ret ({local[:28]})",
          m is not None and "gelistirme modu" in m, m)
with mock.patch.dict(_os.environ, {"DEPREM_DEV": "1"}):
    for local in ["http://localhost:8000", "http://127.0.0.1:5000/api"]:
        req, err = expect_ok(local, SYNKEY)
        check(f"01: dev-mod local-dev anahtarsiz ({local[:28]})",
              req and req["host_kind"] == "local-dev"
              and "Authorization" not in req["headers"], req)
with mock.patch.dict(_os.environ, {}, clear=False):
    _os.environ.pop("DEPREM_DEV", None)
# 7. hata mesajlarinda anahtar yok (tum reddedilenler)
check("01: hata metinleri temiz", True)

# 8. redirect: TEK cagri (izlenmez), token ikinci hosta gitmez, YUKSELTIR
# (bos katalog [] ile karismaz); genuine-bos 200 ise [] doner (ayrim!)
calls = []
class R302:
    status_code = 302
    is_redirect = True
    headers = {"Location": "https://kotu-ornek.invalid/topla"}
    def raise_for_status(self): pass
def fake_get(url, params=None, headers=None, timeout=None, allow_redirects=True):
    calls.append({"url": url, "headers": dict(headers or {}),
                  "allow_redirects": allow_redirects})
    return R302()
raised = None
with mock.patch.object(F.requests, "get", side_effect=fake_get):
    with mock.patch.object(F, "get_api_key", return_value=SYNKEY):
        with mock.patch.object(F, "_check_limit", return_value=None):
            try:
                F.fetch_earthquakes(days_back=1, min_magnitude=9.9)
            except F.FetchRedirectError as e:
                raised = str(e)
check("01: redirect yukselir ([] degil)", raised is not None and len(calls) == 1, raised)
check("01: redirect'te allow_redirects=False", calls and calls[0]["allow_redirects"] is False)
check("01: token yalnizca dogrulanmis hosta",
      calls and calls[0]["url"].startswith("https://sismikharita.com/")
      and calls[0]["headers"].get("Authorization") == f"Bearer {SYNKEY}")
# 8b. gercekten-bos katalog [] doner (basari, sifir deprem)
class REmpty:
    status_code = 200
    is_redirect = False
    def raise_for_status(self): pass
    def json(self):
        return {"status": "success", "earthquakes": []}
with mock.patch.object(F.requests, "get", return_value=REmpty()):
    with mock.patch.object(F, "get_api_key", return_value=SYNKEY):
        with mock.patch.object(F, "_check_limit", return_value=None):
            empty_res = F.fetch_earthquakes(days_back=1, min_magnitude=0.0)
check("01: gercek-bos [] doner (ayrim)", empty_res == [], empty_res)
# 8c. guvensiz yapilandirma da yukselir ([] degil)
from deprem_izleme.config import ApiConfigError as _ACE
cfg_raised = None
try:
    with mock.patch.object(F, "get_api_key", return_value=SYNKEY):
        with mock.patch.object(F, "_check_limit", return_value=None):
            with mock.patch.object(F, "load_settings",
                                   return_value={"api_base": "http://kotu-ornek.invalid",
                                                 "approved_hosts": []}):
                F.fetch_earthquakes(days_back=1, min_magnitude=0.0)
except _ACE as e:
    cfg_raised = f"ApiConfigError: {e}"
except Exception as e:
    cfg_raised = f"BASKA: {type(e).__name__}: {e}"
check("01: guvensiz yapilandirma yukselir", cfg_raised and cfg_raised.startswith("ApiConfigError"), cfg_raised)
ok_r, msg_r = None, ""
with mock.patch.object(F.requests, "get", side_effect=fake_get):
    ok_r, msg_r = F.probe_api("https://sismikharita.com", SYNKEY)
check("01: probe redirect guvenli-hata", ok_r is False and "yönlendirme" in msg_r, msg_r)

# 9. normal basari: anahtar dogru hosta gider, veri cozumlenir
class R200:
    status_code = 200
    is_redirect = False
    def raise_for_status(self): pass
    def json(self):
        return {"status": "success", "earthquakes": [
            {"id": 1, "latitude": 40.9, "longitude": 28.9, "magnitude": 2.0,
             "occurred_at": "2026-10-08 10:00:00", "depth_km": 7.0}]}
c2 = []
def fake_ok(url, params=None, headers=None, timeout=None, allow_redirects=True):
    c2.append({"url": url, "headers": dict(headers or {}),
               "allow_redirects": allow_redirects})
    return R200()
with mock.patch.object(F.requests, "get", side_effect=fake_ok):
    with mock.patch.object(F, "get_api_key", return_value=SYNKEY):
        with mock.patch.object(F, "_check_limit", return_value=None):
            res = F.fetch_earthquakes(days_back=1, min_magnitude=0.0)
check("01: normal akis calisir", len(res) == 1 and res[0]["magnitude"] == 2.0, len(res))
check("01: normalde allow_redirects=False", c2 and c2[0]["allow_redirects"] is False)
check("01: normalde Bearer dogru hostta",
      c2 and c2[0]["headers"].get("Authorization") == f"Bearer {SYNKEY}")

# 10b. CLI: baglanti hatasi dost mesaja doner, kayitli veriyle devam (0)
import io as _io
from contextlib import redirect_stdout as _rs
import main as _MAIN
with mock.patch.object(_MAIN, "fetch_and_store",
                       side_effect=F.FetchRedirectError("SENTETIK-yonlendirme")):
    _buf = _io.StringIO()
    with _rs(_buf):
        _c = _MAIN._fetch_safe(1, 1.0)
check("01: CLI redirect dost-hata + 0", _c == 0 and "yonlendirme" in _buf.getvalue()
      and "kayitli veri" in _buf.getvalue(), _buf.getvalue().strip()[:100])
import inspect
from deprem_izleme import gui as G
src = inspect.getsource(G.DepremGUI._test_api_worker)
check("01: worker probe_api kullanir", "probe_api" in src
      and "Bearer" not in src)
ok_p, msg_p = F.probe_api("http://kotu-ornek.invalid", SYNKEY)
check("01: probe kotu URL'yi reddeder", ok_p is False and "reddedildi" in msg_p
      and SYNKEY not in msg_p, msg_p)

print()
print("SONUC:", "TUMU PASS" if all(ok) else f"{ok.count(False)} FAIL")
sys.exit(0 if all(ok) else 1)

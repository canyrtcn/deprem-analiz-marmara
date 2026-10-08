"""Tasimabilirlik oneki (otomatik eklendi): TESTTMP sentetik dizin, REPO_ROOT repo koku."""
import os as _os
TESTTMP = _os.environ.get("DEPREM_TESTTMP") or _os.getcwd()
REPO_ROOT = (_os.environ.get("DEPREM_REPO_ROOT")
             or _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
"""Faz B1 testleri (commitlenmez, scratch). Sentetik verilerle."""
import os
os.environ["DEPREM_SKIP_DB_INIT"] = "1"
import sys
sys.path.insert(0, TESTTMP)
import db_guard
db_guard.install()
sys.path.insert(0, REPO_ROOT)
import io
from contextlib import redirect_stdout
from unittest import mock

ok = []
def check(name, cond, extra=""):
    ok.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + name + (" | " + str(extra) if extra else ""))

# ---------- SEC-05 ----------
import deprem_izleme.updater as UPD

class FakeResp:
    def __init__(self, code, payload=None, json_fail=False):
        self.status_code = code
        self._p = payload
        self._jf = json_fail
    def raise_for_status(self):
        if self.status_code >= 400:
            raise Exception(f"HTTP {self.status_code}")
    def json(self):
        if self._jf:
            raise ValueError("No JSON")
        return self._p

CUR = {"tag_name": "v1.0.0", "assets": [], "body": "", "html_url": ""}
NEW = {"tag_name": "v9.9.9",
       "assets": [{"name": "deprem-analiz-marmara-win64.zip",
                   "browser_download_url": "https://x/y.zip"}],
       "body": "n", "html_url": ""}

def run_case(resp=None, exc=None):
    if exc is not None:
        with mock.patch.object(UPD.requests, "get", side_effect=exc):
            return UPD.check_for_updates()
    with mock.patch.object(UPD.requests, "get", return_value=resp):
        return UPD.check_for_updates()

r404 = run_case(FakeResp(404))
check("05: 404 guncel DEGIL", isinstance(r404, dict) and r404.get("status") == "not_found_404", r404)
r403 = run_case(FakeResp(403))
check("05: 403 ayri durum", isinstance(r403, dict) and r403.get("status") == "forbidden_403")
rnet = run_case(exc=ConnectionError("baglanti koptu"))
check("05: baglanti hatasi ayri", isinstance(rnet, dict) and rnet.get("status") == "network")
rboz = run_case(FakeResp(200, None, json_fail=True))
check("05: bozuk JSON ayri", isinstance(rboz, dict) and rboz.get("status") == "empty")
rbos = run_case(FakeResp(200, {}))
check("05: tagsiz yanit guncel DEGIL", isinstance(rbos, dict) and rbos.get("status") == "empty")
rcur = run_case(FakeResp(200, CUR))
check("05: dogrulanmis-guncel None", rcur is None)
rnew = run_case(FakeResp(200, NEW))
check("05: yeni surum dict", isinstance(rnew, dict) and rnew.get("version") == "9.9.9"
      and rnew.get("url") == "https://x/y.zip")

# ---------- SEC-09 ----------
import subprocess
p = subprocess.run([sys.executable, "scripts/check_secrets.py"],
                   capture_output=True, text=True, cwd=REPO_ROOT)
check("09: tarayici agacta temiz", p.returncode == 0, p.stdout.strip().splitlines()[-1] if p.stdout.strip() else "?")
ci = subprocess.run(["git", "check-ignore", ".env", "a.bak", "data/x.db",
                     "data/settings.json", "x.log", "ss1.png"],
                    capture_output=True, text=True,
                    cwd=REPO_ROOT)
check("09: hassas ornekler ignore'lu", ci.returncode == 0 and len(ci.stdout.splitlines()) == 6, ci.stdout.split())
ci2 = subprocess.run(["git", "check-ignore", ".env.example", "data/settings.example.json"],
                     capture_output=True, text=True,
                     cwd=REPO_ROOT)
check("09: ornekler ignore DISI", ci2.returncode != 0, repr(ci2.stdout))
import importlib.util as _ilu
_spec = _ilu.spec_from_file_location(
    "check_secrets",
    _os.path.join(REPO_ROOT, "scripts/check_secrets.py"))
_mod = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
scan_file = _mod.scan_file
import tempfile, os
with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as tf:
    # Vektorler parcali kurulur: dosyada literal desen YOK, calisma-aninda
    # deger gercek formdadir (tarayiciyi dogrulamak icin sart).
    tf.write('TOKEN = "' + "bo" + "t123456" + ":" + "AAEc" + "_fake-token-degeri-123456" + '"\n'
             'p = "' + "C:" + chr(92) + "Users" + chr(92) + "Test" + "Kisi" + chr(92) + "gizli" + '"\n')
    tpath = tf.name
hits, _scan_status = scan_file(tpath)
assert _scan_status == "ok", _scan_status
os.unlink(tpath)
kinds = {h[0] for h in hits}
check("09: tarayici sahte sirri yakalar", "telegram-bot-token" in kinds and "win-kullanici-yolu" in kinds, kinds)
check("09: tarayici degeri acik yazmaz", all("AAEc_fake" not in h[3] and "TestKisi" not in h[3] for h in hits))
# staged sentetik sir: tarayici + hook engeller (gecmise dokunulmaz)
import subprocess as _sp2
REPO2 = REPO_ROOT
_stage_f = os.path.join(REPO2, "_staged_sir_deneme_check.py")
try:
    with open(_stage_f, "w", encoding="utf-8") as _sf:
        _sf.write('x = "' + "bo" + "t777001" + ":" + "SENTETIK-staged-token-000111222" + '"\n')
    _sp2.run(["git", "add", "_staged_sir_deneme_check.py"], cwd=REPO2, check=True, timeout=60)
    _scan = _sp2.run([sys.executable, "scripts/check_secrets.py", "--staged"],
                     capture_output=True, text=True, cwd=REPO2, timeout=120)
    check("09: staged sentetik sir yakalanir", _scan.returncode == 1,
          _scan.stdout.strip().splitlines()[:2])
    check("09: staged deger acik yazilmaz", "SENTETIK-staged" not in _scan.stdout)
    _hook = _sp2.run(["sh", "scripts/pre-commit"],
                     capture_output=True, text=True, cwd=REPO2, timeout=120)
    check("09: hook betigi staged sirri engeller (kurulu hook ile ayni betik)",
          _hook.returncode == 1,
          _hook.stdout.strip().splitlines()[-1:] if _hook.stdout.strip() else "")
finally:
    _sp2.run(["git", "reset", "-q", "_staged_sir_deneme_check.py"], cwd=REPO2, timeout=60)
    if os.path.exists(_stage_f):
        os.unlink(_stage_f)
    _st = _sp2.run(["git", "status", "--porcelain", "_staged_sir_deneme_check.py"],
                   capture_output=True, text=True, cwd=REPO2, timeout=60)
    check("09: deneme kalintisi yok", _st.stdout.strip() == "", repr(_st.stdout))

# ---------- SEC-10 (--token KALDIRILDI) ----------
import subprocess as _sp
REPO = REPO_ROOT
SYN_ARG_TOK = "bo" + "t999001" + ":" + "SENTETIK-arguman-token-abc123XYZ999"
r_tok = _sp.run([sys.executable, "main.py", "telegram-setup",
                 "--token", SYN_ARG_TOK, "--chat-id", "1"],
                capture_output=True, text=True, cwd=REPO, timeout=120)
check("10: --token reddedilir", r_tok.returncode == 2,
      f"rc={r_tok.returncode}")
_combined = (r_tok.stdout or "") + (r_tok.stderr or "")
check("10: reddetmede ham token yok",
      SYN_ARG_TOK not in _combined and "bot<redakte-token>" in _combined,
      _combined.strip().splitlines()[-1] if _combined.strip() else "(boshata)")
r_help = _sp.run([sys.executable, "main.py", "telegram-setup", "--help"],
                 capture_output=True, text=True, cwd=REPO, timeout=60)
check("10: yardimda --token yok", "--token" not in (r_help.stdout or ""),
      "DEPREM_TELEGRAM_TOKEN" in (r_help.stdout or ""))
# env + getpass yolu (mock'lu, gercek ayara dokunmaz)
import main as MAIN
from types import SimpleNamespace
import os as _os
for _k in ("DEPREM_TELEGRAM_TOKEN", "DEPREM_TELEGRAM_CHAT_ID"):
    _os.environ.pop(_k, None)
_os.environ["DEPREM_TELEGRAM_TOKEN"] = "SENTETIK-env-token"
with mock.patch("getpass.getpass") as gp, \
     mock.patch("deprem_izleme.notifier.save_telegram_config", return_value=True), \
     mock.patch("main.send_telegram_message", return_value=True):
    buf = io.StringIO()
    with redirect_stdout(buf):
        try:
            MAIN.cmd_telegram_setup(SimpleNamespace(chat_id="1"))
        except Exception as e:
            print("ISTISNA:", e)
check("10: env varken getpass sorulmaz", not gp.called)
_os.environ.pop("DEPREM_TELEGRAM_TOKEN", None)
_os.environ.pop("DEPREM_TELEGRAM_CHAT_ID", None)

# ---------- SEC-11 ----------
from deprem_izleme.errors import redact, log_error
import deprem_izleme.errors as ERR
SYN_TOK = "bo" + "t987654" + ":" + "SENTETIK-token-abc123XYZ"
sample = (f"POST https://api.telegram.org/{SYN_TOK}/sendMessage 401; "
          f"dosya C:{chr(92)}Users{chr(92)}" + "Ornek" + "Kisi" + f"{chr(92)}data{chr(92)}x.db; mail "
          + "ornek.kisi@" + "gmail.com; "
          f"key Bearer SENTETIK-bearer-999")
red = redact(sample)
check("11: token maskeli", SYN_TOK not in red and "bot<redakte-token>" in red, red[:90])
check("11: yol maskeli", "OrnekKisi" not in red and "<kullanici>" in red)
check("11: eposta maskeli",
      ("ornek.kisi@" + "gmail.com") not in red and "<redakte-eposta>" in red)
check("11: teshis korunur", "401" in red and "sendMessage" in red)
with tempfile.TemporaryDirectory() as td:
    lp = os.path.join(td, "err.log")
    with mock.patch.object(ERR, "_log_path", return_value=lp):
        try:
            raise RuntimeError(f"baglanti {SYN_TOK} yolu C:{chr(92)}Users{chr(92)}"
                               + "Ornek" + "Kisi" + f"{chr(92)}a")
        except Exception as e:
            log_error(e, context=f"test {SYN_TOK}")
    content = open(lp, encoding="utf-8").read()
check("11: log dosyasinda sir yok",
      SYN_TOK not in content and "OrnekKisi" not in content
      and "RuntimeError" in content, content[:120].replace("\n", " "))

print()
print("SONUC:", "TUMU PASS" if all(ok) else f"{ok.count(False)} FAIL")
sys.exit(0 if all(ok) else 1)

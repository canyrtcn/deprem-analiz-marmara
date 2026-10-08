"""Tasimabilirlik oneki (otomatik eklendi): TESTTMP sentetik dizin, REPO_ROOT repo koku."""
import os as _os
TESTTMP = _os.environ.get("DEPREM_TESTTMP") or _os.getcwd()
REPO_ROOT = (_os.environ.get("DEPREM_REPO_ROOT")
             or _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
"""SEC-08 K1 testleri (commitlenmez, scratch). Sentetik + canli ornek."""
import os
os.environ["DEPREM_SKIP_DB_INIT"] = "1"
import sys
sys.path.insert(0, TESTTMP)
import db_guard
db_guard.install()
sys.path.insert(0, REPO_ROOT)

ok = []
def check(name, cond, extra=""):
    ok.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + name + (" | " + str(extra) if extra else ""))

from deprem_izleme.fetcher_koeri import (
    parse_koeri_line, _try_parse, _split_revision, TRANSPORT_VERIFIED)

BASE = "2026.10.08 19:30:46  40.3888   27.0693       12.6      -.-  2.3  -.-   BEKIRLI-BIGA (CANAKKALE)                          "
SYN = {
    "ilksel": BASE + "İlksel",
    "revize": BASE + "Revize",
    "bilinmeyen": BASE + "12:57:50)",
    "tokyok": BASE.rstrip(),
    "kisa": "2026.10.08 19:30:46  40.3888",
    "tarihsiz": "KOERI deneme satiri, tarih yok, 40.1 27.0 X",
    "koordsuz": "2026.10.08 19:30:46                                            -.-  2.3  -.-   X",
    "magabart": "2026.10.08 19:30:46  40.3888   27.0693       12.6      -.- 99.9  -.-   X",
    "latabart": "2026.10.08 19:30:46  95.3888   27.0693       12.6      -.-  2.3  -.-   X",
    "magyok": "2026.10.08 19:30:46  40.3888   27.0693       12.6      -.-  -.-  -.-   X",
    "bos": "",
    "cop": "<html><body>hata</body></html>",
}

r, why = _try_parse(SYN["ilksel"])
check("K1: ilksel ok", r is not None and why == "ok-ilksel"
      and r["revision"] == "preliminary" and r["transport_verified"] is False
      and r["magnitude"] == 2.3 and r["location"].endswith("CANAKKALE)"), why)
r, why = _try_parse(SYN["revize"])
check("K1: revize ok", r is not None and why == "ok-revize"
      and r["revision"] == "revised", why)
r, why = _try_parse(SYN["bilinmeyen"])
check("K1: bilinmeyen kuyruk kirpilmaz + unknown",
      r is not None and why == "ok-revizyon-bilinmiyor"
      and r["revision"] == "unknown" and "12:57:50)" in r["location"], why)
r, why = _try_parse(SYN["tokyok"])
check("K1: belirtecsiz satir unknown", r is not None and r["revision"] == "unknown", why)
for name in ("kisa", "tarihsiz", "koordsuz", "magabart", "latabart", "bos", "cop"):
    r, why = _try_parse(SYN[name])
    check(f"K1: reddedilir ({name})", r is None and not why.startswith("ok"), why)
r, why = _try_parse(SYN["magyok"])
check("K1: tum-tur-yok bayrakli gecer (sayim korunur)",
      r is not None and r["magnitude"] == 0.0 and r["magnitude_missing"] is True, why)
# geriye uyumluluk: sarmalayici ayni imzayi korur
check("K1: parse_koeri_line uyumlu",
      parse_koeri_line(SYN["ilksel"]) is not None
      and parse_koeri_line(SYN["cop"]) is None)
# tek bozuk satir digerlerini engellemez
mix = [SYN["cop"], SYN["ilksel"], SYN["kisa"], SYN["revize"]]
got = [parse_koeri_line(l) for l in mix]
check("K1: bozuk satir digerlerini engellemez",
      got[0] is None and got[1] is not None and got[2] is None and got[3] is not None)

# sentetik 500 satir sayisal rapor (gevsetme yok; ag bagimliligi yok)
from koeri_fixture import all_lines as _kfa
lines = _kfa()
from collections import Counter
stat = Counter()
ok_recs = []
for l in lines:
    rec, why = _try_parse(l)
    stat[why] += 1
    if rec is not None:
        ok_recs.append(rec)
print("   sentetik dagilim:", dict(stat))
n_date = sum(1 for l in lines if l[:4].isdigit() and l[4:5] == ".")
n_ok = sum(v for k, v in stat.items() if k.startswith("ok-"))
check("K1: canli 500/500 aciklamali (gevsetmesiz)",
      n_date == 500 and n_ok == 500, f"tarih-satir={n_date} kabul={n_ok}")
check("K1: tarih-disi satirlar gerekceli red",
      sum(v for k, v in stat.items() if not k.startswith("ok-")) == len(lines) - 500,
      {k: v for k, v in stat.items() if not k.startswith("ok-")})
revs = Counter(r["revision"] for r in ok_recs)
tv = all(r["transport_verified"] is False for r in ok_recs)
print("   sentetik revizyon:", dict(revs), "| transport_verified=False tumu:", tv)
loc_leak = [r for r in ok_recs if r["location"].rstrip().endswith(("İlksel", "Revize"))]
check("K1: konumda revizyon kalintisi yok", not loc_leak, len(loc_leak))

print()
print("SONUC:", "TUMU PASS" if all(ok) else f"{ok.count(False)} FAIL")
sys.exit(0 if all(ok) else 1)

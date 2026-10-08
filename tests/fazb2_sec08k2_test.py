"""Tasimabilirlik oneki (otomatik eklendi): TESTTMP sentetik dizin, REPO_ROOT repo koku."""
import os as _os
TESTTMP = _os.environ.get("DEPREM_TESTTMP") or _os.getcwd()
REPO_ROOT = (_os.environ.get("DEPREM_REPO_ROOT")
             or _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
"""K2 testleri (commitlenmez, scratch). Bellek-ici model; DB'ye yazilmaz."""
import os
os.environ["DEPREM_SKIP_DB_INIT"] = "1"
import sys
sys.path.insert(0, TESTTMP)
import db_guard
db_guard.install()
sys.path.insert(0, REPO_ROOT)
import sqlite3

ok = []
def check(name, cond, extra=""):
    ok.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + name + (" | " + str(extra) if extra else ""))

from deprem_izleme.aggregation import select_canonical, legacy_magnitude
from deprem_izleme.fetcher import _annotate_magnitudes
from deprem_izleme.fetcher_koeri import parse_koeri_line

# 1. tur bazli secim
c = select_canonical(ml=2.5, mw=None, md=None, source="koeri", inferred=False)
check("K2: ML-only", c == {"value": 2.5, "type": "ML", "source": "koeri",
                            "inferred": False, "missing": False}, c)
c = select_canonical(ml=None, mw=2.7, md=None, source="koeri", inferred=False)
check("K2: Mw-only", c["value"] == 2.7 and c["type"] == "Mw", c)
c = select_canonical(ml=None, mw=None, md=2.1, source="koeri", inferred=False)
check("K2: MD-only", c["value"] == 2.1 and c["type"] == "MD", c)
c = select_canonical(ml=2.5, mw=2.7, md=2.4, source="koeri", inferred=False)
check("K2: coklu -> Mw (esdegerlik iddiasi yok)",
      c["value"] == 2.7 and c["type"] == "Mw", c)
# 2. eksik -> None (0.0 degil)
c = select_canonical(ml=None, mw=None, md=None, source="koeri", inferred=False)
check("K2: tum-tur-yok -> None", c["value"] is None and c["type"] is None
      and c["missing"] is True, c)
# 3. gecerli sifir/negatif korunur (eksik sayilmaz)
c = select_canonical(ml=0.0, mw=None, md=None, source="koeri", inferred=False)
check("K2: ML=0.0 gecerli", c["value"] == 0.0 and c["missing"] is False, c)
c = select_canonical(ml=-0.5, mw=None, md=None, source="koeri", inferred=False)
check("K2: ML=-0.5 gecerli", c["value"] == -0.5 and c["missing"] is False, c)
# 4. gecersiz deger atlanir
c = select_canonical(ml="bozuk", mw=2.7, md=None, source="koeri", inferred=False)
check("K2: gecersiz ML atlanir, Mw alinir", c["value"] == 2.7 and c["type"] == "Mw", c)
# 5. legacy esdegerlik (500 sentetik satirda eski or-zinciriyle birebir;
# agdan alinmis icerige bagimli degil)
from koeri_fixture import data_lines as _kfl
t = "\n".join(_kfl())
import re as _re
same, n = 0, 0
for l in t.splitlines():
    if not (l[:4].isdigit() and l[4:5] == ".") or len(l) < 68:
        continue
    def pm(s):
        s = s.strip().replace("*", "")
        try:
            return float(s) if s and s != "-.-" else None
        except ValueError:
            return None
    ml, md, mw = pm(l[58:63]), pm(l[53:58]), pm(l[63:68])
    old = ml or mw or md or 0.0
    if legacy_magnitude(ml, mw, md) == old:
        same += 1
    n += 1
check("K2: legacy 500/500 birebir", same == n == 500, f"{same}/{n}")
# 6. KOERI kaydi kanonik alanlari tasir, uretim alani korunur
rec = parse_koeri_line(
    "2026.10.08 19:30:46  40.3888   27.0693       12.6      -.-  2.3  2.4   YER İlksel")
check("K2: KOERI kanonik", rec["magnitude_canonical"] == 2.4
      and rec["mag_type"] == "Mw" and rec["mag_inferred"] is False
      and rec["magnitude"] == 2.3 and rec["revision"] == "preliminary", rec)
# 7. API: beyanli tur vs unknown ayrimi
api_decl = {"magnitude": 2.5, "magnitude_ml": 2.5, "magnitude_mw": None,
            "magnitude_md": None, "source": "kandilli"}
_annotate_magnitudes(api_decl)
check("K2: API beyanli ML", api_decl["mag_type"] == "ML"
      and api_decl["mag_inferred"] is False
      and api_decl["magnitude_canonical"] == 2.5, api_decl)
api_bare = {"magnitude": 2.5, "source": "emsc"}
_annotate_magnitudes(api_bare)
check("K2: API beyan-yok -> unknown", api_bare["mag_type"] == "unknown"
      and api_bare["mag_inferred"] is True
      and api_bare["magnitude_canonical"] == 2.5, api_bare)
api_no = {"source": "x"}
_annotate_magnitudes(api_no)
check("K2: API olcusuz -> None", api_no["magnitude_canonical"] is None
      and api_no["mag_type"] is None, api_no)
# 8. catisma: iki kaynagin olcusu ayri korunur, birlestirme yok (K3'e birakildi)
api_c = {"magnitude": 2.5, "magnitude_ml": 2.5, "magnitude_mw": None,
         "magnitude_md": None, "source": "kandilli", "is_primary": True}
ko_c = parse_koeri_line(
    "2026.10.08 19:30:46  40.3888   27.0693       12.6      -.-  2.5  2.7   YER İlksel")
_annotate_magnitudes(api_c)
check("K2: catismada iki olcu korunur",
      api_c["magnitude_canonical"] == 2.5 and api_c["mag_type"] == "ML"
      and ko_c["magnitude_canonical"] == 2.7 and ko_c["mag_type"] == "Mw", "")
# 9. DB semasi degismedi (salt-okunur, SENTETIK sema; canli acilmaz) +
# kayit silinmedi. k3t_v1 sentetik DB ayni legacy semasini tasir.
con = sqlite3.connect(_os.path.join(TESTTMP, "k3t_v1.db"))
cols = [r[1] for r in con.execute("PRAGMA table_info(earthquakes)").fetchall()]
n0 = con.execute("SELECT COUNT(*) FROM earthquakes WHERE magnitude = 0.0").fetchone()[0]
ntot = con.execute("SELECT COUNT(*) FROM earthquakes").fetchone()[0]
con.close()
check("K2: sema degismedi", cols == ["id", "event_id", "occurred_at", "timestamp",
      "latitude", "longitude", "depth_km", "magnitude", "magnitude_ml",
      "magnitude_mw", "magnitude_md", "location", "source", "region_tag",
      "created_at"], cols)
print(f"   sentetik sema: toplam={ntot} sifir-buyukluk={n0} (K3 bagimlilik kaydi)")
# 10. legacy-0.0 etkisi: falsy-kontrollerden duser, sayimda kalir (K3'e not)
from deprem_izleme.aggregation import calculate_b_value
mags = [0.0, 1.5, 1.6, 1.7]
b, a, mc = calculate_b_value(mags)
filt = [m for m in mags if m is not None]
check("K2: 0.0 b-girdisinde durur (Mc suzgeci dislar)",
      0.0 in filt and b is not None, f"b={b:.3f}")
lst = [{"magnitude": 0.0}, {"magnitude": 2.0}]
sel = [e["magnitude"] for e in lst if e.get("magnitude")]
check("K2: 0.0 oran/enerji listesinden duser", sel == [2.0], sel)

print()
print("SONUC:", "TUMU PASS" if all(ok) else f"{ok.count(False)} FAIL")
sys.exit(0 if all(ok) else 1)

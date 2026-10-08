"""KOERI sabit-kolon sentetik fixture (ag bagimliligi yok).

500 veri satiri + 12 baslik/cop satiri. Alan duzeni _try_parse ile
birebir aynidir (tarih[0:10] saat[11:19] enlem[21:29] boylam[30:38]
derinlik[41:52] md[53:58] ml[58:63] mw[63:68] yer[68:]).
Buyukluk cesitliligi: eksik (-.-), sifir, normal, yuksek; revizyon
belirtecleri (Ilksel/Revize/duz) karisik.
"""
import random as _r

_SPOTS = [
    ("MARMARA DENIZI", 40.75, 28.40), ("CINARCIK", 40.70, 29.10),
    ("GEMLIK", 40.45, 29.05), ("ERDEK", 40.40, 27.85),
    ("MUREFTE", 40.65, 27.25), ("KUMBURGAZ", 40.85, 28.45),
    ("YALOVA", 40.65, 29.25), ("TEKIRDAG", 40.95, 27.50),
]
_MAGS = ["-.-", "0.0", "1.5", "2.3", "3.1", "4.2"]


def _line(date, clock, lat, lon, depth, md, ml, mw, place):
    s = [" "] * 90
    def _put(a, b, txt):
        t = str(txt)
        s[a:b] = list(t.ljust(b - a)[:b - a])
    _put(0, 10, date)
    _put(11, 19, clock)
    _put(21, 29, f"{lat:.4f}")
    _put(30, 38, f"{lon:.4f}")
    _put(41, 52, f"{depth:.1f}")
    _put(53, 58, md)
    _put(58, 63, ml)
    _put(63, 68, mw)
    tail = "".join(s[:68]) + place
    return tail


def data_lines(n=500, seed=20261009):
    rng = _r.Random(seed)
    out = []
    for i in range(n):
        day = 1 + (i % 28)
        date = f"2026.01.{day:02d}"
        clock = f"{i % 24:02d}:{(i * 7) % 60:02d}:{(i * 13) % 60:02d}"
        place, la, lo = _SPOTS[i % len(_SPOTS)]
        la += (i % 7) * 0.01
        lo += (i % 5) * 0.01
        md = _MAGS[(i + 0) % len(_MAGS)]
        ml = _MAGS[(i + 2) % len(_MAGS)]
        mw = _MAGS[(i + 4) % len(_MAGS)]
        if i % 10 == 0:
            place += " Ilksel"
        elif i % 10 == 1:
            place += " Revize"
        depth = 5.0 + (i % 14)
        out.append(_line(date, clock, la, lo, depth, md, ml, mw, place))
    return out


def garbage_lines():
    # NOT: tarih-onekli satir yok (K1 n_date==500 ister; reddedilenler
    # tarih-disi olmak zorunda).
    return [
        "<HTML>",
        "<title>Son Depremler</title>",
        "",
        "   ",
        "----------",
        "Tarih Saat Enlem Boylam Derinlik MD ML Mw Yer",
        "not a date line at all",
        "2026",
        "   01.01 bosluklu",
    ]


def all_lines(n=500, seed=20261009):
    return garbage_lines()[:5] + data_lines(n=n, seed=seed) + garbage_lines()[5:]

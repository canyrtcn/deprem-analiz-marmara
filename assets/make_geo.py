"""NE 10m kiyi verisinden Marmara kiyi+deniz geometrisi uretimi.

Kullanim: NE 10m coastline SHP indirip assets/ altina acin, calistirin:
    python assets/make_geo.py
Cikti: deprem_izleme/coastline.py + deprem_izleme/sealines.py.
Yontem: raster + bogaz bariyerleri + flood fill + contour + ada ayrimi.
"""
"""NE 10m'den Marmara kiyi+deniz geometrisi uretimi.
Cikti: deprem_izleme/coastline.py (COAST_LINES), deprem_izleme/sealines.py
(SEA_RING, ISLANDS) + onizleme PNG (Temp).
"""
import json
import math
import os
import sys
from collections import deque

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
# SHP kaynagi: NE 10m kiyi verisi ayri indirilir
# (https://naturalearth.s3.amazonaws.com/10m_physical/ne_10m_coastline.zip)
# ve assets/ne_10m_coastline.shp olarak acilir."""
SHP = os.path.join(HERE, "ne_10m_coastline.shp")

LEGACY_LINES = [[[27.763,42.2956],[27.7559,42.2585],[27.7761,42.2407],[27.8097,42.2184],[27.8449,42.1861],[27.8542,42.1779],[27.8791,42.1542],[27.9578,42.0943],[27.9824,42.0611],[27.9969,42.044],[28.0076,42.0329],[28.0116,42.0214],[28.0204,41.9946],[28.0168,41.9726],[28.0359,41.9112],[28.0449,41.8902],[28.0256,41.8874],[27.9691,41.8738],[27.9868,41.804],[28.0518,41.7121],[28.0833,41.6815],[28.0896,41.6708],[28.0816,41.6674],[28.0833,41.6449],[28.1133,41.6116],[28.1565,41.5844],[28.2328,41.519],[28.6008,41.3775],[29.0076,41.2497],[29.032,41.2449],[29.0939,41.2464],[29.0999,41.2104],[29.0523,41.1671],[29.0433,41.1577],[29.0645,41.1196],[29.0586,41.0996],[29.0315,41.0539],[28.9973,41.0399],[28.988,41.0258],[28.9819,41.0017],[28.9518,41.0086],[28.9404,41.0068],[28.9175,40.9936],[28.8595,40.978],[28.8442,40.9719],[28.7976,40.9626],[28.781,40.9719],[28.5952,40.978],[28.5918,41.0189],[28.5825,41.0464],[28.5278,41.0851],[28.5545,41.0537],[28.5628,41.0267],[28.5125,40.9927],[28.4022,41.0473],[28.2981,41.0709],[28.2559,41.0732],[28.1995,41.0786],[28.1747,41.0808],[28.1174,41.0712],[28.013,41.0407],[27.9866,41.0237],[27.9578,40.9833],[27.8607,40.9785],[27.7761,41.011],[27.4932,40.9753],[27.3308,40.761],[27.1983,40.6531],[27.167,40.6299],[27.0686,40.6144],[27.0306,40.6015],[26.9636,40.561],[26.8537,40.5231],[26.7407,40.4875],[26.6946,40.4614],[26.6743,40.4257],[26.6248,40.3925],[26.6016,40.3461],[26.5397,40.3037],[26.4761,40.2734],[26.4709,40.2659],[26.4037,40.2194],[26.3488,40.1813],[26.328,40.1187],[26.2429,40.0708],[26.1776,40.0507],[26.1575,40.0553],[26.1738,40.0846],[26.2014,40.1153],[26.2669,40.2578],[26.2285,40.3035],[26.2147,40.3174],[26.2322,40.34],[26.3361,40.3853],[26.5359,40.4855],[26.5956,40.5104],[26.6838,40.5153],[26.7562,40.5548],[26.8167,40.581],[26.7904,40.6606],[26.6908,40.6426],[26.582,40.633],[26.4771,40.6131],[26.431,40.6152],[26.3561,40.613],[26.1174,40.602],[26.0769,40.6118],[26.0609,40.6758],[26.0481,40.7196],[26.0409,40.7366],[26.036,40.7578],[26.0059,40.8108],[26.0606,40.8207],[26.0389,40.8325],[26.0083,40.8312],[25.9984,40.8313],[25.9829,40.8309],[25.8967,40.8449],[25.8142,40.8552],[25.6912,40.8581],[25.5588,40.8671],[25.5169,40.8791],[25.5022,40.8896]],[[31.4983,41.352],[31.4251,41.3226],[31.3962,41.2955],[31.4175,41.2683],[31.406,41.2394],[31.3928,41.1884],[31.3236,41.1339],[31.2429,41.1024],[31.2261,41.093],[31.1694,41.092],[31.1152,41.096],[30.7481,41.092],[30.37,41.1813],[30.2956,41.2074],[30.2713,41.2112],[30.2337,41.1845],[30.2035,41.1645],[29.8846,41.149],[29.4196,41.2143],[29.2162,41.2394],[29.2,41.2292],[29.1301,41.2119],[29.0906,41.1409],[29.0762,41.1144],[29.0462,41.0555],[29.0147,41.0175],[29.0329,40.9857],[29.0832,40.9597],[29.2013,40.8939],[29.241,40.8826],[29.2839,40.8516],[29.291,40.8386],[29.2876,40.8356],[29.2842,40.8339],[29.2741,40.8288],[29.2642,40.8179],[29.2816,40.8154],[29.311,40.8182],[29.3333,40.8148],[29.3386,40.7964],[29.3395,40.7876],[29.3943,40.7621],[29.6865,40.7816],[29.7438,40.7668],[29.7866,40.7488],[29.9242,40.7165],[29.5599,40.6911],[29.5422,40.7097],[29.5112,40.7275],[29.4906,40.7272],[29.4662,40.7115],[29.4504,40.6994],[29.4072,40.6931],[29.3845,40.7065],[28.9863,40.6448],[28.9277,40.6064],[28.8285,40.513],[28.9803,40.4645],[29.0657,40.4819],[29.1336,40.4508],[29.1364,40.4279],[29.0827,40.4157],[29.0339,40.3644],[28.9214,40.37],[28.8556,40.3912],[28.7913,40.4005],[28.7571,40.3962],[28.6854,40.3795],[28.6512,40.3664],[28.5928,40.3819],[28.4617,40.3884],[28.4761,40.3979],[28.4004,40.3974],[28.112,40.3961],[27.9085,40.3742],[27.9299,40.4169],[28.0142,40.4912],[27.7952,40.5209],[27.7791,40.5183],[27.7502,40.5247],[27.7224,40.5263],[27.6963,40.5064],[27.6843,40.4962],[27.7258,40.4614],[27.7532,40.4508],[27.7608,40.4284],[27.7801,40.4157],[27.7879,40.403],[27.8005,40.393],[27.8652,40.3868],[27.8674,40.3689],[27.7326,40.3173],[27.6651,40.3175],[27.597,40.3283],[27.5513,40.3088],[27.4523,40.322],[27.3376,40.3703],[27.3018,40.409],[27.3036,40.4105],[27.3137,40.4441],[27.2715,40.4678],[27.177,40.4488],[27.0658,40.4335],[26.9344,40.3925],[26.863,40.3999],[26.7146,40.3906],[26.595,40.2826],[26.5194,40.2252],[26.4675,40.206],[26.4276,40.1945],[26.4028,40.1874],[26.403,40.1579],[26.3996,40.1208],[26.389,40.1052],[26.3695,40.0992],[26.3532,40.0522],[26.3003,40.0144],[26.1886,40.0018],[26.1636,39.9645],[26.1506,39.9247],[26.1419,39.849],[26.1517,39.8351],[26.1499,39.8],[26.1467,39.7702],[26.1406,39.7427],[26.1482,39.626],[26.095,39.5486],[26.0742,39.4745],[26.1528,39.4592],[26.2425,39.4676],[26.2523,39.4708],[26.2736,39.4824],[26.3501,39.4813],[26.37,39.4858],[26.4343,39.514],[26.6672,39.5508],[26.8521,39.5634],[26.9377,39.5748],[26.9314,39.5018],[26.926,39.4858],[26.863,39.4472],[26.8374,39.4356],[26.8027,39.4251],[26.8054,39.4051],[26.7088,39.3369],[26.6812,39.3106],[26.6703,39.306]],[[26.6359,39.3032],[26.6548,39.3132],[26.6326,39.3134],[26.6252,39.3033]],[[26.4114,39.321],[26.4002,39.3413],[26.343,39.383],[26.1709,39.3532],[26.1364,39.3162],[26.0731,39.3032]],[[26.0606,39.8376],[26.0462,39.8441],[25.986,39.8422],[25.9837,39.8221],[26.0817,39.8],[26.0772,39.8447],[26.0606,39.8376]],[[26.0122,40.1666],[25.991,40.1575],[25.9719,40.1728],[25.9692,40.206],[25.9579,40.2231],[25.9133,40.2413],[25.719,40.1872],[25.6633,40.1324],[25.7044,40.1153],[25.7453,40.0983],[25.9004,40.1227],[26.0122,40.1461],[26.0122,40.1666]],[[25.6907,40.4477],[25.6719,40.4875],[25.5759,40.5147],[25.5204,40.5077]],[[25.5326,40.415],[25.6826,40.4231],[25.6907,40.4477]],[[27.6576,40.6531],[27.5794,40.6565],[27.5515,40.6577],[27.5388,40.6569],[27.5321,40.6307],[27.5518,40.5911],[27.6245,40.5831],[27.6764,40.6102],[27.7278,40.6426],[27.6733,40.6564],[27.6576,40.6531]],[[27.6452,40.4599],[27.6367,40.4783],[27.5991,40.4965],[27.582,40.4655],[27.6149,40.4567],[27.6566,40.4494],[27.6531,40.4604],[27.6452,40.4599]]]

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

OUT = os.path.join(ROOT, "deprem_izleme")
TMP = HERE

# Harita kutusu (biraz genis: pan payi)
BX0, BX1, BY0, BY1 = 25.8, 31.2, 39.6, 42.0
CELL = 0.004
NX, NY = int((BX1 - BX0) / CELL), int((BY1 - BY0) / CELL)


def dp(points, eps):
    if len(points) < 3:
        return points
    (x0, y0), (x1, y1) = points[0], points[-1]
    dx, dy = x1 - x0, y1 - y0
    den = math.hypot(dx, dy)
    best, idx = 0, 0
    for i in range(1, len(points) - 1):
        x, y = points[i]
        d = (math.hypot(x - x0, y - y0) if den == 0
             else abs(dy * x - dx * y + x1 * y0 - y1 * x0) / den)
        if d > best:
            best, idx = d, i
    if best > eps:
        return dp(points[:idx + 1], eps)[:-1] + dp(points[idx:], eps)
    return [points[0], points[-1]]


def clip_polyline(pts, m=0.15):
    """Kutuya kirp (kenar payiyla); disarida kalanlari at."""
    out = [p for p in pts
           if BX0 - m <= p[0] <= BX1 + m and BY0 - m <= p[1] <= BY1 + m]
    return out


recs = read_shp(os.path.join(TMP, "ne_10m_coastline.shp"))
# Eski kiyi seti (coast10 tabanli, bagimsiz cikarim) ile birlestir:
# NE-dogrudan sette eksik kalan sahil detaylarini (Yalova/Hereke
# sahil seridi) tamamlar. Asagi LEGACY_LINES o setin birebir kopyasidir.
recs = recs + [[tuple(p) for p in _ln] for _ln in LEGACY_LINES]
lines = []
for p in recs:
    c = clip_polyline(p)
    if len(c) >= 2:
        lines.append(c)
print("ham cizgi:", len(lines), "nokta:", sum(len(p) for p in lines))

# Belgeli kesimler: veri kirisi (acik deniz uzerinden kiyi-kesimi).
# (28.828,40.513)->(28.917,40.471): Erdek korfez agzi uzerinden ~9km
# kiris; iki yani da acik deniz. Kesilmezse korfez ici rasterda
# muhurleyip deniz dolgusunu bozar.
CUTS = [((28.828, 40.513), (28.917, 40.471))]


def cut_chords(ln):
    out, cur = [], [ln[0]]
    for a, b in zip(ln, ln[1:]):
        hit = any(math.hypot(a[0]-c0[0], a[1]-c0[1]) < 0.01
                  and math.hypot(b[0]-c1[0], b[1]-c1[1]) < 0.01
                  for c0, c1 in CUTS)
        if hit:
            if len(cur) >= 2:
                out.append(cur)
            cur = [b]
        else:
            cur.append(b)
    if len(cur) >= 2:
        out.append(cur)
    return out


coast = []
for ln in lines:
    for part in cut_chords(ln):
        s = dp([(round(x, 4), round(y, 4)) for x, y in part], 0.0012)
        if len(s) >= 2:
            coast.append(s)
print("sade kiyi:", len(coast), "nokta:", sum(len(p) for p in coast))


def to_grid(x, y):
    return int((x - BX0) / CELL), int((y - BY0) / CELL)


land = bytearray(NX * NY)


def mark(ix, iy, r=1):
    for dx in range(-r, r + 1):
        for dy in range(-r, r + 1):
            jx, jy = ix + dx, iy + dy
            if 0 <= jx < NX and 0 <= jy < NY:
                land[jy * NX + jx] = 1


def raster_seg(ax, ay, bx, by, r=1):
    steps = max(1, int(math.hypot(bx - ax, by - ay)) + 1)
    for i in range(steps + 1):
        t = i / steps
        mark(int(ax + (bx - ax) * t), int(ay + (by - ay) * t), r=r)


for ln in coast:
    g = [to_grid(x, y) for x, y in ln]
    for i in range(len(g) - 1):
        raster_seg(g[i][0], g[i][1], g[i + 1][0], g[i + 1][1], r=0)

# Bogaz + Canakkale DAR-bogaz bariyerleri (Kilitbahir hatti ~1.3km).
# Agiz geometrisi kararsiz oldugu icin dar noktadan muhurlenir;
# alt bogaz suni kara gorunur (Bogaz bariyeriyle tutarli davranis).
# Tum duvar uclari raster-kara hucrelerine deger (yoklamali).
# - Bogaz: eski hat (muhurlu oldugu dogrulandi).
# - Dar-bogaz: olculmus kara bloklari arasi (26.355-26.405 @ 40.16).
# - Uc tipa: korfez ucu alt-hucre boslugunu tikar, iki ucu da
#   izlenmis egri uzerinde.
# Giris-agzi baraji: kuzey kiyi izi (29.890,40.763 civari) ile uc
# egrisi arasindaki ~3.7km'lik izlenmemis agiz; iki ucu da izli kiyida.
# Dogusundaki ~2km2'lik girinti kuru kalir (belgelensin).
# Guney-dogu duvari: Gemlik ucu izli kiyidan (29.152,40.434) korfez
# ucu egrisine (29.924,40.716); tamami gercek karada kalir (gorunmez),
# haritalanmamis guney-dogu bosluga sizmayi onler.
# Giris-agzi baraji: kuzey izi (29.888,40.764) ile uc egrisi arasindaki
# izlenmemis agiz; girinti ici suyu havzada tutar.
for (x0, y0, x1, y1) in [(28.93, 41.02, 29.12, 41.02),
                          (26.355, 40.16, 26.405, 40.16),
                          (29.152, 40.434, 29.924, 40.716),
                          (29.888, 40.764, 29.931, 40.757)]:
    a, b = to_grid(x0, y0), to_grid(x1, y1)
    raster_seg(a[0], a[1], b[0], b[1])
print("kara hucre:", sum(land))

def _fill(seed):
    w = bytearray(NX * NY)
    sx, sy = to_grid(*seed)
    if land[sy * NX + sx]:
        return w, "karada"
    dq = deque([(sx, sy)])
    while dq:
        ix, iy = dq.popleft()
        if not (0 <= ix < NX and 0 <= iy < NY):
            continue
        k = iy * NX + ix
        if w[k] or land[k]:
            continue
        w[k] = 1
        dq.extend(((ix + 1, iy), (ix - 1, iy), (ix, iy + 1), (ix, iy - 1)))
    edge = (sum(1 for iy in range(NY) if w[iy * NX])
            + sum(1 for ix in range(NX) if w[ix])
            + sum(1 for iy in range(NY) if w[iy * NX + NX - 1])
            + sum(1 for ix in range(NX) if w[(NY - 1) * NX + ix]))
    return w, ("siziyor" if edge else "kapali")


# Tohum adaylari: her biri IZOLE denenir; kutu kenarina sizan
# elenir (fail-closed). Kapali cepler (korfez icleri) boyle boyanir.
CANDS = [(28.0, 40.70), (29.7, 40.75), (29.85, 40.74), (30.0, 40.74),
          (27.9, 40.45), (27.55, 40.62), (27.0, 40.55), (29.25, 40.58)]
water = bytearray(NX * NY)
for _sd in CANDS:
    _w, _st = _fill(_sd)
    print(f"tohum {_sd}: {sum(_w)} hucre [{_st}]")
    if _st == "kapali":
        for _k in range(NX * NY):
            if _w[_k]:
                water[_k] = 1
# Havza kirpma: guney-dogu duvari dogusunda kalan su hucrelerini
# birak (haritalanmamis dogu boslugu; duvar harita cercevesi islevi
# gorur). Duvar yonlu dogru: (29.152,40.434)->(29.924,40.716).
_WX0, _WY0, _WX1, _WY1 = 29.152, 40.434, 29.924, 40.716
_dropped = 0
for _iy in range(NY):
    _lat = BY0 + _iy * CELL
    if not (40.4 <= _lat <= 40.9):
        continue
    for _ix in range(NX):
        if not water[_iy * NX + _ix]:
            continue
        _lon = BX0 + _ix * CELL
        if _lon < 29.4:
            continue
        _cross = (_WX1 - _WX0) * (_lat - _WY0) - (_WY1 - _WY0) * (_lon - _WX0)
        if _cross < 0:
            water[_iy * NX + _ix] = 0
            _dropped += 1
print("kirpma:", _dropped)
print("su hucre:", sum(water))

# Izmit ic korfez de su mu?
ix, iy = to_grid(30.1, 40.72)
print("izmit-ic su:", bool(water[iy * NX + ix]))

_w = np.array(water, dtype=bool).reshape(NY, NX)
_pad = np.zeros((NY + 2, NX + 2), dtype=bool)
_pad[1:-1, 1:-1] = _w
_er = (_pad[1:-1, 1:-1] & _pad[:-2, 1:-1] & _pad[2:, 1:-1]
       & _pad[1:-1, :-2] & _pad[1:-1, 2:])
_pad2 = np.zeros((NY + 2, NX + 2), dtype=bool)
_pad2[1:-1, 1:-1] = _er
_dil = (_pad2[1:-1, 1:-1] | _pad2[:-2, 1:-1] | _pad2[2:, 1:-1]
        | _pad2[1:-1, :-2] | _pad2[1:-1, 2:])
m = _dil.astype(float).reshape(NY, NX)
xs = np.linspace(BX0, BX1, NX)
ys = np.linspace(BY0, BY1, NY)
fig, ax = plt.subplots()
cs = ax.contour(xs, ys, m, levels=[0.5])
polys = []
for p in cs.get_paths():
    v = p.vertices
    codes = p.codes
    # Alt-yollari MOVETO'dan bol (tek Path coklu halka icerebilir;
    # bolunmezse halkalar arasi hayalet kirisler olusur).
    cur = []
    rings = []

    def _flush():
        if len(cur) >= 8:
            rings.append([(round(float(x), 4), round(float(y), 4))
                          for x, y in cur])

    if codes is None:
        if len(v) >= 8:
            rings.append([(round(float(x), 4), round(float(y), 4))
                          for x, y in v])
    else:
        for (x, y), c in zip(v, codes):
            if c == 1 and cur:
                _flush()
                cur = []
            if c != 79:
                cur.append((x, y))
        _flush()
    polys.extend(rings)
plt.close(fig)
print("kontur:", len(polys))


def area(poly):
    s = 0.0
    for i in range(len(poly)):
        x0, y0 = poly[i]
        x1, y1 = poly[(i + 1) % len(poly)]
        s += x0 * y1 - x1 * y0
    return abs(s) / 2


sea, islands = None, []
for poly in polys:
    a = area(poly)
    cx = sum(p[0] for p in poly) / len(poly)
    cy = sum(p[1] for p in poly) / len(poly)
    if 26.0 <= cx <= 30.6 and 40.0 <= cy <= 41.2 and a > 0.02:
        if sea is None or a > area(sea):
            if sea is not None:
                islands.append(sea)
            sea = poly
        else:
            islands.append(poly)
    elif 26.0 <= cx <= 30.6 and 40.0 <= cy <= 41.2 and 0.0005 < a <= 0.02:
        islands.append(poly)
print("DENIZ:", len(sea) if sea else 0, "alan:", round(area(sea), 4) if sea else 0,
      "ADA:", len(islands))

sea_s = dp(sea, 0.0025)
isl_s = [dp(p, 0.002) for p in islands if len(p) >= 6]
print("sade: deniz", len(sea_s), "adalar", sorted(len(p) for p in isl_s))

# Sadelemeden sonra en uzun parca (km)
mx = 0
for a, b in zip(sea_s, sea_s[1:] + sea_s[:1]):
    mx = max(mx, math.hypot((b[0]-a[0])*85.0, (b[1]-a[1])*111.0))
print("deniz max parca km:", round(mx, 2))

with open(os.path.join(OUT, "coastline.py"), "w", encoding="utf-8") as f:
    f.write('"""\nMarmara kiyi cizgileri (Natural Earth 10m, public domain).\nFormat: [boylam, enlem] nokta listeleri.\n"""\nCOAST_LINES = ')
    json.dump(coast, f, separators=(",", ":"))
    f.write("\n")
with open(os.path.join(OUT, "sealines.py"), "w", encoding="utf-8") as f:
    f.write('"""\nMarmara deniz hududu + adalar (NE 10m + raster flood-fill + contour).\nBogaz ve Canakkale bariyerlidir.\n"""\nSEA_RING = ')
    json.dump(sea_s, f, separators=(",", ":"))
    f.write("\nISLANDS = ")
    json.dump(isl_s, f, separators=(",", ":"))
    f.write("\n")
print("dosyalar yazildi")

fig, ax = plt.subplots(figsize=(12, 7))
for ln in coast:
    ax.plot([p[0] for p in ln], [p[1] for p in ln], "k-", lw=0.5)
ax.add_patch(plt.Polygon(sea_s, closed=True, facecolor="#9fc3e8", edgecolor="red", lw=1.0))
for isl in isl_s:
    ax.add_patch(plt.Polygon(isl, closed=True, facecolor="green", edgecolor="green"))
ax.set_xlim(BX0, BX1)
ax.set_ylim(BY0, BY1)
ax.set_aspect(1.32)
fig.savefig(os.path.join(TMP, "sea_new.png"), dpi=130, bbox_inches="tight")
print("preview ok")

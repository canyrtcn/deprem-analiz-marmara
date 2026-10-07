"""Kiyi cizgisi kirpma + sadelestirme (gelistirme araci, uygulamada calismaz)."""
import json, math, os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

LON0, LON1 = 25.8, 31.2
LAT0, LAT1 = 39.6, 42.0


def dp(points, eps):
    """Douglas-Peucker."""
    if len(points) < 3:
        return points
    (x0, y0), (x1, y1) = points[0], points[-1]
    dx, dy = x1 - x0, y1 - y0
    den = math.hypot(dx, dy)
    best, idx = 0, 0
    for i in range(1, len(points) - 1):
        x, y = points[i]
        if den == 0:
            d = math.hypot(x - x0, y - y0)
        else:
            d = abs(dy * x - dx * y + x1 * y0 - y1 * x0) / den
        if d > best:
            best, idx = d, i
    if best > eps:
        left = dp(points[:idx + 1], eps)
        right = dp(points[1 + idx:], eps)
        return left[:-1] + right
    return [points[0], points[-1]]


def clip_runs(line):
    """Bbox disina cikan noktalarda cizgiyi bol (akor artefakti yok)."""
    runs, cur = [], []
    for lo, la in line:
        if LON0 - 0.3 <= lo <= LON1 + 0.3 and LAT0 - 0.3 <= la <= LAT1 + 0.3:
            cur.append((lo, la))
        else:
            if len(cur) >= 2:
                runs.append(cur)
            cur = []
    if len(cur) >= 2:
        runs.append(cur)
    return runs


d = json.load(open(os.path.join(HERE, "coast10.geojson"), encoding="utf-8"))
lines = []
for f in d["features"]:
    g = f["geometry"]
    geoms = []
    if g["type"] == "LineString":
        geoms = [g["coordinates"]]
    elif g["type"] == "MultiLineString":
        geoms = g["coordinates"]
    for ln in geoms:
        for run in clip_runs(ln):
            s = dp(run, 0.002)
            if len(s) >= 2:
                lines.append([[round(x, 4), round(y, 4)] for x, y in s])

npts = sum(len(l) for l in lines)
print(f"cizgi: {len(lines)}, nokta: {npts}")

with open(os.path.join(ROOT, "deprem_izleme", "coastline.py"), "w", encoding="utf-8") as f:
    f.write('"""\nGomulu Marmara kiyi cizgisi (Natural Earth 10m, kirpilmis + sadelestirilmis).\nKaynak: https://www.naturalearthdata.com (public domain)\nFormat: COAST_LINES = [ [(lon, lat), ...], ... ]\n"""\nCOAST_LINES = ')
    json.dump(lines, f, separators=(",", ":"))
    f.write("\n")
print("coastline.py yazildi")

# Onizleme
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
fig, ax = plt.subplots(figsize=(10, 6))
for ln in lines:
    xs = [p[0] for p in ln]
    ys = [p[1] for p in ln]
    ax.plot(xs, ys, "k-", lw=0.6)
import sys
sys.path.insert(0, ROOT)
from deprem_izleme.fault_segments import FAULT_SEGMENTS, HISTORICAL_EARTHQUAKES
for seg in FAULT_SEGMENTS:
    xs = [c[1] for c in seg["coords"]]
    ys = [c[0] for c in seg["coords"]]
    ax.plot(xs, ys, "-", color=seg["color"], lw=1.5)
ax.set_xlim(LON0, LON1)
ax.set_ylim(LAT0, LAT1)
ax.set_aspect("equal")
fig.savefig(os.path.join(HERE, "_coast_preview.png"), dpi=110, bbox_inches="tight")
print("preview ok")

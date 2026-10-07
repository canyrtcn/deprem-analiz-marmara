"""Deniz halkasi otomatik cikarma: kirpilmis kiyi kollari uclardan birlestirilir,
en buyuk kapali halka Marmara hududu olur (adalar ayri saklanir)."""
import sys, math, os
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
from deprem_izleme.coastline import COAST_LINES

BX0, BX1, BY0, BY1 = 26.15, 30.05, 39.90, 41.30
TOL = 0.035


def in_box(p):
    return BX0 <= p[0] <= BX1 and BY0 <= p[1] <= BY1


def area(poly):
    s = 0.0
    for i in range(len(poly)):
        x0, y0 = poly[i]
        x1, y1 = poly[(i + 1) % len(poly)]
        s += x0 * y1 - x1 * y0
    return abs(s) / 2


def centroid(poly):
    return (sum(p[0] for p in poly) / len(poly), sum(p[1] for p in poly) / len(poly))


def dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


# Kollar: kutu icinde parcasi olanlar
runs = []
for ln in COAST_LINES:
    pts = [(x, y) for x, y in ln]
    if any(in_box(p) for p in pts) and len(pts) >= 2:
        runs.append(pts)
print("kol:", len(runs))

# Uctan uca birlestirme
chains = [list(r) for r in runs]
changed = True
while changed:
    changed = False
    ends = []
    for ci, ch in enumerate(chains):
        ends.append((ch[0], ci, 0))
        ends.append((ch[-1], ci, 1))
    best = None
    for i in range(len(ends)):
        for j in range(i + 1, len(ends)):
            (pa, ca, ea), (pb, cb, eb) = ends[i], ends[j]
            if ca == cb:
                continue
            d = dist(pa, pb)
            if d < TOL and (best is None or d < best[0]):
                best = (d, ca, ea, cb, eb)
    if best:
        _, ca, ea, cb, eb = best
        A, B = chains[ca], chains[cb]
        if ea == 1 and eb == 0:
            C = A + B
        elif ea == 0 and eb == 1:
            C = B + A
        elif ea == 0 and eb == 0:
            C = A[::-1] + B
        else:
            C = A + B[::-1]
        chains = [c for k, c in enumerate(chains) if k not in (ca, cb)]
        chains.append(C)
        changed = True

print("zincir:", len(chains))
loops = []
for ch in chains:
    if len(ch) >= 8 and dist(ch[0], ch[-1]) < TOL:
        loops.append(ch)
print("kapali halka:", len(loops))

sea = None
islands = []
for lp in loops:
    a = area(lp)
    cx, cy = centroid(lp)
    in_sea = 26.6 <= cx <= 29.6 and 40.2 <= cy <= 41.0
    print(f"halka: n={len(lp)} alan={a:.4f} merkez=({cx:.2f},{cy:.2f}) in_sea={in_sea}")
    if in_sea and (sea is None or a > area(sea)):
        if sea is not None and area(sea) < 0.05:
            islands.append(sea)
        sea = lp
    elif in_sea and a < 0.05:
        islands.append(lp)

print("DENIZ n=", len(sea) if sea else 0, "ADA:", len(islands))

with open(os.path.join(ROOT, "deprem_izleme", "sealines.py"), "w", encoding="utf-8") as f:
    f.write('"""\nMarmara deniz hududu + adalar (Natural Earth 10m kiyidan otomatik cikarma).\nKaynak: https://www.naturalearthdata.com (public domain)\n"""\nSEA_RING = ')
    import json
    json.dump([[round(x, 4), round(y, 4)] for x, y in sea], f, separators=(",", ":"))
    f.write("\nISLANDS = ")
    json.dump([[[round(x, 4), round(y, 4)] for x, y in isl] for isl in islands], f, separators=(",", ":"))
    f.write("\n")
print("sealines.py yazildi")

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
fig, ax = plt.subplots(figsize=(12, 7))
for ln in COAST_LINES:
    ax.plot([p[0] for p in ln], [p[1] for p in ln], "k-", lw=0.6)
ax.add_patch(plt.Polygon(sea, closed=True, facecolor="#9fc3e8", edgecolor="red", lw=1.2))
for isl in islands:
    ax.add_patch(plt.Polygon(isl, closed=True, facecolor="green", edgecolor="green"))
ax.set_xlim(BX0, BX1)
ax.set_ylim(BY0, BY1)
ax.set_aspect(1.32)
fig.savefig(os.path.join(HERE, "_sea_auto.png"), dpi=130, bbox_inches="tight")
print("preview ok")

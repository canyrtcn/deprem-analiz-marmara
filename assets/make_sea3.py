"""Deniz poligonu: raster + flood fill + contour (deterministik, dogru)."""
import sys, math, os
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
from collections import deque
from deprem_izleme.coastline import COAST_LINES

X0, X1, Y0, Y1, CELL = 26.25, 31.2, 39.95, 42.0, 0.004
NX, NY = int((X1 - X0) / CELL), int((Y1 - Y0) / CELL)
print("grid:", NX, NY)


def to_grid(x, y):
    return int((x - X0) / CELL), int((y - Y0) / CELL)


land = bytearray(NX * NY)


def mark(ix, iy, r=1):
    for dx in range(-r, r + 1):
        for dy in range(-r, r + 1):
            jx, jy = ix + dx, iy + dy
            if 0 <= jx < NX and 0 <= jy < NY:
                land[jy * NX + jx] = 1


def raster_seg(ax, ay, bx, by):
    steps = max(1, int(math.hypot(bx - ax, by - ay)) + 1)
    for i in range(steps + 1):
        t = i / steps
        mark(int(ax + (bx - ax) * t), int(ay + (by - ay) * t))


for ln in COAST_LINES:
    g = [to_grid(x, y) for x, y in ln]
    for i in range(len(g) - 1):
        raster_seg(g[i][0], g[i][1], g[i + 1][0], g[i + 1][1])

# Bogaz bariyeri (Karadeniz'e sizma onlenir)
b0, b1 = to_grid(28.93, 41.07), to_grid(29.10, 41.07)
raster_seg(b0[0], b0[1], b1[0], b1[1])
print("kara hucre:", sum(land))

# Flood fill (deniz tohumu: Marmara ortasi)
sx, sy = to_grid(28.0, 40.75)
water = bytearray(NX * NY)
dq = deque([(sx, sy)])
while dq:
    ix, iy = dq.popleft()
    if not (0 <= ix < NX and 0 <= iy < NY):
        continue
    k = iy * NX + ix
    if water[k] or land[k]:
        continue
    water[k] = 1
    dq.extend(((ix + 1, iy), (ix - 1, iy), (ix, iy + 1), (ix, iy - 1)))
print("su hucre:", sum(water))

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

m = np.array(water, dtype=float).reshape(NY, NX)
xs = np.linspace(X0, X1, NX)
ys = np.linspace(Y0, Y1, NY)
fig, ax = plt.subplots()
cs = ax.contour(xs, ys, m, levels=[0.5])
paths = cs.get_paths()
print("kontur:", len(paths))
polys = []
for p in paths:
    v = p.vertices
    if len(v) >= 8:
        polys.append([(round(float(x), 4), round(float(y), 4)) for x, y in v])
plt.close(fig)


def area(poly):
    s = 0.0
    for i in range(len(poly)):
        x0, y0 = poly[i]
        x1, y1 = poly[(i + 1) % len(poly)]
        s += x0 * y1 - x1 * y0
    return abs(s) / 2


def centroid(poly):
    return (sum(p[0] for p in poly) / len(poly), sum(p[1] for p in poly) / len(poly))


def dp(points, eps):
    if len(points) < 3:
        return points
    (x0, y0), (x1, y1) = points[0], points[-1]
    dx, dy = x1 - x0, y1 - y0
    den = math.hypot(dx, dy)
    best, idx = 0, 0
    for i in range(1, len(points) - 1):
        x, y = points[i]
        d = math.hypot(x - x0, y - y0) if den == 0 else abs(dy * x - dx * y + x1 * y0 - y1 * x0) / den
        if d > best:
            best, idx = d, i
    if best > eps:
        return dp(points[:idx + 1], eps)[:-1] + dp(points[idx:], eps)
    return [points[0], points[-1]]


# Marmara su kutlesi: merkezi kutuda olan en buyuk poligon
sea, islands = None, []
for poly in polys:
    a = area(poly)
    cx, cy = centroid(poly)
    if 26.5 <= cx <= 29.8 and 40.1 <= cy <= 41.0 and a > 0.02:
        if sea is None or a > area(sea):
            sea = poly
        else:
            islands.append(poly)
    elif 26.5 <= cx <= 29.8 and 40.1 <= cy <= 41.0 and 0.0005 < a <= 0.02:
        islands.append(poly)

print("DENIZ:", len(sea) if sea else 0, "alan:", round(area(sea), 4) if sea else 0, "ADA:", len(islands))
sea_s = dp(sea, 0.0025)
isl_s = [dp(p, 0.002) for p in islands if len(p) >= 6]
print("sade: deniz", len(sea_s), "adalar", [len(p) for p in isl_s])

import json
with open(os.path.join(ROOT, "deprem_izleme", "sealines.py"), "w", encoding="utf-8") as f:
    f.write('"""\nMarmara deniz hududu + adalar (raster flood-fill + contour).\nHammadde: Natural Earth 10m kiyi (public domain). Bogaz bariyerlidir.\n"""\nSEA_RING = ')
    json.dump(sea_s, f, separators=(",", ":"))
    f.write("\nISLANDS = ")
    json.dump(isl_s, f, separators=(",", ":"))
    f.write("\n")
print("sealines.py yazildi")

fig, ax = plt.subplots(figsize=(12, 7))
for ln in COAST_LINES:
    ax.plot([p[0] for p in ln], [p[1] for p in ln], "k-", lw=0.6)
ax.add_patch(plt.Polygon(sea_s, closed=True, facecolor="#9fc3e8", edgecolor="red", lw=1.2))
for isl in isl_s:
    ax.add_patch(plt.Polygon(isl, closed=True, facecolor="green", edgecolor="green"))
ax.set_xlim(25.8, 31.2)
ax.set_ylim(39.6, 42.0)
ax.set_aspect(1.32)
fig.savefig(os.path.join(HERE, "_sea_auto2.png"), dpi=130, bbox_inches="tight")
print("preview ok")

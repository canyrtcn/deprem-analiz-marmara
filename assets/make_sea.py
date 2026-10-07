"""Deniz poligonu secimi icin numarali onizleme."""
import sys, os
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
from deprem_izleme.coastline import COAST_LINES
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

pts = []
for ln in COAST_LINES:
    for x, y in ln:
        if 26.1 <= x <= 30.1 and 39.85 <= y <= 41.35:
            pts.append((x, y))
print("aday nokta:", len(pts))

fig, ax = plt.subplots(figsize=(20, 12))
for ln in COAST_LINES:
    xs = [p[0] for p in ln]
    ys = [p[1] for p in ln]
    ax.plot(xs, ys, "k-", lw=0.8)
for i, (x, y) in enumerate(pts):
    ax.text(x, y, str(i), fontsize=5, color="red")
ax.set_xlim(26.1, 30.1)
ax.set_ylim(39.85, 41.35)
fig.savefig(os.path.join(HERE, "_sea_pick.png"), dpi=130, bbox_inches="tight")
print("ok")
with open(os.path.join(HERE, "_sea_pts.txt"), "w") as f:
    for i, (x, y) in enumerate(pts):
        f.write(f"{i}: {x},{y}\n")

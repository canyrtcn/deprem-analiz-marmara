"""MTA sayisallastirmasindan gercek fay izleri v2 (kaynak: ozangerger/earthquakes-in-istanbul,
MTA diri fay haritalarinin QGIS sayisallastirmasi). Cikti: deprem_izleme/fault_traces.py"""
import json, os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
A = os.path.join(HERE)


def load(name):
    d = json.load(open(f"{A}/{name}.geojson", encoding="utf-8"))
    out = []
    for f in d["features"]:
        g = f["geometry"]
        if g["type"] == "LineString":
            out.append([(p[0], p[1]) for p in g["coordinates"]])
        elif g["type"] == "MultiLineString":
            for part in g["coordinates"]:
                out.append([(p[0], p[1]) for p in part])
    return out


def merge_lon(chains):
    pts = sorted([p for c in chains for p in c], key=lambda p: (p[0], p[1]))
    ded = [pts[0]]
    for p in pts[1:]:
        if abs(p[0] - ded[-1][0]) > 0.001 or abs(p[1] - ded[-1][1]) > 0.001:
            ded.append(p)
    return ded


def simplify(line, eps=0.0025):
    import math
    if len(line) < 3:
        return line
    (x0, y0), (x1, y1) = line[0], line[-1]
    dx, dy = x1 - x0, y1 - y0
    den = math.hypot(dx, dy)
    best, idx = 0, 0
    for i in range(1, len(line) - 1):
        x, y = line[i]
        d = math.hypot(x - x0, y - y0) if den == 0 else abs(dy * x - dx * y + x1 * y0 - y1 * x0) / den
        if d > best:
            best, idx = d, i
    if best > eps:
        return simplify(line[:idx + 1], eps)[:-1] + simplify(line[idx:], eps)
    return [line[0], line[-1]]


def to_latlon(line):
    return [[round(y, 4), round(x, 4)] for x, y in simplify(line)]


tek = load("tekirdag_segmenti")
tek_main = max(tek, key=len)
tek_splays = [c for c in tek if c is not tek_main and len(c) >= 8]

orta = load("orta_marmara_cukuru")
south_idx = [i for i, c in enumerate(orta)
             if sum(p[1] for p in c) / len(c) < 40.825 and min(p[0] for p in c) < 28.08]
central_main = merge_lon([orta[i] for i in south_idx])
central_splays = [orta[i] for i in range(len(orta)) if i not in south_idx and len(orta[i]) >= 8]

kum = load("kumburgaz_segmenti")
kumburgaz_main = merge_lon(kum)

avc = load("avcilar_segmenti")
is_north = lambda c: sum(p[1] for p in c) / len(c) > 40.855 and max(p[0] for p in c) < 28.6
splay_avc = [c for c in avc if is_north(c)]
main_avc = merge_lon([c for c in avc if not is_north(c)])
avc_pts = sorted(main_avc, key=lambda p: p[0])
avcilar_main = [p for p in avc_pts if p[0] < 28.75]
adalar_main = [p for p in avc_pts if p[0] >= 28.75]

cin = load("cinarcik_segmenti")
cinarcik_main = max(cin, key=len)

TRACES = {
    "Tekirdag": {"coords": to_latlon(tek_main),
                 "splays": [to_latlon(c) for c in tek_splays],
                 "trace_source": "MTA sayısallaştırma"},
    "Central": {"coords": to_latlon(central_main),
                "splays": [to_latlon(c) for c in central_splays],
                "trace_source": "MTA sayısallaştırma"},
    "Kumburgaz": {"coords": to_latlon(kumburgaz_main),
                  "splays": [],
                  "trace_source": "MTA sayısallaştırma"},
    "Avcilar": {"coords": to_latlon(avcilar_main),
                "splays": [to_latlon(c) for c in splay_avc if len(c) >= 2],
                "trace_source": "MTA sayısallaştırma"},
    "Adalar": {"coords": to_latlon(adalar_main),
               "splays": [],
               "trace_source": "MTA sayısallaştırma"},
    "Cinarcik": {"coords": to_latlon(cinarcik_main),
                 "splays": [],
                 "trace_source": "MTA sayısallaştırma"},
}

for k, v in TRACES.items():
    print(k, "ana:", len(v["coords"]), "splay:", [len(s) for s in v["splays"]])

with open(os.path.join(ROOT, "deprem_izleme", "fault_traces.py"),
          "w", encoding="utf-8") as f:
    f.write('"""\nGercek fay izleri (MTA diri fay haritalarinin QGIS sayisallastirmasi).\nKaynak repo: ozangerger/earthquakes-in-istanbul (data/*.geojson).\nFormat: [lat, lon]. apply_traces() FAULT_SEGMENTS icine isler.\n"""\nTRACES = ')
    json.dump(TRACES, f, separators=(",", ":"), ensure_ascii=False)
    f.write('\n\n\ndef apply_traces(segments):\n'
            '    """FAULT_SEGMENTS listesini gercek izlerle guncelle."""\n'
            '    for seg in segments:\n'
            '        t = TRACES.get(seg["name"])\n'
            '        if t:\n'
            '            seg["coords"] = t["coords"]\n'
            '            seg["splays"] = t["splays"]\n'
            '            seg["trace_source"] = t["trace_source"]\n'
            '        else:\n'
            '            seg.setdefault("splays", [])\n'
            '            seg.setdefault("trace_source", "şematik")\n')
print("fault_traces.py yazildi")

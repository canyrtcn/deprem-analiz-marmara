"""Deprem Analiz uygulamasi ikonu - kodla uretilir (dis asset yok)."""
import os
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
SIZE = 256
SS = 4  # supersampling: buyuk ciz, kucult (yumusak kenar)
BIG = SIZE * SS

# Zemin: koyu lacivert degrade, yuvarlatilmis kare
base = Image.new("RGBA", (BIG, BIG), (0, 0, 0, 0))
g = Image.new("RGBA", (BIG, BIG))
gd = ImageDraw.Draw(g)
for y in range(BIG):
    t = y / BIG
    r = int(26 + (16 - 26) * t)
    gr = int(26 + (16 - 26) * t)
    b = int(46 + (32 - 46) * t)
    gd.line([(0, y), (BIG, y)], fill=(r, gr, b, 255))
mask = Image.new("L", (BIG, BIG), 0)
ImageDraw.Draw(mask).rounded_rectangle([0, 0, BIG, BIG], radius=58 * SS, fill=255)
base.paste(g, (0, 0), mask)

d = ImageDraw.Draw(base)


def S(v):
    return int(v * SS)


# Ince vurgu cercevesi
d.rounded_rectangle([S(3), S(3), BIG - S(3), BIG - S(3)], radius=55 * SS,
                    outline=(59, 130, 246, 160), width=3 * SS)

# Merkez: artci dalga halkalari (episantr)
cx, cy = BIG // 2, int(112 * SS)
for rad, col, w in ((86, (239, 68, 68, 70), 5),
                    (62, (245, 158, 11, 130), 6),
                    (40, (249, 115, 22, 200), 7)):
    rr, ww = S(rad), S(w)
    d.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], outline=col, width=ww)

# Episantr noktasi (beyaz-sari cekirdek + turuncu hale)
d.ellipse([cx - S(20), cy - S(20), cx + S(20), cy + S(20)], fill=(249, 115, 22, 255))
d.ellipse([cx - S(11), cy - S(11), cx + S(11), cy + S(11)], fill=(255, 255, 255, 255))

# Sismograf cizgisi (alt bantta, ekran genisligince)
pts = [8, 196, 30, 196, 40, 196, 48, 168, 56, 214, 64, 150, 72, 222,
       80, 196, 96, 196, 104, 178, 112, 206, 120, 160, 128, 218, 136, 196,
       152, 196, 160, 184, 168, 204, 176, 172, 184, 212, 192, 196, 248, 196]
xy = [(S(pts[i]), S(pts[i + 1])) for i in range(0, len(pts), 2)]
d.line(xy, fill=(45, 212, 191, 230), width=S(7), joint="curve")

# Asagi ornekle -> yumusak kenarlar
base = base.resize((SIZE, SIZE), Image.LANCZOS)

png_path = os.path.join(HERE, "icon.png")
ico_path = os.path.join(HERE, "icon.ico")
base.save(png_path)
base.save(ico_path, sizes=[(16, 16), (24, 24), (32, 32), (48, 48),
                           (64, 64), (128, 128), (256, 256)])
print("OK", png_path, os.path.getsize(png_path), "|", ico_path, os.path.getsize(ico_path))

"""Spindle's logo and icons, pixel art: drawn pixel by pixel on small grids
(no anti-aliasing) and only ever enlarged by whole numbers, so they stay
crisp. The wheel is the app's own (blue theme): the top wedge lit, the
name across it, frosted wedges below, the hub with its pill.

    python assets/brand/make_brand.py        (writes the files next to it)

    icon-16 / -24 / -32.png    drawn at that size (16 and 24 simplified)
    icon-48 ... -512.png       the 24 / 32 px drawings enlarged x2 ... x16
    logo.png / logo.svg        the full logo, 80 x 80 (the SVG is pixel-exact)
    logo-dark.svg              the logo on its dark tile (README)
    social-preview.png         1280 x 640, for GitHub's social preview
    (installer_images(): the Windows installer's pictures, made by the build)
"""
import math, os, sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtCore import QPointF, QRectF, Qt  # noqa: E402
from PyQt6.QtGui import QColor, QFont, QGuiApplication, QImage, QPainter  # noqa: E402

app = QGuiApplication.instance() or QGuiApplication(sys.argv[:1])
OUT = Path(__file__).resolve().parent
TILE = "#1F2329"  # the dark tile behind the full logo

C = {  # stepped blue-theme palette
    "outline": "#14306A", "hot3": "#1E5BD8", "hot2": "#2F6FEA", "hot1": "#4C8DFF", "hot0": "#8DB6FF",
    "glass2": "#C3D6F5", "glass1": "#D6E4FB", "glass0": "#EAF2FF", "white": "#FFFFFF",
    "hub1": "#DCE8FC", "hub0": "#F4F8FF", "edge": "#9DB8E8", "ink": "#1E3A5F",
}

# bold 6x7 pixel font, 2-pixel strokes (1 = ink)
FONT = {
    "S": ["011110", "110011", "110000", "011110", "000011", "110011", "011110"],
    "P": ["111110", "110011", "110011", "111110", "110000", "110000", "110000"],
    "I": ["111111", "001100", "001100", "001100", "001100", "001100", "111111"],
    "N": ["110011", "111011", "111111", "110111", "110011", "110011", "110011"],
    "D": ["111100", "110110", "110011", "110011", "110011", "110110", "111100"],
    "L": ["110000", "110000", "110000", "110000", "110000", "110000", "111111"],
    "E": ["111111", "110000", "110000", "111110", "110000", "110000", "111111"],
}
SMALL_S = ["01110", "11011", "11000", "01110", "00011", "11011", "01110"]
# bold 7x9 S for the icon hub
BIG_S = ["0111110", "1111111", "1100000", "1111100", "0111110", "0000011", "0000011", "1111111", "0111110"]


def wheel(n, top_deg=212, lower=4, text=True, hub_s=None, shadow=True, hub_frac=None):
    """A pixel grid (list of rows of color names or None)."""
    g = [[None] * n for _ in range(n)]
    c = n / 2
    R = n / 2 - (2 if shadow else 0.5)
    r = R * (hub_frac or (0.40 if hub_s is None else 0.52))
    a1 = top_deg / 2
    step = (360 - top_deg) / lower
    dividers = [a1 + i * step for i in range(lower)] + [-a1]
    for y in range(n):
        for x in range(n):
            dx, dy = x + 0.5 - c, y + 0.5 - c
            d = math.hypot(dx, dy)
            ang = (math.degrees(math.atan2(dx, -dy)) + 360) % 360
            if d > R:
                if shadow and math.hypot(dx - 0.5, dy - 1.5) <= R + 0.3:
                    g[y][x] = "shadow"
                continue
            if d > R - 1:
                g[y][x] = "outline"
                continue
            if d > r:  # the ring
                if abs(d - r) < 1.0:
                    g[y][x] = "white"      # gap around the hub
                    continue
                on_div = any(abs(((ang - a + 180) % 360) - 180) * math.pi / 180 * d < 0.55 for a in dividers)
                if on_div:
                    g[y][x] = "white"
                    continue
                top = ang <= a1 or ang >= 360 - a1
                light = (-dx * 0.55 - dy * 0.75) / R  # light from the top left
                if top:
                    tone = "hot1" if light > 0.15 else "hot2" if light > -0.35 else "hot3"
                    if R - 2.6 < d <= R - 1 and 285 <= ang <= 340:
                        tone = "hot0"  # a glint on the rim
                else:
                    t = (d - r) / (R - r) - light * 0.4
                    tone = "glass0" if t < 0.45 else "glass1" if t < 0.8 else "glass2"
                    if 0.45 <= t < 0.55 and (x + y) % 2:  # dithered edge between tones
                        tone = "glass0"
                g[y][x] = tone
                continue
            # hub
            if d > r - 2:
                g[y][x] = "edge"
            else:
                g[y][x] = "hub0" if (-dx - dy) / r > -0.6 else "hub1"
    if hub_s is None:  # the pill
        w, h = round(r * 1.25), 5
        x0, y0 = round(c - w / 2), round(c - h / 2)
        for y in range(y0, y0 + h):
            for x in range(x0, x0 + w):
                corner = (x in (x0, x0 + w - 1)) and (y in (y0, y0 + h - 1))
                if corner:
                    continue
                edge = x in (x0, x0 + w - 1) or y in (y0, y0 + h - 1) or \
                    ((x in (x0 + 1, x0 + w - 2)) and (y in (y0, y0 + h - 1)))
                g[y][x] = "edge" if edge else "white"
    else:
        rows = hub_s
        h, w = len(rows), len(rows[0])
        x0, y0 = round(c - w / 2), round(c - h / 2)
        for j, row in enumerate(rows):
            for i, bit in enumerate(row):
                if bit == "1":
                    g[y0 + j][x0 + i] = "hot3"
    if text:
        # Upright letters a fixed 7 px apart (never touching), each at the
        # height of an arc: the classic pixel-art curved title.
        mid = R - 11.5          # the middle letter's height above the center
        rv = R * 1.6            # a gentler arc than the rim's
        ink, shade = set(), set()
        for k, ch in enumerate("SPINDLE"):
            cx = c + (k - 3) * 8  # 6 px letters, 2 px apart
            cy = c - mid + (rv - math.sqrt(rv * rv - (cx - c) ** 2))
            x0, y0 = round(cx - 3), round(cy - 3.5)
            for j, row in enumerate(FONT[ch]):
                for i, bit in enumerate(row):
                    if bit == "1":
                        ink.add((x0 + i, y0 + j))
        shade = {(x + 1, y + 1) for x, y in ink} - ink  # a 1-pixel drop shadow
        for x, y in shade:
            g[y][x] = "outline"
        for x, y in ink:
            g[y][x] = "white"
    return g


def to_image(g):
    n = len(g)
    img = QImage(n, n, QImage.Format.Format_ARGB32)
    img.fill(QColor(0, 0, 0, 0))
    for y, row in enumerate(g):
        for x, v in enumerate(row):
            if v == "shadow":
                img.setPixelColor(x, y, QColor(10, 25, 60, 70))
            elif v:
                img.setPixelColor(x, y, QColor(C[v]))
    return img


def to_svg(g):
    n = len(g)
    rects = []
    for y, row in enumerate(g):
        x = 0
        while x < n:
            v = row[x]
            if not v:
                x += 1
                continue
            x1 = x
            while x1 < n and row[x1] == v:
                x1 += 1
            fill = 'fill="#0A193C" fill-opacity="0.27"' if v == "shadow" else f'fill="{C[v]}"'
            rects.append(f'<rect x="{x}" y="{y}" width="{x1 - x}" height="1" {fill}/>')
            x = x1
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {n} {n}" shape-rendering="crispEdges">'
            + "".join(rects) + "</svg>\n")


def scaled(img, k):
    return img.scaled(img.width() * k, img.height() * k, Qt.AspectRatioMode.KeepAspectRatio,
                      Qt.TransformationMode.FastTransformation)


def on_tile(img, size, k, radius=0.11):
    """The logo enlarged k times, centered on a rounded dark tile."""
    out = QImage(size, size, QImage.Format.Format_ARGB32)
    out.fill(QColor(0, 0, 0, 0))
    p = QPainter(out)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(QColor(TILE)); p.setPen(Qt.PenStyle.NoPen)
    p.drawRoundedRect(QRectF(0, 0, size, size), size * radius, size * radius)
    big = scaled(img, k)
    p.drawImage(QPointF((size - big.width()) // 2, (size - big.height()) // 2), big)
    p.end()
    return out


def tile_svg(g, pad=6, radius=10):
    """The logo on its dark tile as a pixel-exact SVG (crisp at any size)."""
    inner = to_svg(g).split(">", 1)[1].rsplit("</svg>", 1)[0]
    n = len(g) + 2 * pad
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {n} {n}">'
            f'<rect width="{n}" height="{n}" rx="{radius}" fill="{TILE}"/>'
            f'<g transform="translate({pad} {pad})" shape-rendering="crispEdges">{inner}</g></svg>\n')


def bmp(img, w, h, bg, k):
    """A Windows bitmap (no transparency) with the art enlarged k times, centered."""
    out = QImage(w, h, QImage.Format.Format_RGB32)
    out.fill(QColor(bg))
    p = QPainter(out)
    big = scaled(img, k)
    p.drawImage(QPointF((w - big.width()) // 2, (h - big.height()) // 2), big)
    p.end()
    return out


def installer_images(dest: Path) -> None:
    """The Windows installer's pictures (made at build time): the big one
    on its first / last page (164 x 314 at 100 %, 328 x 628 at 200 %), the
    small one top right (55 x 58 / 110 x 116)."""
    lg = to_image(wheel(80))
    i24 = to_image(wheel(24, top_deg=90, lower=3, text=False, hub_s=SMALL_S, shadow=False, hub_frac=0.56))
    i32 = to_image(wheel(32, top_deg=90, lower=3, text=False, hub_s=BIG_S, shadow=False))
    dest.mkdir(parents=True, exist_ok=True)
    bmp(lg, 164, 314, TILE, 2).save(str(dest / "installer-side.bmp"))
    bmp(lg, 328, 628, TILE, 4).save(str(dest / "installer-side-200.bmp"))
    bmp(i24, 55, 58, "#FFFFFF", 2).save(str(dest / "installer-small.bmp"))
    bmp(i32, 110, 116, "#FFFFFF", 3).save(str(dest / "installer-small-200.bmp"))


if __name__ == "__main__":
    logo = wheel(80)
    icon16 = wheel(16, top_deg=90, lower=3, text=False, hub_s=SMALL_S, shadow=False, hub_frac=0.66)
    icon24 = wheel(24, top_deg=90, lower=3, text=False, hub_s=SMALL_S, shadow=False, hub_frac=0.56)
    icon32 = wheel(32, top_deg=90, lower=3, text=False, hub_s=BIG_S, shadow=False)
    i16, i24, i32, lg = (to_image(g) for g in (icon16, icon24, icon32, logo))
    i16.save(str(OUT / "icon-16.png"))
    i24.save(str(OUT / "icon-24.png"))
    i32.save(str(OUT / "icon-32.png"))
    scaled(i24, 2).save(str(OUT / "icon-48.png"))
    for k in (2, 4, 8, 16):
        scaled(i32, k).save(str(OUT / f"icon-{32 * k}.png"))
    lg.save(str(OUT / "logo.png"))
    (OUT / "logo.svg").write_text(to_svg(logo))
    (OUT / "logo-dark.svg").write_text(tile_svg(logo))
    on_tile(lg, 96, 1, radius=0.16).save(str(OUT / "logo-tile-96.png"))  # welcome window

    # GitHub social preview: 1280 x 640, the logo x6 on the dark tile color, the tagline
    sp = QImage(1280, 640, QImage.Format.Format_RGB32)
    sp.fill(QColor(TILE))
    p = QPainter(sp)
    p.drawImage(QPointF(90, 80), scaled(lg, 6))
    title = QFont("Noto Sans"); title.setPixelSize(88); title.setWeight(QFont.Weight.Black)
    p.setFont(title); p.setPen(QColor("#FFFFFF"))
    p.drawText(QPointF(640, 300), "Spindle")
    sub = QFont("Noto Sans"); sub.setPixelSize(34)
    p.setFont(sub); p.setPen(QColor("#AFC6EE"))
    p.drawText(QRectF(640, 330, 580, 160), Qt.TextFlag.TextWordWrap,
               "Convert, compress & edit files from a wheel.")
    p.end()
    sp.save(str(OUT / "social-preview.png"))

    print("written to", OUT)

"""Draw the home-screen icons (SS monogram in brushed steel on black) as PNGs, using only the standard library.

Run once after changing the design: python3 local/make_icons.py  ->  site/icons/*.png
"""
import os, struct, zlib

# The SS monogram from the page header, in its own 1931 x 1923 coordinate box.
LEFT = [(83, 83), (892, 83), (892, 511), (664, 423), (664, 318), (330, 318), (330, 443), (892, 659), (892, 1008),
        (83, 1840), (83, 751), (322, 846), (322, 1250), (662, 910), (662, 810), (83, 608)]
SHAPES = [LEFT, [(1931 - x, y) for x, y in LEFT]]
BOX_W, BOX_H = 1931, 1923
OUT = os.path.join(os.path.dirname(__file__), "..", "site", "icons")
SS = 4  # supersamples per pixel along each axis


def coverage(size, scale):
    """Fraction of each pixel covered by the monogram, centred, `scale` = logo width / icon width."""
    w = size * scale
    k = w / BOX_W
    ox, oy = (size - w) / 2, (size - BOX_H * k) / 2
    polys = [[(ox + x * k, oy + y * k) for x, y in p] for p in SHAPES]
    cov = [[0] * size for _ in range(size)]
    for sy in range(size * SS):
        y = (sy + 0.5) / SS
        xs = []
        for p in polys:
            for (x1, y1), (x2, y2) in zip(p, p[1:] + p[:1]):
                if (y1 <= y) != (y2 <= y):
                    xs.append(x1 + (y - y1) * (x2 - x1) / (y2 - y1))
        xs.sort()
        row = cov[sy // SS]
        for a, b in zip(xs[::2], xs[1::2]):
            for sx in range(max(0, round(a * SS)), min(size * SS, round(b * SS))):
                row[sx // SS] += 1
    return [[c / (SS * SS) for c in r] for r in cov]


def mix(a, b, t):
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b))


def draw(size, scale):
    cov = coverage(size, scale)
    rows = []
    for y in range(size):
        row = bytearray([0])
        for x in range(size):
            # Black background with a soft lift toward the top, like the page header.
            d = ((x - size / 2) ** 2 + (y - size * 0.3) ** 2) ** 0.5 / size
            bg = mix((34, 39, 45), (8, 10, 12), min(1, d * 1.6))
            # Brushed steel: bright at the top, darker at the bottom, with faint horizontal streaks.
            t = y / size
            steel = mix((236, 240, 243), (122, 134, 145), t)
            streak = ((y * 7919) % 13) / 13 - 0.5
            steel = tuple(max(0, min(255, round(c + streak * 10))) for c in steel)
            row += bytes(mix(bg, steel, cov[y][x]))
        rows.append(bytes(row))
    return png(size, b"".join(rows))


def png(size, raw):
    chunk = lambda kind, data: struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    # Logo at 60% of the width keeps it inside Android's round/squircle mask and iOS's rounded corners.
    for name, size in [("icon-512.png", 512), ("icon-192.png", 192), ("apple-touch-icon.png", 180), ("favicon-32.png", 32)]:
        scale = 0.78 if size == 32 else 0.6
        with open(os.path.join(OUT, name), "wb") as f:
            f.write(draw(size, scale))
        print(name)

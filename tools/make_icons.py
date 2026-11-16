"""Draw the toolbar icons (a bone-like capsule shaded blue -> green -> red). Pure Python PNG.

    py -3.10 tools/make_icons.py
"""

import math
import os
import struct
import zlib

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   'resources', 'ColorMap')
INK = (60, 60, 60)


def png(path, size, px):
    raw = b''.join(b'\x00' + bytes(c for p in row for c in p) for row in px)

    def chunk(tag, data):
        return (struct.pack('>I', len(data)) + tag + data
                + struct.pack('>I', zlib.crc32(tag + data) & 0xffffffff))

    with open(path, 'wb') as fh:
        fh.write(b'\x89PNG\r\n\x1a\n')
        fh.write(chunk(b'IHDR', struct.pack('>IIBBBBB', size, size, 8, 6, 0, 0, 0)))
        fh.write(chunk(b'IDAT', zlib.compress(raw, 9)))
        fh.write(chunk(b'IEND', b''))


def _seg_dist(px, py, ax, ay, bx, by):
    vx, vy = bx - ax, by - ay
    t = max(0.0, min(1.0, ((px - ax) * vx + (py - ay) * vy) / (vx * vx + vy * vy)))
    return math.hypot(px - ax - t * vx, py - ay - t * vy), t


def _heat(s):
    """blue -> green -> red"""
    return (int(255 * max(0.0, 2 * s - 1)), int(230 * (1 - abs(2 * s - 1))),
            int(255 * max(0.0, 1 - 2 * s)))


def draw(size):
    ss = 4
    n = size * ss
    a, b = (0.22 * n, 0.80 * n), (0.78 * n, 0.20 * n)    # capsule axis, lower left -> upper right
    r = 0.22 * n
    edge = max(1.0, n / 20.0)
    cov = [[None] * n for _ in range(n)]
    for y in range(n):
        for x in range(n):
            d, t = _seg_dist(x + 0.5, y + 0.5, a[0], a[1], b[0], b[1])
            if d < r - edge:
                cov[y][x] = _heat(t)
            elif d < r:
                cov[y][x] = INK
    rows = []
    for y in range(size):
        row = []
        for x in range(size):
            acc = [0, 0, 0, 0]
            for sy in range(ss):
                for sx in range(ss):
                    c = cov[y * ss + sy][x * ss + sx]
                    if c:
                        acc[0] += c[0]
                        acc[1] += c[1]
                        acc[2] += c[2]
                        acc[3] += 1
            k = acc[3]
            row.append((acc[0] // k, acc[1] // k, acc[2] // k, 255 * k // (ss * ss))
                       if k else (0, 0, 0, 0))
        rows.append(row)
    return rows


def _blue_red(s):
    """blue -> cyan -> green -> yellow -> red, s in 0..1 (the DensityMap scale)"""
    pts = [(0, 0, 255), (0, 255, 255), (0, 255, 0), (255, 255, 0), (255, 0, 0)]
    x = min(max(s, 0.0), 1.0) * (len(pts) - 1)
    i = min(int(x), len(pts) - 2)
    f = x - i
    return tuple(int(pts[i][c] * (1 - f) + pts[i + 1][c] * f) for c in range(3))


def draw_legend(size):
    """The legend button: a vertical colour bar (red top, blue bottom) with three tick marks."""
    ss = 4
    n = size * ss
    x0, x1, y0, y1 = int(0.18 * n), int(0.48 * n), int(0.08 * n), int(0.92 * n)
    edge = max(1, n // 24)
    cov = [[None] * n for _ in range(n)]
    for y in range(n):
        for x in range(n):
            if x0 <= x < x1 and y0 <= y < y1:
                inner = x0 + edge <= x < x1 - edge and y0 + edge <= y < y1 - edge
                cov[y][x] = _blue_red(1 - (y - y0) / (y1 - y0)) if inner else INK
            for t in (0.2, 0.5, 0.8):                  # tick marks to the right of the bar
                ty = int(y0 + t * (y1 - y0))
                if x1 + edge <= x < int(0.82 * n) and abs(y - ty) <= edge // 2 + 1:
                    cov[y][x] = INK
    rows = []
    for y in range(size):
        row = []
        for x in range(size):
            acc = [0, 0, 0, 0]
            for sy in range(ss):
                for sx in range(ss):
                    c = cov[y * ss + sy][x * ss + sx]
                    if c:
                        acc[0] += c[0]
                        acc[1] += c[1]
                        acc[2] += c[2]
                        acc[3] += 1
            k = acc[3]
            row.append((acc[0] // k, acc[1] // k, acc[2] // k, 255 * k // (ss * ss))
                       if k else (0, 0, 0, 0))
        rows.append(row)
    return rows


if __name__ == '__main__':
    os.makedirs(OUT, exist_ok=True)
    for s in (16, 32, 64):
        png(os.path.join(OUT, '%dx%d.png' % (s, s)), s, draw(s))
    print('icons written to', OUT)
    out2 = os.path.join(os.path.dirname(OUT), 'ColorMapLegend')
    os.makedirs(out2, exist_ok=True)
    for s in (16, 32, 64):
        png(os.path.join(out2, '%dx%d.png' % (s, s)), s, draw_legend(s))
    print('legend icons written to', out2)

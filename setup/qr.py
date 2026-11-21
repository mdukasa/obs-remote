"""Tiny QR code maker for the installer. Python standard library only.

    python qr.py --rows URL                  # the QR as lines of 0/1 (1 = dark), quiet zone included
    python qr.py --html OUT.html "Label|URL" ...   # a page with a big QR code per address

Byte mode, error correction level M, versions 1-10 (up to 213 bytes, plenty for a URL).
Follows ISO/IEC 18004; the structure mirrors Project Nayuki's reference implementation.
"""
import html
import sys

# Error correction level M, versions 1..10: EC codewords per block, number of blocks
ECC_PER_BLOCK = [None, 10, 16, 26, 18, 24, 16, 18, 22, 22, 26]
NUM_BLOCKS = [None, 1, 1, 1, 2, 2, 4, 4, 4, 5, 5]
ECL_FORMAT_BITS = 0  # M


def raw_modules(ver):
    n = (16 * ver + 128) * ver + 64
    if ver >= 2:
        na = ver // 7 + 2
        n -= (25 * na - 10) * na - 55
        if ver >= 7:
            n -= 36
    return n


def data_codewords(ver):
    return raw_modules(ver) // 8 - ECC_PER_BLOCK[ver] * NUM_BLOCKS[ver]


# --- Reed-Solomon over GF(256), polynomial 0x11D -----------------------------------------
def gf_mul(x, y):
    z = 0
    for i in range(7, -1, -1):
        z = (z << 1) ^ ((z >> 7) * 0x11D)
        z ^= ((y >> i) & 1) * x
    return z


def rs_divisor(degree):
    r = [0] * (degree - 1) + [1]
    root = 1
    for _ in range(degree):
        for j in range(degree):
            r[j] = gf_mul(r[j], root)
            if j + 1 < degree:
                r[j] ^= r[j + 1]
        root = gf_mul(root, 0x02)
    return r


def rs_remainder(data, divisor):
    r = [0] * len(divisor)
    for b in data:
        f = b ^ r.pop(0)
        r.append(0)
        for i, c in enumerate(divisor):
            r[i] ^= gf_mul(c, f)
    return r


# --- encoding ----------------------------------------------------------------------------
def encode_codewords(text):
    data = text.encode("utf-8")
    for ver in range(1, 11):
        cc_bits = 8 if ver < 10 else 16
        if 4 + cc_bits + 8 * len(data) <= data_codewords(ver) * 8:
            break
    else:
        raise ValueError("Text too long for this QR maker")
    bits = []
    put = lambda val, n: bits.extend((val >> i) & 1 for i in range(n - 1, -1, -1))
    put(0b0100, 4)  # byte mode
    put(len(data), cc_bits)
    for b in data:
        put(b, 8)
    cap = data_codewords(ver) * 8
    put(0, min(4, cap - len(bits)))  # terminator
    put(0, (8 - len(bits) % 8) % 8)
    pad = 0xEC
    while len(bits) < cap:
        put(pad, 8)
        pad ^= 0xEC ^ 0x11
    words = [int("".join(map(str, bits[i:i + 8])), 2) for i in range(0, len(bits), 8)]

    # split into blocks, add EC, interleave
    nblocks, ecl = NUM_BLOCKS[ver], ECC_PER_BLOCK[ver]
    raw = raw_modules(ver) // 8
    nshort = nblocks - raw % nblocks
    short_len = raw // nblocks
    div = rs_divisor(ecl)
    blocks, k = [], 0
    for i in range(nblocks):
        dlen = short_len - ecl + (0 if i < nshort else 1)
        dat = words[k:k + dlen]
        k += dlen
        blocks.append((dat, rs_remainder(dat, div)))
    out = []
    for i in range(max(len(d) for d, _ in blocks)):
        for d, _ in blocks:
            if i < len(d):
                out.append(d[i])
    for i in range(ecl):
        for _, e in blocks:
            out.append(e[i])
    return ver, out


def make(text):
    ver, words = encode_codewords(text)
    size = ver * 4 + 17
    mod = [[False] * size for _ in range(size)]
    fun = [[False] * size for _ in range(size)]

    def setf(x, y, dark):
        mod[y][x] = dark
        fun[y][x] = True

    for i in range(size):  # timing patterns
        setf(6, i, i % 2 == 0)
        setf(i, 6, i % 2 == 0)

    def finder(cx, cy):
        for dy in range(-4, 5):
            for dx in range(-4, 5):
                x, y = cx + dx, cy + dy
                if 0 <= x < size and 0 <= y < size:
                    d = max(abs(dx), abs(dy))
                    setf(x, y, d not in (2, 4))

    finder(3, 3)
    finder(size - 4, 3)
    finder(3, size - 4)

    if ver >= 2:  # alignment patterns
        na = ver // 7 + 2
        step = (ver * 4 + na * 2 + 1) // (na * 2 - 2) * 2
        pos = [6] + [size - 7 - i * step for i in reversed(range(na - 1))]
        for i, a in enumerate(pos):
            for j, b in enumerate(pos):
                if (i == 0 and j == 0) or (i == 0 and j == na - 1) or (i == na - 1 and j == 0):
                    continue
                for dy in range(-2, 3):
                    for dx in range(-2, 3):
                        setf(a + dx, b + dy, max(abs(dx), abs(dy)) != 1)

    def draw_format(mask):
        data = ECL_FORMAT_BITS << 3 | mask
        rem = data
        for _ in range(10):
            rem = (rem << 1) ^ ((rem >> 9) * 0x537)
        bits = (data << 10 | rem) ^ 0x5412
        b = lambda i: (bits >> i) & 1 == 1
        for i in range(6):
            setf(8, i, b(i))
        setf(8, 7, b(6))
        setf(8, 8, b(7))
        setf(7, 8, b(8))
        for i in range(9, 15):
            setf(14 - i, 8, b(i))
        for i in range(8):
            setf(size - 1 - i, 8, b(i))
        for i in range(8, 15):
            setf(8, size - 15 + i, b(i))
        setf(8, size - 8, True)  # always-dark module

    draw_format(0)  # reserve the areas
    if ver >= 7:
        rem = ver
        for _ in range(12):
            rem = (rem << 1) ^ ((rem >> 11) * 0x1F25)
        bits = ver << 12 | rem
        for i in range(18):
            d = (bits >> i) & 1 == 1
            a, b2 = size - 11 + i % 3, i // 3
            setf(a, b2, d)
            setf(b2, a, d)

    # data in the zig-zag order
    i = 0
    right = size - 1
    while right >= 1:
        if right == 6:
            right = 5
        for vert in range(size):
            for j in range(2):
                x = right - j
                upward = ((right + 1) & 2) == 0
                y = size - 1 - vert if upward else vert
                if not fun[y][x] and i < len(words) * 8:
                    mod[y][x] = (words[i >> 3] >> (7 - (i & 7))) & 1 == 1
                    i += 1
        right -= 2

    masks = [lambda x, y: (x + y) % 2 == 0, lambda x, y: y % 2 == 0, lambda x, y: x % 3 == 0,
             lambda x, y: (x + y) % 3 == 0, lambda x, y: (x // 3 + y // 2) % 2 == 0,
             lambda x, y: x * y % 2 + x * y % 3 == 0, lambda x, y: (x * y % 2 + x * y % 3) % 2 == 0,
             lambda x, y: ((x + y) % 2 + x * y % 3) % 2 == 0]

    def apply(m):
        f = masks[m]
        for y in range(size):
            for x in range(size):
                if not fun[y][x] and f(x, y):
                    mod[y][x] = not mod[y][x]

    def penalty():
        p = 0
        for grid in (mod, list(map(list, zip(*mod)))):  # rows, then columns: runs of 5+
            for row in grid:
                run, prev = 0, None
                for c in row:
                    run = run + 1 if c == prev else 1
                    prev = c
                    if run == 5:
                        p += 3
                    elif run > 5:
                        p += 1
        for y in range(size - 1):  # 2x2 blocks
            for x in range(size - 1):
                c = mod[y][x]
                if c == mod[y][x + 1] == mod[y + 1][x] == mod[y + 1][x + 1]:
                    p += 3
        dark = sum(map(sum, mod))
        p += abs(dark * 20 - size * size * 10) // (size * size) * 10  # balance
        return p

    best, best_p = 0, None
    for m in range(8):
        apply(m)
        draw_format(m)
        p = penalty()
        if best_p is None or p < best_p:
            best, best_p = m, p
        apply(m)  # undo (XOR)
    apply(best)
    draw_format(best)
    return mod


def rows(text, quiet=2):
    m = make(text)
    n = len(m) + 2 * quiet
    blank = "0" * n
    out = [blank] * quiet
    for r in m:
        out.append("0" * quiet + "".join("1" if c else "0" for c in r) + "0" * quiet)
    return out + [blank] * quiet


def svg(text, scale=8, quiet=4):
    m = make(text)
    n = len(m) + 2 * quiet
    path = "".join(f"M{x + quiet},{y + quiet}h1v1h-1z" for y, r in enumerate(m) for x, c in enumerate(r) if c)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {n} {n}" width="{n * scale}" height="{n * scale}" '
            f'shape-rendering="crispEdges"><rect width="{n}" height="{n}" fill="#fff"/><path d="{path}" fill="#000"/></svg>')


def html_page(items):
    cards = "".join(
        f'<div class="card"><h2>{html.escape(label)}</h2>{svg(url)}<a href="{html.escape(url)}">{html.escape(url)}</a></div>'
        for label, url in items)
    return f"""<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>OBS Remote - phone address</title>
<style>body{{font:16px system-ui,sans-serif;background:#0e1116;color:#e6edf3;margin:0;padding:24px;text-align:center}}
h1{{font-size:22px;margin:0 0 6px}}p{{color:#8b949e;margin:0 0 20px}}.wrap{{display:flex;flex-wrap:wrap;gap:20px;justify-content:center}}
.card{{background:#161b22;border:1px solid #2a323d;border-radius:14px;padding:16px}}h2{{font-size:16px;margin:0 0 10px}}
svg{{display:block;margin:0 auto 10px;border-radius:6px;max-width:72vw;height:auto}}a{{color:#58a6ff;word-break:break-all}}</style>
<h1>OBS Remote</h1><p>Point your phone's camera at a code, then open the link. Then enter the OBS WebSocket password and add it to your home screen.</p>
<div class="wrap">{cards}</div></html>"""


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "--rows":
        print("\n".join(rows(sys.argv[2])))
    elif len(sys.argv) >= 4 and sys.argv[1] == "--html":
        items = [a.split("|", 1) for a in sys.argv[3:]]
        with open(sys.argv[2], "w", encoding="utf-8") as f:
            f.write(html_page(items))
    else:
        sys.exit(__doc__)

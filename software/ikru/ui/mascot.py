"""Renders data/ascii-art.png as truecolor half-block ANSI art (2 image pixels per terminal cell)."""
import os


def render(path, width=26, bg_tol=28):
    """Returns a list of ANSI strings (one per terminal row) or [] if the image/Pillow is unavailable."""
    try:
        from PIL import Image
        img = Image.open(path).convert("RGB")
    except Exception:
        return []
    bg = img.getpixel((0, 0))

    def is_bg(p):
        return all(abs(p[i] - bg[i]) <= bg_tol for i in range(3))

    w, h = img.size
    px = img.load()
    xs = [x for x in range(0, w, 2) for y in range(0, h, 4) if not is_bg(px[x, y])]
    ys = [y for x in range(0, w, 4) for y in range(0, h, 2) if not is_bg(px[x, y])]
    if xs and ys:
        img = img.crop((max(0, min(xs) - 2), max(0, min(ys) - 2), min(w, max(xs) + 3), min(h, max(ys) + 3)))
    w, h = img.size
    th = max(2, int(width * h / w) // 2 * 2)
    img = img.resize((width, th), Image.BOX)
    px = img.load()
    rows = []
    for y in range(0, th, 2):
        line = []
        for x in range(width):
            t, b = px[x, y], px[x, y + 1]
            tb, bb = is_bg(t), is_bg(b)
            if tb and bb:
                line.append(" ")
            elif tb:
                line.append("\x1b[38;2;%d;%d;%dm\u2584\x1b[0m" % b)
            elif bb:
                line.append("\x1b[38;2;%d;%d;%dm\u2580\x1b[0m" % t)
            else:
                line.append("\x1b[38;2;%d;%d;%d;48;2;%d;%d;%dm\u2580\x1b[0m" % (t + b))
        rows.append("".join(line).rstrip())
    return rows

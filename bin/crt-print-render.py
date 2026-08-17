#!/usr/bin/env python3
# Rasterize plain text to a PNG sized for the Phomemo M02 (384px print head
# width is the standard for this model -- CRT_PRINT_WIDTH overrides if the
# real hardware differs). Reads text on stdin, writes PNG to argv[1].
#
#   [rest: vault:crt/header-archaeology-20260817.md]
import sys, os, textwrap
from PIL import Image, ImageDraw, ImageFont

WIDTH = int(os.environ.get("CRT_PRINT_WIDTH", "384"))
FONT_SIZE = int(os.environ.get("CRT_PRINT_FONT_SIZE", "16"))
MARGIN = 8

FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
]


def load_font():
    for path in FONT_CANDIDATES:
        if os.path.exists(path):
            return ImageFont.truetype(path, FONT_SIZE)
    return ImageFont.load_default()


def main():
    if len(sys.argv) < 2:
        sys.stderr.write("usage: crt-print-render.py out.png < text\n")
        sys.exit(2)
    out_path = sys.argv[1]
    text = sys.stdin.read()

    font = load_font()
    # Rough chars-per-line from a monospace glyph width guess; good enough
    # for a first draft, retune CRT_PRINT_FONT_SIZE once real output exists.
    char_w = FONT_SIZE * 0.6
    cols = max(10, int((WIDTH - MARGIN * 2) / char_w))

    lines = []
    for para in text.splitlines():
        if not para.strip():
            lines.append("")
            continue
        lines.extend(textwrap.wrap(para, cols) or [""])

    line_h = int(FONT_SIZE * 1.3)
    height = MARGIN * 2 + line_h * max(1, len(lines))

    img = Image.new("1", (WIDTH, height), color=1)  # 1-bit, white bg
    draw = ImageDraw.Draw(img)
    y = MARGIN
    for line in lines:
        draw.text((MARGIN, y), line, font=font, fill=0)
        y += line_h

    img.save(out_path)


if __name__ == "__main__":
    main()

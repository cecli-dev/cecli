"""Generate Tauri app icons from the desktop favicon SVG.

CairoSVG renders the same ``CE_`` artwork the browser uses as its favicon. If
CairoSVG is unavailable, a procedural fallback icon keeps the script usable
with only the Python standard library.
"""

import math
import os
import struct
import zlib

ICON_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src-tauri", "icons"
)
SVG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "ui",
    "public",
    "cecli-temp-logo-favicon.svg",
)
SUPERSAMPLE = 4
TARGETS = (
    (1024, "icon.png"),
    (512, "512x512.png"),
    (256, "128x128@2x.png"),
    (128, "128x128.png"),
    (32, "32x32.png"),
)

BG_TOP = (0.12, 0.08, 0.33)
BG_BOTTOM = (0.02, 0.58, 0.72)
GLOW_COLOR = (0.60, 0.92, 1.00)
PANEL_COLOR = (0.72, 0.93, 1.00)
RIM_COLOR = (0.60, 0.95, 1.00)
LETTER_TOP = (1.00, 1.00, 1.00)
LETTER_BOTTOM = (0.42, 0.94, 1.00)


def main():
    """Render every target icon and write PNG, ICO, and ICNS files."""
    os.makedirs(ICON_DIR, exist_ok=True)
    pngs = {}
    use_svg = os.path.isfile(SVG_PATH)
    if not use_svg:
        print(f"warning: {SVG_PATH} is missing; using the fallback icon")

    for size, name in TARGETS:
        data = None
        if use_svg:
            try:
                data = render_svg_png(size)
            except Exception as err:
                print(f"warning: cannot render {SVG_PATH}: {err}; using fallback icon")
                use_svg = False
        if data is None:
            data = render_fallback_png(size)

        pngs[size] = data
        path = os.path.join(ICON_DIR, name)
        write_file(path, pngs[size])
        print(f"{path} {size}x{size} {os.path.getsize(path)} bytes")

    ico_path = os.path.join(ICON_DIR, "icon.ico")
    write_file(ico_path, encode_ico(pngs[256]))
    print(f"{ico_path} {os.path.getsize(ico_path)} bytes")

    icns_path = os.path.join(ICON_DIR, "icon.icns")
    write_file(icns_path, encode_icns(pngs))
    print(f"{icns_path} {os.path.getsize(icns_path)} bytes")


def render_svg_png(size):
    """Render the favicon SVG to PNG bytes at one square size."""
    import cairosvg

    return cairosvg.svg2png(url=SVG_PATH, output_width=size, output_height=size)


def render_fallback_png(size):
    """Render the procedural icon when CairoSVG cannot read the SVG."""
    rgba = render_icon(size)
    pixels = downsample(rgba, size * SUPERSAMPLE, size)
    return encode_png(size, size, pixels)


def render_icon(size):
    """Render one icon at ``size * SUPERSAMPLE`` resolution, returning RGBA bytes."""
    hi = size * SUPERSAMPLE
    buffer = bytearray(hi * hi * 4)
    inv = 1.0 / hi
    sqrt = math.sqrt
    fabs = math.fabs
    atan2 = math.atan2

    for py in range(hi):
        v = (py + 0.5) * inv
        dv = v - 0.5
        row_start = py * hi * 4

        for px in range(hi):
            u = (px + 0.5) * inv
            du = u - 0.5

            qx = fabs(du) - 0.25
            qy = fabs(dv) - 0.25
            mx = qx if qx > 0.0 else 0.0
            my = qy if qy > 0.0 else 0.0
            inner = qx if qx > qy else qy

            if inner > 0.0:
                inner = 0.0

            sdf = sqrt(mx * mx + my * my) + inner - 0.22

            if sdf > 0.0:
                continue

            t = 0.5 * (u + v)
            red = BG_TOP[0] + (BG_BOTTOM[0] - BG_TOP[0]) * t
            green = BG_TOP[1] + (BG_BOTTOM[1] - BG_TOP[1]) * t
            blue = BG_TOP[2] + (BG_BOTTOM[2] - BG_TOP[2]) * t

            vignette = 1.0 - 1.45 * (du * du + dv * dv)

            if vignette < 0.62:
                vignette = 0.62

            red *= vignette
            green *= vignette
            blue *= vignette

            gdx = u - 0.40
            gdy = v - 0.34
            glow = sqrt(gdx * gdx + gdy * gdy) * 1.75

            if glow < 1.0:
                k = 1.0 - glow
                k = k * k * 0.55
                red += (GLOW_COLOR[0] - red) * k
                green += (GLOW_COLOR[1] - green) * k
                blue += (GLOW_COLOR[2] - blue) * k

            pqx = fabs(du) - 0.18
            pqy = fabs(dv) - 0.18
            pmx = pqx if pqx > 0.0 else 0.0
            pmy = pqy if pqy > 0.0 else 0.0
            pinner = pqx if pqx > pqy else pqy

            if pinner > 0.0:
                pinner = 0.0

            panel = sqrt(pmx * pmx + pmy * pmy) + pinner - 0.14

            if panel <= 0.0:
                if panel > -0.010:
                    k = (1.0 + panel / 0.010) * 0.30
                else:
                    k = 0.10

                red += (PANEL_COLOR[0] - red) * k
                green += (PANEL_COLOR[1] - green) * k
                blue += (PANEL_COLOR[2] - blue) * k

            if sdf > -0.013:
                k = (1.0 + sdf / 0.013) * 0.55
                red += (RIM_COLOR[0] - red) * k
                green += (RIM_COLOR[1] - green) * k
                blue += (RIM_COLOR[2] - blue) * k

            ld = sqrt(du * du + dv * dv)

            if 0.16 < ld < 0.30:
                k = 1.0 - fabs(ld - 0.195) / 0.105
                k = k * k * 0.10
                red += (LETTER_BOTTOM[0] - red) * k
                green += (LETTER_BOTTOM[1] - green) * k
                blue += (LETTER_BOTTOM[2] - blue) * k

            ring = fabs(ld - 0.195) - 0.037

            if ring <= 0.0 and fabs(atan2(dv, du)) > 0.42:
                lt = (v - 0.30) / 0.40

                if lt < 0.0:
                    lt = 0.0
                elif lt > 1.0:
                    lt = 1.0

                red = LETTER_TOP[0] + (LETTER_BOTTOM[0] - LETTER_TOP[0]) * lt
                green = LETTER_TOP[1] + (LETTER_BOTTOM[1] - LETTER_TOP[1]) * lt
                blue = LETTER_TOP[2] + (LETTER_BOTTOM[2] - LETTER_TOP[2]) * lt

            index = row_start + px * 4
            buffer[index] = int(red * 255.0 + 0.5)
            buffer[index + 1] = int(green * 255.0 + 0.5)
            buffer[index + 2] = int(blue * 255.0 + 0.5)
            buffer[index + 3] = 255

    return bytes(buffer)


def downsample(source, hi_size, low_size):
    """Box-filter ``source`` from ``hi_size`` down to ``low_size`` in premultiplied alpha."""
    scale = hi_size // low_size
    samples = scale * scale
    half_samples = samples // 2
    output = bytearray(low_size * low_size * 4)

    for y in range(low_size):
        for x in range(low_size):
            sum_r = 0
            sum_g = 0
            sum_b = 0
            sum_a = 0
            base = (y * scale) * hi_size + x * scale

            for oy in range(scale):
                index = (base + oy * hi_size) * 4

                for _ in range(scale):
                    alpha = source[index + 3]
                    sum_r += source[index] * alpha
                    sum_g += source[index + 1] * alpha
                    sum_b += source[index + 2] * alpha
                    sum_a += alpha
                    index += 4

            out_index = (y * low_size + x) * 4

            if sum_a:
                output[out_index] = (sum_r + sum_a // 2) // sum_a
                output[out_index + 1] = (sum_g + sum_a // 2) // sum_a
                output[out_index + 2] = (sum_b + sum_a // 2) // sum_a
                output[out_index + 3] = (sum_a + half_samples) // samples

    return bytes(output)


def encode_png(width, height, rgba):
    """Encode straight RGBA bytes as an 8-bit truecolour-alpha PNG."""
    stride = width * 4
    raw = bytearray()

    for y in range(height):
        raw.append(0)
        raw.extend(rgba[y * stride : (y + 1) * stride])

    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return b"".join(
        (
            b"\x89PNG\r\n\x1a\n",
            _png_chunk(b"IHDR", header),
            _png_chunk(b"IDAT", zlib.compress(bytes(raw), 9)),
            _png_chunk(b"IEND", b""),
        )
    )


def encode_ico(png):
    """Wrap a 256x256 PNG in a single-image Vista-style ICO container."""
    header = struct.pack("<HHH", 0, 1, 1)
    entry = struct.pack("<BBBBHHII", 0, 0, 0, 0, 1, 32, len(png), 22)
    return header + entry + png


def encode_icns(pngs):
    """Wrap 128/256/512/1024 PNGs in an ICNS container."""
    chunks = b"".join(
        tag + struct.pack(">I", len(pngs[size]) + 8) + pngs[size]
        for tag, size in ((b"ic07", 128), (b"ic08", 256), (b"ic09", 512), (b"ic10", 1024))
    )
    return b"icns" + struct.pack(">I", len(chunks) + 8) + chunks


def write_file(path, payload):
    """Write one generated icon atomically enough for a local build script."""
    with open(path, "wb") as handle:
        handle.write(payload)


def _png_chunk(tag, data):
    """Build a length-prefixed, CRC-terminated PNG chunk."""
    crc = zlib.crc32(tag + data) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)


if __name__ == "__main__":
    main()

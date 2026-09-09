"""Turns a generated history map's ASCII text into a vintage 1950s-style
subway-map illustration via fal's image-edit model. Always fal, regardless
of whatever provider the Visuals tab itself is currently set to -- this
needs real image-in/image-out editing, which the local (text-to-image-only)
provider can't do.

Deliberately two steps rather than one from-scratch text-to-image prompt:
rendering the map's own text to a plain reference image first gives the
edit model actual layout and label positions to preserve, rather than
inventing its own from a text description alone. A second reference image
(config.SUBWAY_MAP_STYLE_REFERENCE_IMAGE, a real 1950s NYC subway map) rides
along purely for illustration style -- see config.yaml's subway_map.prompt
for how the two are told apart.
"""

from PIL import Image, ImageDraw, ImageFont

from . import config
from . import storage
from .providers import get_provider

# Common monospace font locations, tried in order -- Menlo/Courier New on
# macOS, DejaVu Sans Mono on most Linux installs. Falls back to PIL's tiny
# built-in bitmap font (still legible enough for the model to read off of)
# if none of these exist.
_FONT_CANDIDATES = [
    "/System/Library/Fonts/Menlo.ttc",
    "/System/Library/Fonts/Supplemental/Courier New.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
]


def _load_font(size: int):
    for path in _FONT_CANDIDATES:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


# The procedural map (citymap.py) rasterizes its coastline as Unicode
# Braille Patterns characters (U+2800-U+28FF, one glyph = a 2x4 dot cell),
# for a much finer coastline than a block-character grid gives. Neither
# Menlo nor Courier New (this file's regular text fonts) carry glyphs for
# that block, so handing a rendered line straight to draw.text() silently
# fell back to whatever placeholder glyph the OS substituted -- garbled
# boxes, not dots, which is what an image-edit model would see as noise
# rather than a coastline. Decoding each character's 8 dot-bits ourselves
# and drawing them as small circles sidesteps font coverage entirely, and
# is portable rather than depending on a macOS-only Braille font install.
_BRAILLE_LOW = 0x2800
_BRAILLE_HIGH = 0x28FF
_BRAILLE_DOT_BITS = {  # (column, row) within the cell's 2x4 dot grid -> bit
    (0, 0): 0x01, (0, 1): 0x02, (0, 2): 0x04, (0, 3): 0x40,
    (1, 0): 0x08, (1, 1): 0x10, (1, 2): 0x20, (1, 3): 0x80,
}


def _draw_braille_cell(draw, x: float, y: float, cell_width: float, cell_height: float, codepoint: int):
    bits = codepoint - _BRAILLE_LOW
    dot_w, dot_h = cell_width / 2, cell_height / 4
    radius = min(dot_w, dot_h) * 0.32
    for (col, row), bit in _BRAILLE_DOT_BITS.items():
        if not (bits & bit):
            continue
        cx, cy = x + dot_w * (col + 0.5), y + dot_h * (row + 0.5)
        draw.ellipse([cx - radius, cy - radius, cx + radius, cy + radius], fill="black")


def render_map_image(map_text: str) -> Image.Image:
    """Plain black-on-white monospace rendering of `map_text` -- just
    legible enough for the image-edit model to read layout and labels off
    of, not meant to be shown to a user on its own. Drawn character by
    character (rather than one draw.text() per line) so Braille coastline
    cells can be rasterized as real dots -- see _draw_braille_cell."""
    font = _load_font(config.SUBWAY_MAP_RENDER_FONT_SIZE)
    lines = map_text.split("\n")
    pad = config.SUBWAY_MAP_RENDER_PADDING

    measurer = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    cell_width = measurer.textlength("M", font=font) or config.SUBWAY_MAP_RENDER_FONT_SIZE * 0.6
    bbox = font.getbbox("Mgy")
    cell_height = (bbox[3] - bbox[1]) + 6

    max_len = max((len(line) for line in lines), default=0)
    width = int(cell_width * max_len) + pad * 2
    height = int(cell_height * len(lines)) + pad * 2
    image = Image.new("RGB", (max(width, 1), max(height, 1)), "white")
    draw = ImageDraw.Draw(image)

    for row, line in enumerate(lines):
        y = pad + row * cell_height
        for col, ch in enumerate(line):
            if ch == " ":
                continue
            x = pad + col * cell_width
            code = ord(ch)
            if _BRAILLE_LOW <= code <= _BRAILLE_HIGH:
                _draw_braille_cell(draw, x, y, cell_width, cell_height, code)
            else:
                draw.text((x, y), ch, font=font, fill="black")
    return image


def generate_subway_map(map_text: str) -> dict:
    style_ref = config.SUBWAY_MAP_STYLE_REFERENCE_IMAGE
    if not style_ref.exists():
        raise RuntimeError(f"subway map style reference image not found: {style_ref}")

    rendered = render_map_image(map_text)
    rendered_path = storage.save_pil_image(rendered, directory=config.UPLOADS_DIR)
    provider = get_provider("fal")
    return provider.generate_image(
        config.SUBWAY_MAP_PROMPT, image_paths=[str(rendered_path), str(style_ref)],
    )

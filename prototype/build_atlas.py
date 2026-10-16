"""Pack Codex NABO frames into a pre-scaled sprite atlas for the DIVE prototype.

Reads ``game-art/dive/manifest.json``, scales every frame of every skin with one
shared factor (the manifest's ``preview_scale_to_actual``), and writes
``prototype/assets/nabo_atlas.js``. The atlas PNG is embedded as a data URI so
the prototype can read pixels back (RGB565 preview) even from ``file://``.

Besides the original frames it bakes two variants with the same layout:
``png_dark`` (the light sticker-style outer outline recoloured dark) and
``png_rim`` (a white mask of top-facing silhouette edges, tinted at runtime).

Usage:
    python3 game-art/dive/prototype/build_atlas.py
"""

import base64
import io
import json
import logging
from pathlib import Path
from typing import Dict, List

import numpy as np
from PIL import Image
from scipy import ndimage

logger = logging.getLogger(__name__)

DIVE_DIR = Path(__file__).resolve().parent.parent
MANIFEST = DIVE_DIR / "manifest.json"
OUT_JS = Path(__file__).resolve().parent / "assets" / "nabo_atlas.js"
OUTLINE_RGB = (16, 30, 52)     # 替换白色外描边的深色
LIGHT_MIN = 185                # 三个通道都高于它算“浅色”
RIM_REACH = 8                  # 源图上往上看多少像素内是透明就算受光边


def _scale(img: Image.Image, cell: int) -> Image.Image:
    """Downscale an RGBA image using premultiplied alpha to avoid dark fringes."""
    return img.convert("RGBa").resize((cell, cell), Image.LANCZOS).convert("RGBA")


def _darken_outer_outline(img: Image.Image) -> Image.Image:
    """Recolour light pixels connected to the transparent outside (the sticker outline)."""
    a = np.asarray(img, dtype=np.uint8).copy()
    alpha = a[..., 3]
    outside = alpha < 40
    light = (a[..., :3].min(axis=2) > LIGHT_MIN) & ~outside
    band = ndimage.binary_propagation(outside, mask=outside | light) & light
    a[band, 0], a[band, 1], a[band, 2] = OUTLINE_RGB
    return Image.fromarray(a, "RGBA")


def _rim_mask(img: Image.Image) -> Image.Image:
    """White mask of opaque pixels that see transparency straight above (light from the surface)."""
    alpha = np.asarray(img, dtype=np.float32)[..., 3] / 255.0
    rim = np.zeros_like(alpha)
    for k in range(1, RIM_REACH + 1):
        above = np.ones_like(alpha)
        above[k:] = alpha[:-k]
        rim = np.maximum(rim, (above < 0.25) * (1 - (k - 1) / RIM_REACH))
    rim *= alpha
    out = np.zeros(alpha.shape + (4,), dtype=np.uint8)
    out[..., :3] = 255
    out[..., 3] = (rim * 255).astype(np.uint8)
    return Image.fromarray(out, "RGBA")


def build_atlas() -> Dict:
    """Build the atlas image and metadata from the manifest.

    Returns:
        Metadata dict written into the generated JS module.

    Raises:
        FileNotFoundError: When the manifest or a referenced frame is missing.
    """
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    canvas = manifest["canvas"][0]
    scale = float(manifest["preview_scale_to_actual"])
    cell = round(canvas * scale)
    anchor = [round(v * scale, 2) for v in manifest["anchor"]]

    skins = list(manifest["skins"].keys())
    clips = list(manifest["animations"].keys())  # Codex 新增的动作自动进图集
    cols = sum(manifest["animations"][c]["frame_count"] for c in clips)
    size = (cols * cell, len(skins) * cell)
    sheet = Image.new("RGBA", size, (0, 0, 0, 0))
    sheet_dark = Image.new("RGBA", size, (0, 0, 0, 0))
    sheet_rim = Image.new("RGBA", size, (0, 0, 0, 0))

    meta: Dict = {
        "cell": cell,
        "anchor": anchor,
        "scale": scale,
        "revision": manifest.get("revision"),
        "default_skin": manifest.get("default_skin", skins[0]),
        "skins": {},
    }
    for row, skin in enumerate(skins):
        col = 0
        anims: Dict[str, Dict] = {}
        for clip in clips:
            spec = manifest["animations"][clip]
            rects: List[List[int]] = []
            for rel in spec["skin_frames"][skin]:
                frame_path = DIVE_DIR / rel
                if not frame_path.exists():
                    logger.error("Missing frame: %s", frame_path)
                    raise FileNotFoundError(frame_path)
                src = Image.open(frame_path).convert("RGBA")
                at = (col * cell, row * cell)
                sheet.paste(_scale(src, cell), at)
                sheet_dark.paste(_scale(_darken_outer_outline(src), cell), at)
                sheet_rim.paste(_scale(_rim_mask(src), cell), at)
                rects.append([col * cell, row * cell])
                col += 1
            anims[clip] = {"fps": spec.get("fps", manifest["fps"]), "loop": spec["loop"], "frames": rects}
        meta["skins"][skin] = {"name": manifest["skins"][skin]["name"], "anims": anims}

    for key, img in (("png", sheet), ("png_dark", sheet_dark), ("png_rim", sheet_rim)):
        meta[key] = _data_uri(img)
    logger.info("Atlas %dx%d, cell %d px", sheet.width, sheet.height, cell)
    return meta


def _data_uri(img: Image.Image) -> str:
    """Encode an image as a PNG data URI."""
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def main() -> None:
    """Generate ``assets/nabo_atlas.js``."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    meta = build_atlas()
    OUT_JS.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(meta, ensure_ascii=False, separators=(",", ":"))
    OUT_JS.write_text(f"// 由 build_atlas.py 生成，不要手改\nwindow.NABO_ATLAS = {body};\n", encoding="utf-8")
    logger.info("Wrote %s", OUT_JS)


if __name__ == "__main__":
    main()

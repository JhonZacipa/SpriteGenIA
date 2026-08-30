from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

Color = tuple[int, int, int]


def load_palette(path: str | Path) -> list[Color]:
    """Lee una paleta en texto plano: un color hex por línea (#RRGGBB o RRGGBB).

    Compatible con las paletas descargables de lospec.com (formato HEX).
    """
    colors: list[Color] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip().lstrip("#")
        if not line or line.startswith(";"):
            continue
        if len(line) == 6:
            colors.append(tuple(int(line[i : i + 2], 16) for i in (0, 2, 4)))
    if not colors:
        raise ValueError(f"No se encontraron colores hex en {path}")
    return colors


def save_palette(path: str | Path, colors: list[Color]) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    lines = [f"#{r:02X}{g:02X}{b:02X}" for r, g, b in colors]
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def extract_palette(img: Image.Image, n: int = 32) -> list[Color]:
    """Extrae los N colores dominantes de una imagen (ignorando transparencia)."""
    rgba = img.convert("RGBA")
    arr = np.asarray(rgba)
    opaque = arr[arr[..., 3] > 0, :3]
    # Fondo del color medio del sujeto: los huecos transparentes no aportan
    # un color falso a la extracción
    fill = tuple(opaque.mean(axis=0).astype(int)) if len(opaque) else (0, 0, 0)
    rgb = Image.new("RGB", rgba.size, fill)
    rgb.paste(rgba, mask=rgba.getchannel("A"))
    quantized = rgb.quantize(colors=n, method=Image.Quantize.MEDIANCUT)
    flat = quantized.getpalette()[: n * 3]
    colors = [tuple(flat[i : i + 3]) for i in range(0, len(flat), 3)]
    seen: list[Color] = []
    for c in colors:
        if c not in seen:
            seen.append(c)
    return seen

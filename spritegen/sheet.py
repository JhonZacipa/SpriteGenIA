from __future__ import annotations

from math import ceil
from pathlib import Path

from PIL import Image


def make_sheet(paths: list[str | Path], cols: int | None = None) -> Image.Image:
    """Une frames del mismo tamaño en un sprite sheet con fondo transparente."""
    frames = [Image.open(p).convert("RGBA") for p in paths]
    if not frames:
        raise ValueError("No hay frames para el sprite sheet")
    w, h = frames[0].size
    for p, f in zip(paths, frames):
        if f.size != (w, h):
            raise ValueError(
                f"Todos los frames deben medir lo mismo: {p} mide {f.size}, "
                f"se esperaba {(w, h)}"
            )
    cols = cols or len(frames)
    rows = ceil(len(frames) / cols)
    sheet = Image.new("RGBA", (cols * w, rows * h), (0, 0, 0, 0))
    for i, frame in enumerate(frames):
        sheet.paste(frame, ((i % cols) * w, (i // cols) * h))
    return sheet

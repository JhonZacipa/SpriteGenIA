"""Importar imágenes ajenas al historial.

Una imagen cualquiera (foto, render, dibujo, PNG de otra herramienta) se
registra como una entrada `sprite` más: su original en `output/raw/`, su copia
visible en `output/` y su ficha en `output/meta/`. A partir de ahí la GUI y la
CLI la tratan como a cualquier pieza generada: animarla por video, pedir una
variación Klein, pixelizarla... Se guarda TAL CUAL: sin recortar fondo, sin
sombra y sin pixelizar, porque no se sabe qué es (una foto no tiene fondo
plano que quitar).
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from PIL import Image, ImageOps

from spritegen.generate import PROJECT_ROOT, slugify, unique_stem

OUTPUT_DIR = PROJECT_ROOT / "output"
META_DIR = OUTPUT_DIR / "meta"


def import_image(
    img: Image.Image,
    *,
    name: str,
    subject: str | None = None,
    hidden: bool = False,
) -> str:
    """Registra `img` en el historial y devuelve el stem creado.

    `name` es el nombre de archivo original: de él sale el stem (minúsculas,
    sin tildes ni espacios, único con sufijo _vN) y, si no se da `subject`,
    la descripción de la ficha.
    """
    (OUTPUT_DIR / "raw").mkdir(parents=True, exist_ok=True)
    META_DIR.mkdir(parents=True, exist_ok=True)
    titulo = Path(name).stem.strip() or "importado"
    stem = unique_stem(META_DIR, slugify(titulo) or "importado")

    # Las fotos de móvil llevan la rotación en EXIF: aplicarla, o Wan
    # animaría una imagen tumbada. Siempre RGBA para que el resto del
    # pipeline (fondo, pixelizado, video) encuentre el canal alfa que espera.
    rgba = ImageOps.exif_transpose(img).convert("RGBA")
    rgba.save(OUTPUT_DIR / "raw" / f"{stem}.png")
    rgba.save(OUTPUT_DIR / f"{stem}.png")

    meta = {
        "subject": subject.strip() if subject and subject.strip() else titulo,
        "engine": None,          # no la dibujó ningún motor
        "seed": 0,
        "raw": f"{stem}.png",
        "sprite": f"{stem}.png",
        # Se muestra sin tocar: la «rejilla» es su lado mayor real y no hay
        # reescalado. Si luego se pixeliza (🧹 Quitar sombra) parte de aquí.
        "native": max(rgba.size),
        "scale": 1,
        "colors": None,
        "method": "box",         # imagen suave: box limpia mejor que nearest
        "used_palette": False,
        "raw_prompt": False,
        "steps": 0,
        "cfg": 0,
        "imported": True,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    if hidden:
        meta["hidden"] = True
    (META_DIR / f"{stem}.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return stem


def import_file(path: Path, *, subject: str | None = None) -> str:
    """Versión para la CLI: abre el archivo y lo registra."""
    with Image.open(path) as img:
        img.load()
        return import_image(img, name=path.name, subject=subject)

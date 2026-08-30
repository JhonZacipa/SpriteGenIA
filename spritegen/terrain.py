"""Terreno para mapas top-down: tiles base seamless, transiciones y tilesets.

Flujo: la IA genera una textura de suelo → se pixeliza → se cortan varias
variantes de tile → cada una se vuelve *seamless* (reparación de costura con
dithering determinista). Las 16 piezas de transición entre dos terrenos se
construyen matemáticamente (esquinas Wang con borde dentado), porque ahí la
IA no puede dar consistencia. El mapa final se pinta en el motor (Godot o
Tiled) usando el tileset PNG que exportamos.
"""

from __future__ import annotations

import json
import random
import shutil
import time
from pathlib import Path

import numpy as np
from PIL import Image

from spritegen import engines as eng
from spritegen.generate import (
    DEFAULT_SERVER,
    PROJECT_ROOT,
    build_workflow,
    ensure_server,
    load_config,
    run_workflow,
    slugify,
    unique_stem,
)
from spritegen.pixelize import pixelize
from spritegen.sheet import make_sheet

TERRAIN_DIR = PROJECT_ROOT / "output" / "terrain"
TILE = 64  # px nativos por tile (personaje de 128 = 2 tiles de alto)

TERRAIN_TEMPLATE = (
    "pixel art, {subject}, top-down ground texture for a 2d game, seamless "
    "repeating pattern, flat even lighting, uniform density, no objects, "
    "no shadows, full frame texture"
)
TERRAIN_NEGATIVE_EXTRA = (
    ", vignette, 3d perspective, horizon, sky, border, frame, objects, "
    "creature, building, text"
)


# ---------------------------------------------------------------------------
# Tiles base
# ---------------------------------------------------------------------------

def cut_tile_variants(texture: Image.Image, variants: int = 4) -> list[Image.Image]:
    """Corta una textura nativa en tiles de 64 y devuelve las N variantes más
    homogéneas (las más cercanas al color medio global, sin elementos raros)."""
    rgb = texture.convert("RGB")
    cols, rows = rgb.width // TILE, rgb.height // TILE
    if cols == 0 or rows == 0:
        raise ValueError(f"La textura ({rgb.width}x{rgb.height}) es menor que un tile de {TILE}")
    arr = np.asarray(rgb).astype(np.float32)
    global_mean = arr.reshape(-1, 3).mean(axis=0)
    candidates = []
    for r in range(rows):
        for c in range(cols):
            block = arr[r * TILE : (r + 1) * TILE, c * TILE : (c + 1) * TILE]
            score = float(np.linalg.norm(block.reshape(-1, 3).mean(axis=0) - global_mean))
            candidates.append((score, r, c))
    candidates.sort(key=lambda item: item[0])
    out = []
    for _, r, c in candidates[: max(1, variants)]:
        out.append(rgb.crop((c * TILE, r * TILE, (c + 1) * TILE, (r + 1) * TILE)))
    return out


def make_seamless(tile: Image.Image, band: int = 8) -> Image.Image:
    """Vuelve un tile repetible sin costuras.

    Se desplaza medio tile (los bordes externos quedan seamless por
    construcción) y la costura en cruz que queda dentro se disimula
    intercambiando píxeles con su reflejo mediante dithering determinista.
    """
    a = np.asarray(tile.convert("RGB")).copy()
    h, w = a.shape[:2]
    a = np.roll(a, (h // 2, w // 2), (0, 1))
    ys, xs = np.mgrid[0:h, 0:w]
    noise = (((xs * 73856093) ^ (ys * 19349663)) % 1000) / 1000.0
    for axis, mid in ((0, h // 2), (1, w // 2)):
        coord = ys if axis == 0 else xs
        dist = np.abs(coord - mid + 0.5)
        prob = np.clip((band - dist) / band, 0, 1) * 0.5
        swap = noise < prob
        if axis == 0:
            reflected = a[np.clip(2 * mid - ys - 1, 0, h - 1), xs]
        else:
            reflected = a[ys, np.clip(2 * mid - xs - 1, 0, w - 1)]
        a = np.where(swap[..., None], reflected, a)
    return Image.fromarray(a)


def generate_terrain(
    subject: str,
    seed: int | None = None,
    variants: int = 4,
    colors: int = 16,
    server: str = DEFAULT_SERVER,
) -> dict:
    """Genera con IA un terreno y guarda sus variantes seamless de 64 px.

    Devuelve el meta registrado en el historial (la lámina de variantes)."""
    eng.require_installed(eng.get_engine("sdxl_pixelart"))  # terreno usa SDXL
    cfg = load_config()
    cfg["prompt_template"] = TERRAIN_TEMPLATE
    cfg["negative_prompt"] = cfg["negative_prompt"] + TERRAIN_NEGATIVE_EXTRA
    seed = seed if seed is not None else random.randrange(2**31)

    ensure_server(server)
    print(f"Generando terreno '{subject}' (seed {seed})...")
    png = run_workflow(server, build_workflow(cfg, subject, seed))

    # Stem único (regla del proyecto): repetir subject+seed no debe pisar el
    # terreno anterior ni mezclar tiles viejos y nuevos en la misma carpeta
    meta_dir = PROJECT_ROOT / "output" / "meta"
    meta_dir.mkdir(parents=True, exist_ok=True)
    stem = unique_stem(meta_dir, f"terreno_{slugify(subject, 22)}_{seed}")
    slug = stem[len("terreno_"):]
    raw_dir = PROJECT_ROOT / "output" / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw_path = raw_dir / f"{stem}.png"
    raw_path.write_bytes(png)

    # Textura nativa de 256 px = rejilla de 4x4 tiles candidatos
    result = pixelize(
        Image.open(raw_path), native=256, scale=1, colors=colors,
        method="box", clean=False,
    )
    tiles = [make_seamless(t) for t in cut_tile_variants(result.native, variants)]

    terrain_path = TERRAIN_DIR / slug
    if terrain_path.is_dir():
        # Sin meta json el directorio es un huérfano de una ejecución fallida:
        # se limpia para no mezclar tiles viejos con los nuevos
        shutil.rmtree(terrain_path)
    terrain_path.mkdir(parents=True, exist_ok=True)
    for i, tile in enumerate(tiles):
        tile.save(terrain_path / f"base_{i:02d}.png")

    # Lámina de variantes para el historial de la GUI
    lamina_paths = []
    for i, tile in enumerate(tiles):
        big = tile.resize((TILE * 4, TILE * 4), Image.Resampling.NEAREST)
        p = terrain_path / f"_variante_{i:02d}.png"
        big.save(p)
        lamina_paths.append(p)
    lamina = make_sheet(lamina_paths, cols=len(lamina_paths))
    lamina_out = PROJECT_ROOT / "output" / f"{stem}.png"
    lamina.save(lamina_out)
    for p in lamina_paths:
        p.unlink()

    meta = {
        "kind": "terrain",
        "subject": f"terreno: {subject}",
        "terrain_id": slug,
        "seed": seed,
        "variants": len(tiles),
        "sprite": lamina_out.name,
        "raw": raw_path.name,
        "native": TILE,
        "scale": 4,
        "colors": colors,
        "used_palette": False,
        "steps": cfg["steps"],
        "cfg": cfg["cfg"],
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    (meta_dir / f"{stem}.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Variantes seamless: {terrain_path} ({len(tiles)} tiles de {TILE}px)")
    return meta


def list_terrains() -> list[dict]:
    items = []
    if TERRAIN_DIR.is_dir():
        for d in sorted(TERRAIN_DIR.iterdir()):
            if d.is_dir():
                n = len(list(d.glob("base_*.png")))
                if n:
                    items.append({"id": d.name, "variants": n})
    return items


def load_terrain(terrain_id: str) -> list[Image.Image]:
    d = TERRAIN_DIR / Path(terrain_id).name
    paths = sorted(d.glob("base_*.png"))
    if not paths:
        raise ValueError(f"No existe el terreno '{terrain_id}' en {TERRAIN_DIR}")
    return [Image.open(p).convert("RGB") for p in paths]


# ---------------------------------------------------------------------------
# Transiciones Wang (16 combinaciones de esquinas) y tileset
# ---------------------------------------------------------------------------

def transition_tiles(
    tile_a: Image.Image, tile_b: Image.Image,
    jag: float = 0.16, edge_darken: float = 0.82,
) -> list[Image.Image]:
    """16 tiles de transición indexados por bitmask de esquinas (NW·NE·SW·SE):
    bit a 1 = esquina de terreno A. El borde se dienta con ruido determinista
    y la orilla de A se oscurece un poco (ribete natural)."""
    A = np.asarray(tile_a.convert("RGB"))
    B = np.asarray(tile_b.convert("RGB"))
    h, w = A.shape[:2]
    U, V = np.meshgrid((np.arange(w) + 0.5) / w, (np.arange(h) + 0.5) / h)
    ys, xs = np.mgrid[0:h, 0:w]
    noise = ((((xs * 2654435761) ^ (ys * 40503)) % 1000) / 1000.0 - 0.5) * 2 * jag

    tiles = []
    for bits in range(16):
        nw, ne, sw, se = (bits >> 3) & 1, (bits >> 2) & 1, (bits >> 1) & 1, bits & 1
        field = (
            nw * (1 - U) * (1 - V) + ne * U * (1 - V)
            + sw * (1 - U) * V + se * U * V + noise
        )
        is_a = field > 0.5
        out = np.where(is_a[..., None], A, B).astype(np.uint16)
        rim = is_a & (field <= 0.5 + 0.09)
        out[rim] = (out[rim] * edge_darken).astype(np.uint16)
        tiles.append(Image.fromarray(out.astype(np.uint8)))
    return tiles


def build_tileset(
    terrain_a: str, terrain_b: str, name: str | None = None
) -> dict:
    """Arma el tileset A+B: variantes base + 16 transiciones + mapa de prueba.

    Exporta el tileset NATIVO (el motor escala con nearest) y registra la
    vista previa del mapa en el historial."""
    a_tiles = load_terrain(terrain_a)
    b_tiles = load_terrain(terrain_b)
    trans = transition_tiles(a_tiles[0], b_tiles[0])

    # El nombre por defecto conserva los ids COMPLETOS (con seed): dos parejas
    # de terrenos distintas no deben colisionar en el mismo fichero
    if name:
        name = slugify(name, 40)
    else:
        name = slugify(f"{Path(terrain_a).name}_{Path(terrain_b).name}", 60)
    meta_dir = PROJECT_ROOT / "output" / "meta"
    meta_dir.mkdir(parents=True, exist_ok=True)
    stem = unique_stem(meta_dir, f"tileset_{name}")
    name = stem[len("tileset_"):]

    # Layout: fila 0 = variantes A y B; filas 1-2 = las 16 transiciones (bitmask
    # NW·NE·SW·SE = columna + fila*8). Documentado en el README.
    cols = 8
    all_tiles = a_tiles[:4] + b_tiles[:4] + trans
    rows = (len(all_tiles) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * TILE, rows * TILE), (0, 0, 0))
    for i, tile in enumerate(all_tiles):
        sheet.paste(tile, ((i % cols) * TILE, (i // cols) * TILE))
    tileset_path = PROJECT_ROOT / "output" / f"{stem}.png"
    sheet.save(tileset_path)

    preview = render_map_preview(a_tiles, b_tiles, trans)
    preview_path = PROJECT_ROOT / "output" / f"{stem}_mapa.png"
    preview.save(preview_path)

    meta = {
        "kind": "tileset",
        "subject": f"tileset {name} ({TILE}px)",
        "seed": 0,
        "sprite": preview_path.name,
        "sheet": tileset_path.name,
        "native": TILE,
        "scale": 2,
        "colors": None,
        "used_palette": False,
        "steps": 0,
        "cfg": 0,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    (meta_dir / f"{stem}.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Tileset : {tileset_path} ({len(all_tiles)} tiles de {TILE}px)")
    print(f"Mapa de prueba: {preview_path}")
    return meta


def render_map_preview(
    a_tiles: list[Image.Image],
    b_tiles: list[Image.Image],
    trans: list[Image.Image],
    cols: int = 14, rows: int = 9, seed: int = 7,
) -> Image.Image:
    """Pinta un mapa demo con autotiling: manchas de terreno B sobre fondo A."""
    rng = random.Random(seed)
    corners = np.ones((rows + 1, cols + 1), dtype=int)
    for _ in range(4):
        cy, cx = rng.uniform(1, rows), rng.uniform(1, cols)
        radius = rng.uniform(1.4, 3.0)
        for r in range(rows + 1):
            for c in range(cols + 1):
                if (r - cy) ** 2 + (c - cx) ** 2 <= radius**2:
                    corners[r, c] = 0

    canvas = Image.new("RGB", (cols * TILE, rows * TILE))
    for r in range(rows):
        for c in range(cols):
            bits = (
                (corners[r, c] << 3) | (corners[r, c + 1] << 2)
                | (corners[r + 1, c] << 1) | corners[r + 1, c + 1]
            )
            if bits == 15:
                tile = rng.choice(a_tiles)
            elif bits == 0:
                tile = rng.choice(b_tiles)
            else:
                tile = trans[bits]
            canvas.paste(tile, (c * TILE, r * TILE))
    return canvas.resize((canvas.width * 2, canvas.height * 2), Image.Resampling.NEAREST)

"""Efectos ambientales procedurales: animación matemática sobre sprites.

Ningún efecto usa la GPU: son deformaciones y dibujos deterministas con loop
perfecto (todas las funciones son periódicas en t ∈ [0,1)). La IA diseña el
objeto base; aquí se le da el movimiento.
"""

from __future__ import annotations

import json
import math
import re
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from spritegen.animate import save_gif
from spritegen.background import hex_to_rgb
from spritegen.generate import PROJECT_ROOT, slugify, unique_stem
from spritegen.sheet import make_sheet

# ---------------------------------------------------------------------------
# Mecer vegetación (sway): copa oscila, base fija
# ---------------------------------------------------------------------------

def sway_frames(
    img: Image.Image, frames: int = 6, amplitude: int | None = None
) -> list[Image.Image]:
    """Balanceo por viento de un sprite nativo: desplaza filas con pivote en
    la base del contenido y desfase por altura (efecto látigo suave)."""
    rgba = np.asarray(img.convert("RGBA"))
    h, w = rgba.shape[:2]
    alpha_rows = np.where(rgba[..., 3].any(axis=1))[0]
    if len(alpha_rows) == 0:
        raise ValueError("El sprite está vacío o completamente transparente")
    y_top, y_bottom = int(alpha_rows[0]), int(alpha_rows[-1])
    height = max(1, y_bottom - y_top)
    amplitude = amplitude if amplitude is not None else max(2, round(height * 0.03))

    pad = amplitude + 1
    out = []
    for i in range(frames):
        phase = 2 * math.pi * (i / frames)
        frame = np.zeros((h, w + pad * 2, 4), dtype=np.uint8)
        for y in range(h):
            # acotado a 1: las filas por encima del contenido no deben
            # producir desplazamientos mayores que la amplitud
            weight = min(1.0, (y_bottom - y) / height) ** 1.4 if y <= y_bottom else 0.0
            dx = pad + round(amplitude * math.sin(phase - weight * 0.9) * weight)
            frame[y, dx : dx + w] = rgba[y]
        out.append(Image.fromarray(frame))
    return out


# ---------------------------------------------------------------------------
# Fuego (flame): llama por capas con parpadeo
# ---------------------------------------------------------------------------

FIRE_COLORS = [
    (127, 15, 15), (201, 47, 26), (255, 115, 0), (255, 176, 46), (255, 233, 120),
]

FLAME_KINDS = {
    # (ancho relativo, alto relativo, nº de lenguas)
    "torch": (0.44, 0.95, 1),
    "campfire": (0.95, 0.75, 3),
    "candle": (0.24, 0.85, 1),
}


def flame_frames(
    kind: str = "torch", size: int = 64, frames: int = 6
) -> list[Image.Image]:
    if kind not in FLAME_KINDS:
        raise ValueError(f"Tipo de fuego desconocido '{kind}': {', '.join(FLAME_KINDS)}")
    width_f, height_f, tongues = FLAME_KINDS[kind]
    W, H = max(16, round(size * width_f)), size
    offsets = [0.0] if tongues == 1 else [-0.26, 0.04, 0.3]

    out = []
    for i in range(frames):
        t = i / frames
        img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        for j, off in enumerate(offsets):
            cx = W / 2 + off * W
            base_hw = W * (0.30 if tongues == 1 else 0.17)
            base_y = H - 2
            for layer in range(4):
                hw = base_hw * (1 - layer * 0.2)
                fh = (
                    H * height_f
                    * (1 - layer * 0.2)
                    * (1 + 0.10 * math.sin(2 * math.pi * (2 * t) + j * 2.1 + layer * 0.7))
                )
                tip_dx = 0.14 * W * math.sin(2 * math.pi * t + j * 2.1 + layer * 0.9)
                left, right = [], []
                for k in range(8):
                    u = k / 7
                    r = hw * (math.sin(math.pi * min(1.0, u * 1.12)) ** 0.8 if u < 1 else 0)
                    x = cx + tip_dx * u * u
                    y = base_y - fh * u
                    left.append((x - r, y))
                    right.append((x + r, y))
                d.polygon(left + right[::-1], fill=FIRE_COLORS[layer + 1])
            # Chispa que sube y parpadea
            sp = (t + j * 0.37) % 1.0
            if sp < 0.75 and (i + j) % 2 == 0:
                sx = cx + round(3 * math.sin(sp * 9 + j))
                sy = base_y - H * height_f * (0.55 + 0.5 * sp)
                if sy > 1:
                    d.point((sx, sy), fill=FIRE_COLORS[4])
        out.append(img)
    return out


# ---------------------------------------------------------------------------
# Onda de tela (wave): banderas, estandartes, cortinas
# ---------------------------------------------------------------------------

def make_cloth(
    width: int = 96, height: int = 64,
    color: str = "#B22222", color2: str | None = None,
) -> Image.Image:
    """Tela rectangular simple (una o dos franjas) con borde oscurecido."""
    c1 = hex_to_rgb(color)
    img = Image.new("RGBA", (width, height), c1 + (255,))
    d = ImageDraw.Draw(img)
    if color2:
        d.rectangle([0, height // 2, width, height], fill=hex_to_rgb(color2) + (255,))
    dark = tuple(int(v * 0.55) for v in c1) + (255,)
    d.rectangle([0, 0, width - 1, height - 1], outline=dark, width=1)
    return img


def wave_frames(
    img: Image.Image,
    frames: int = 8,
    amplitude: int | None = None,
    cycles: float = 1.2,
    anchor: str = "left",
) -> list[Image.Image]:
    """Ondea una tela con onda viajera y sombreado de pliegues (3 niveles).

    anchor "left": amarre al mástil (banderas); "top": cuelga (cortinas).
    """
    rgba = np.asarray(img.convert("RGBA"))
    if anchor == "top":
        rgba = np.transpose(rgba, (1, 0, 2))
    h, w = rgba.shape[:2]
    amplitude = amplitude if amplitude is not None else max(2, round(h * 0.12))

    pad = amplitude + 1
    out = []
    for i in range(frames):
        t = i / frames
        frame = np.zeros((h + pad * 2, w, 4), dtype=np.uint8)
        for x in range(w):
            xn = x / max(1, w - 1)
            weight = xn ** 0.75
            angle = 2 * math.pi * (cycles * xn - t)
            dy = pad + round(amplitude * math.sin(angle) * weight)
            col = rgba[:, x].astype(np.int16)
            slope = math.cos(angle) * weight
            if slope > 0.3:
                col[:, :3] = np.clip(col[:, :3] * 1.18, 0, 255)  # cresta iluminada
            elif slope < -0.3:
                col[:, :3] = np.clip(col[:, :3] * 0.76, 0, 255)  # valle en sombra
            frame[dy : dy + h, x] = col.astype(np.uint8)
        result = frame if anchor != "top" else np.transpose(frame, (1, 0, 2))
        out.append(Image.fromarray(result))
    return out


# ---------------------------------------------------------------------------
# Humo (smoke): columna de nubes que sube y se disipa
# ---------------------------------------------------------------------------

SMOKE_COLORS = [(96, 101, 112), (134, 140, 152), (176, 182, 194)]


def smoke_frames(
    width: int = 48, height: int = 96, frames: int = 8, puffs: int = 8
) -> list[Image.Image]:
    ys, xs = np.mgrid[0:height, 0:width]
    out = []
    for i in range(frames):
        t = i / frames
        density = np.zeros((height, width), dtype=np.float32)
        for k in range(puffs):
            p = (t + k / puffs) % 1.0
            py = (height - 8) - p * (height - 18)
            px = width / 2 + (1.5 + p * 5.5) * math.sin(p * 4.5 + k * 1.9)
            r = 4.5 + p * 9
            dist = np.sqrt((xs - px) ** 2 + (ys - py) ** 2)
            # Kernel de caída lenta para que los puffs se fundan en columna
            density += np.clip(1 - dist / r, 0, None) ** 0.7 * (1 - p) ** 0.8
        frame = np.zeros((height, width, 4), dtype=np.uint8)
        for threshold, color in zip((0.25, 0.55, 0.95), SMOKE_COLORS):
            mask = density > threshold
            frame[mask, :3] = color
            frame[mask, 3] = 255
        out.append(Image.fromarray(frame))
    return out


# ---------------------------------------------------------------------------
# Empaquetado común: frames nativos -> PNGs + sprite sheet + GIF + metadatos
# ---------------------------------------------------------------------------

def list_frames(frames_dir: Path) -> list[Path]:
    """Frames de una animación en ORDEN TEMPORAL.

    No vale `sorted()`: los clips anteriores al ancho dinámico de nombre mezclan
    `frame_99.png` con `frame_100.png`, y alfabéticamente el 100 va justo detrás
    del 10. Se ordena por el número, que es la única verdad."""
    def indice(p: Path) -> int:
        m = re.search(r"(\d+)", p.stem)
        return int(m.group(1)) if m else -1
    return sorted(frames_dir.glob("frame_*.png"), key=indice)


def export_effect(
    frames_native: list[Image.Image],
    *,
    name: str,
    subject: str,
    fps: int,
    scale: int = 6,
    seed: int = 0,
    video_frames: list[Image.Image] | None = None,
    video_fps: int = 16,
    sheet_cols: int | None = None,
    sheet_sample: int | None = None,
    gif_max_side: int = 384,
    anim_format: str = "gif",
    raw_video: bool = False,
    engine: str | None = None,
    parent: str | None = None,
    segments: list[int] | None = None,
    extra: dict | None = None,
) -> Path:
    """Escala los frames (nearest), arma el sheet y el GIF, y registra la
    animación en el historial. Devuelve la ruta del GIF.

    video_frames: clip ORIGINAL completo (p. ej. el video de Wan) que se
    guarda como GIF en output/raw/ para poder verlo desde la GUI.
    sheet_cols: columnas del sprite sheet. Por defecto una sola fila, que es
    lo que espera un motor de juego; los clips largos (video libre, decenas de
    frames) necesitan cuadrícula para no salir un PNG imposible de ancho.
    extra: campos propios del origen que se añaden a la ficha (p. ej. los
    ajustes de un horneado 3D); pisan a los genéricos si coinciden."""
    meta_dir = PROJECT_ROOT / "output" / "meta"
    meta_dir.mkdir(parents=True, exist_ok=True)
    slug = unique_stem(meta_dir, f"{slugify(subject, 28)}_{name}")

    video_name = None
    if video_frames:
        raw_dir = PROJECT_ROOT / "output" / "raw"
        raw_dir.mkdir(parents=True, exist_ok=True)
        # WebP y no GIF: este clip es la REFERENCIA con la que se compara el
        # resultado pixelizado, así que tiene que verse tal como lo generó Wan.
        # En GIF se guardaba a 256 colores tomados del primer frame, que en un
        # clip largo desteñía los tramos finales
        video_name = f"{slug}_video.webp"
        clip = [f.convert("RGB") for f in video_frames]
        clip[0].save(
            raw_dir / video_name,
            save_all=True,
            append_images=clip[1:],
            duration=int(1000 / max(1, video_fps)),
            loop=0,
            format="WEBP",
            quality=80,
            method=4,
        )

    frames_dir = PROJECT_ROOT / "output" / "frames" / slug
    frames_dir.mkdir(parents=True, exist_ok=True)
    # Ancho suficiente para TODOS los frames: con "%02d" fijo, un clip de 201
    # frames mezcla anchos (frame_99 y frame_100) y cualquier orden alfabético
    # los intercala mal. Los ciclos de <=100 frames conservan sus dos dígitos.
    ancho = max(2, len(str(max(0, len(frames_native) - 1))))
    frame_paths = []
    for i, frame in enumerate(frames_native):
        big = frame.resize(
            (frame.width * scale, frame.height * scale), Image.Resampling.NEAREST
        )
        path = frames_dir / f"frame_{i:0{ancho}d}.png"
        big.save(path)
        frame_paths.append(path)

    sheet_path = PROJECT_ROOT / "output" / f"{slug}_sheet.png"
    # Un sprite sheet con TODOS los frames de un clip largo es inservible y
    # enorme (241 frames a 624 px = 87 Mpx): con sheet_sample se reparte una
    # hoja de contactos de como máximo N frames
    sheet_paths = frame_paths
    if sheet_sample and len(frame_paths) > sheet_sample:
        paso = (len(frame_paths) - 1) / (sheet_sample - 1)
        sheet_paths = [frame_paths[round(i * paso)] for i in range(sheet_sample)]
    make_sheet(sheet_paths, cols=sheet_cols or len(sheet_paths)).save(sheet_path)
    gif_path = PROJECT_ROOT / "output" / f"{slug}.{anim_format}"
    save_gif(frame_paths, gif_path, fps=fps, max_side=gif_max_side)

    meta = {
        "kind": "animation",
        "subject": subject,
        "anim": name,
        "seed": seed,
        "frames": len(frame_paths),
        "sprite": gif_path.name,
        "sheet": sheet_path.name,
        "video": video_name,
        # El GIF principal ES el clip del modelo, no un preview de sprites: la
        # GUI etiqueta su pestaña como «Video» y no ofrece la de comparación
        "raw_video": raw_video,
        # Qué motor lo generó, cuando lo hubo: los efectos son matemática
        # pura y no tienen ninguno. Sin esto la GUI no puede decir el
        # modelo de un clip, solo su método.
        "engine": engine,
        # Encadenado: de qué clip se extendió y cuántos frames aportó cada
        # tramo. El padre sigue en el historial con sus propios archivos, así
        # que borrar cualquiera de los dos no rompe al otro
        "parent": parent,
        "segments": segments,
        "fps": fps,
        "native": frames_native[0].height,
        "scale": scale,
        "colors": None,
        "used_palette": False,
        "steps": 0,
        "cfg": 0,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    if extra:
        meta.update(extra)
    (meta_dir / f"{slug}.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Frames: {frames_dir}")
    print(f"Sprite sheet: {sheet_path}")
    print(f"GIF preview : {gif_path}")
    return gif_path

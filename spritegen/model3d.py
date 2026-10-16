"""Imagen → modelo 3D (GLB) con TRELLIS.2 nativo en ComfyUI.

Toma la imagen ORIGINAL de un sprite (el raw de la IA, no el PNG
pixelizado: con el tramado del pixel art la textura sale manchada y
saturada) y la convierte en una malla texturizada con color, relieve y
oclusión. El resultado se registra en el historial como pieza `model3d`:

- `output/models/<stem>.glb`: el modelo, sin los metadatos de ComfyUI.
- `output/<stem>.png`: miniatura isométrica RGBA para el archivo.
- `output/raw/<stem>.png`: copia propia de la imagen de partida, para que
  borrar el sprite base nunca deje al modelo sin su origen.

El modelo sale normalizado al cubo [-0,5, 0,5] y, con TRELLIS.2, recto y
alineado con los ejes (qué cara queda de frente varía entre generaciones):
girarlo 45° y elevar la vista 30° da una vista isométrica. Desde una sola
imagen, las caras ocultas se inventan.

`bake_sprites` hace el camino de vuelta: recibe los renders de cada
dirección que pinta el visor 3D del navegador (Three.js) y los convierte en
sprites pixel art con recorte y paleta comunes.
"""
from __future__ import annotations

import io
import json
import random
import shutil
import struct
import time
from pathlib import Path

import numpy as np
from PIL import Image

from spritegen import engines as eng
from spritegen.animate import upload_image
from spritegen.effects import export_effect
from spritegen.generate import (
    DEFAULT_SERVER,
    PROJECT_ROOT,
    ensure_server,
    run_workflow_files,
    slugify,
    switch_family,
    unique_stem,
)
from spritegen.pixelize import pixelize

OUTPUT_DIR = PROJECT_ROOT / "output"
META_DIR = OUTPUT_DIR / "meta"
MODELS_DIR = OUTPUT_DIR / "models"

# Remallados de reserva si el del motor agota la VRAM (ver image_to_model)
REMESH_FALLBACK = (384, 256)

_GLB_MAGIC = 0x46546C67   # "glTF"
_CHUNK_JSON = 0x4E4F534A  # "JSON"


def _subject_in_alpha(img: Image.Image) -> bool:
    """¿La imagen ya trae el sujeto recortado en su canal alfa? Entonces se
    usa ese recorte; si no (un raw de IA con fondo blanco, una foto), BiRefNet
    separa el sujeto dentro del grafo."""
    if img.mode not in ("RGBA", "LA", "PA") and "transparency" not in img.info:
        return False
    alpha = img.convert("RGBA").getchannel("A")
    transparentes = sum(alpha.histogram()[:16])
    return transparentes > 0.01 * alpha.width * alpha.height


def _read_glb(glb: bytes) -> tuple[dict, bytes]:
    """Separa el GLB en su JSON y el resto (chunk BIN incluido, intacto)."""
    magic, version, _ = struct.unpack_from("<III", glb, 0)
    if magic != _GLB_MAGIC or version != 2:
        raise ValueError("El archivo devuelto por ComfyUI no es un GLB 2.0")
    length, kind = struct.unpack_from("<II", glb, 12)
    if kind != _CHUNK_JSON:
        raise ValueError("GLB sin chunk JSON al principio")
    return json.loads(glb[20:20 + length]), glb[20 + length:]


def strip_glb_extras(glb: bytes) -> bytes:
    """Quita `asset.extras` del GLB: SaveGLB mete ahí el workflow completo de
    ComfyUI, que no pinta nada dentro de un asset que se va a publicar."""
    doc, rest = _read_glb(glb)
    if not doc.get("asset", {}).pop("extras", None):
        return glb
    data = json.dumps(doc, separators=(",", ":")).encode("utf-8")
    data += b" " * (-len(data) % 4)  # el chunk JSON se rellena con espacios a 4 bytes
    total = 12 + 8 + len(data) + len(rest)
    return (struct.pack("<III", _GLB_MAGIC, 2, total)
            + struct.pack("<II", len(data), _CHUNK_JSON) + data + rest)


def glb_stats(glb: bytes) -> dict:
    """Triángulos, vértices y tamaño de cada textura del GLB."""
    doc, rest = _read_glb(glb)
    accessors = doc.get("accessors", [])
    triangles = vertices = 0
    for mesh in doc.get("meshes", []):
        for prim in mesh.get("primitives", []):
            if "indices" in prim:
                triangles += accessors[prim["indices"]]["count"] // 3
            vertices += accessors[prim["attributes"]["POSITION"]]["count"]
    # El chunk BIN empieza tras su cabecera de 8 bytes
    binary = rest[8:]
    textures = []
    views = doc.get("bufferViews", [])
    for image in doc.get("images", []):
        if "bufferView" not in image:
            continue
        view = views[image["bufferView"]]
        start = view.get("byteOffset", 0)
        try:
            with Image.open(io.BytesIO(binary[start:start + view["byteLength"]])) as im:
                textures.append(max(im.size))
        except OSError:
            continue
    return {"triangles": triangles, "vertices": vertices, "textures": textures}


def image_to_model(
    base_raw: Path,
    *,
    subject: str,
    engine_id: str = "trellis2",
    quality: str | None = None,
    seed: int | None = None,
    source_id: str | None = None,
    server: str = DEFAULT_SERVER,
) -> str:
    """Genera el modelo 3D de `base_raw` y lo registra. Devuelve el stem.

    quality: una de las calidades que declara el motor en motores.json
    («juego», «detalle»): cuántas caras y qué tamaño de textura."""
    engine = eng.get_engine(engine_id)
    if engine.get("kind") != "model3d":
        raise ValueError(f"El motor '{engine['label']}' no genera modelos 3D")
    eng.require_installed(engine)
    p = engine["params"]
    qualities = p.get("qualities", {})
    quality = quality or p.get("quality") or next(iter(qualities), None)
    if quality not in qualities:
        raise ValueError(f"Calidad desconocida '{quality}'. Disponibles: {', '.join(qualities)}")
    preset = qualities[quality]
    seed = seed if seed is not None else random.randrange(2**31)

    with Image.open(base_raw) as img:
        img.load()
        from_alpha = _subject_in_alpha(img)

    ensure_server(server)
    # Si lo último fue vídeo, sus expertos (~21 GB) se descargan antes
    switch_family(server, "model3d")
    image_name = upload_image(server, base_raw)
    print(f"Generando el modelo 3D de '{subject}' con {engine['label']} (seed {seed}, "
          f"calidad {quality}: {preset['faces']} caras, textura {preset['texture']}) "
          "— tarda unos minutos...")
    # El postproceso de malla (sobre todo RemeshMesh) usa memoria de la GPU
    # que ComfyUI no gestiona: con los modelos aún cargados, una malla grande
    # puede agotar la VRAM. Tras un OOM ComfyUI descarga todos los modelos y
    # se reintenta remallando más bajo; los muestreos se repiten, porque la
    # caché del grafo no sobrevive al error
    base_remesh = int(p.get("remesh", 512))
    attempts = [base_remesh] + [r for r in REMESH_FALLBACK if r < base_remesh]
    t0 = time.time()
    for i, remesh in enumerate(attempts):
        graph = eng.build_model3d_graph(
            engine, image_name, seed,
            faces=int(preset["faces"]), texture=int(preset["texture"]),
            mask_from_alpha=from_alpha, remesh=remesh,
        )
        try:
            outputs = run_workflow_files(server, graph, timeout=int(p.get("timeout", 1800)))
            break
        except RuntimeError as exc:
            if "out of memory" not in str(exc).lower() or i == len(attempts) - 1:
                raise
            print(f"Sin VRAM en el postproceso con remallado a {remesh}: se repite "
                  f"remallando a {attempts[i + 1]}...")
    seconds = round(time.time() - t0)

    glb = next((data for name, data in outputs.get("save", [])
                if name.lower().endswith(".glb")), None)
    if glb is None:
        raise RuntimeError("ComfyUI terminó sin devolver el modelo GLB")
    glb = strip_glb_extras(glb)
    stats = glb_stats(glb)

    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "raw").mkdir(parents=True, exist_ok=True)
    META_DIR.mkdir(parents=True, exist_ok=True)
    stem = unique_stem(META_DIR, f"{slugify(subject, 34)}_3d_{seed}")
    (MODELS_DIR / f"{stem}.glb").write_bytes(glb)
    shutil.copyfile(base_raw, OUTPUT_DIR / "raw" / f"{stem}.png")
    thumb = outputs.get("thumb", [])
    if thumb:
        (OUTPUT_DIR / f"{stem}.png").write_bytes(thumb[0][1])
    else:
        # Sin miniatura el archivo no podría mostrar la pieza: vale la imagen de partida
        shutil.copyfile(base_raw, OUTPUT_DIR / f"{stem}.png")

    meta = {
        "kind": "model3d",
        "subject": subject,
        "engine": engine["id"],
        "seed": seed,
        "raw": f"{stem}.png",
        "sprite": f"{stem}.png",
        "model": f"{stem}.glb",
        # De qué pieza del archivo salió, si salió de una
        "source": source_id,
        "quality": quality,
        "faces": stats["triangles"],
        "vertices": stats["vertices"],
        "texture": max(stats["textures"], default=int(preset["texture"])),
        "textures": len(stats["textures"]),
        "glb_mb": round(len(glb) / 2**20, 2),
        "cascade": int(p.get("cascade", 1024)),
        # El remallado que de verdad se usó (puede ser uno de reserva)
        "remesh": remesh,
        "mask": "alpha" if from_alpha else "birefnet",
        "seconds": seconds,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    (META_DIR / f"{stem}.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Modelo 3D listo en {seconds} s: output/models/{stem}.glb "
          f"({stats['triangles']} triángulos, {meta['glb_mb']} MB)")
    return stem


# ---------------------------------------------------------------------------
# Horneado: renders del visor 3D -> sprites pixel art
# ---------------------------------------------------------------------------

def _native_size(size: tuple[int, int], native: int) -> tuple[int, int]:
    """Mismo reparto que pixelize(): el lado mayor mide `native`."""
    w, h = size
    if w >= h:
        return native, max(1, round(h * native / w))
    return max(1, round(w * native / h)), native


def _shared_palette(crops: list[Image.Image], native: int, colors: int) -> list[tuple[int, int, int]]:
    """UNA paleta para todas las direcciones. Se cuantizan juntas (en una tira)
    con el mismo método que pixelize: si cada dirección eligiera la suya, el
    mismo tejado cambiaría de tono al girar."""
    smalls = [c.resize(_native_size(c.size, native), Image.Resampling.BOX) for c in crops]
    strip = Image.new("RGBA", (sum(s.width for s in smalls), max(s.height for s in smalls)),
                      (0, 0, 0, 0))
    x = 0
    for s in smalls:
        strip.paste(s, (x, 0))
        x += s.width
    # native = lado mayor de la tira: pixelize no la reescala, solo la cuantiza
    quantized = pixelize(strip, native=max(strip.size), scale=1, colors=colors,
                         method="nearest").native
    arr = np.asarray(quantized)
    opaque = arr[..., 3] == 255
    if not opaque.any():
        raise ValueError("El render salió vacío: el modelo no se ve en ninguna dirección")
    return [tuple(int(v) for v in c) for c in np.unique(arr[opaque][:, :3], axis=0)]


def bake_sprites(
    model_meta: dict,
    frames: list[Image.Image],
    *,
    ss: int,
    colors: int,
    palette: list[tuple[int, int, int]] | None,
    scale: int,
    settings: dict,
) -> str:
    """Convierte los renders de un modelo 3D (uno por dirección, mismo tamaño y
    mismo encuadre, pintados a `ss`× la rejilla) en sprites pixel art.

    Con una dirección sale una pieza `sprite` (con el render como «original»,
    así que se puede animar por vídeo o variar como cualquier sprite); con
    varias, una `animation`: GIF de giro, sprite sheet de las direcciones y
    sus frames. Todas comparten recorte y paleta: el origen del modelo cae en
    el mismo píxel de cada sprite y los colores no cambian al girar.

    `settings`: vista, orientación, luz, escala... del horneado, que se
    guardan en la ficha para poder repetirlo."""
    if not frames:
        raise ValueError("No llegó ningún render")
    rgba = [f.convert("RGBA") for f in frames]
    if any(f.size != rgba[0].size for f in rgba):
        raise ValueError("Los renders de las direcciones no miden lo mismo")

    # Recorte COMÚN: la unión de lo visible en todas las direcciones, más un
    # píxel nativo de aire
    box = None
    for f in rgba:
        b = f.getchannel("A").point(lambda a: 255 if a >= 8 else 0).getbbox()
        if b:
            box = b if box is None else (min(box[0], b[0]), min(box[1], b[1]),
                                         max(box[2], b[2]), max(box[3], b[3]))
    if box is None:
        raise ValueError("El render salió vacío: el modelo no se ve en ninguna dirección")
    w, h = rgba[0].size
    box = (max(0, box[0] - ss), max(0, box[1] - ss), min(w, box[2] + ss), min(h, box[3] + ss))
    crops = [f.crop(box) for f in rgba]
    native = max(1, round(max(crops[0].size) / max(1, ss)))
    shared = palette or _shared_palette(crops, native, colors)
    n = len(crops)

    seed = int(model_meta.get("seed") or 0)
    base_subject = model_meta.get("subject") or "modelo 3D"
    extra = {
        **settings,
        "baked_from": model_meta.get("id"),
        "directions": n,
        "colors": len(shared),
        "used_palette": palette is not None,
        "method": "box",
    }
    if n == 1:
        result = pixelize(crops[0], native=native, scale=scale, palette=shared,
                          method="box", clean=True)
        (OUTPUT_DIR / "raw").mkdir(parents=True, exist_ok=True)
        META_DIR.mkdir(parents=True, exist_ok=True)
        subject = f"{base_subject} · render 3D"
        stem = unique_stem(META_DIR, f"{slugify(base_subject, 34)}_render_{seed}")
        crops[0].save(OUTPUT_DIR / "raw" / f"{stem}.png")
        result.final.save(OUTPUT_DIR / f"{stem}.png")
        meta = {
            "subject": subject,
            "engine": None,
            "seed": seed,
            "raw": f"{stem}.png",
            "sprite": f"{stem}.png",
            "native": native,
            "scale": scale,
            "raw_prompt": False,
            "steps": 0,
            "cfg": 0,
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            **extra,
        }
        (META_DIR / f"{stem}.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"Sprite horneado: output/{stem}.png ({result.native.size[0]}x{result.native.size[1]} px)")
        return stem

    natives = [pixelize(c, native=native, scale=1, palette=shared, method="box",
                        clean=True).native for c in crops]
    gif = export_effect(
        natives,
        name=f"dirs{n}",
        subject=f"{base_subject} · {n} direcciones",
        # El GIF es un giro completo: ~2 s por vuelta sea cual sea el número
        fps=max(2, n // 2),
        scale=scale,
        seed=seed,
        extra=extra,
    )
    return gif.stem

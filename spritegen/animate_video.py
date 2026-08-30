"""Animación por video: sprite + descripción de movimiento -> Wan 2.2 I2V.

A diferencia del modo esqueleto (ControlNet, frame a frame), aquí un modelo
imagen→video genera un clip corto del sprite moviéndose: la identidad entre
frames es coherente por naturaleza. Del video se muestrean N frames que pasan
por el pipeline estándar (fondo, sombra, pixelizado con paleta compartida).

Los motores con `raw_output` (video libre) se saltan ese pipeline: el clip se
guarda tal cual sale del modelo, para animar cualquier imagen sin convertirla
en pixel art.
"""

from __future__ import annotations

import io
import math
import random
import tempfile
from pathlib import Path

from PIL import Image

from spritegen import engines as eng
from spritegen.animate import upload_image
from spritegen.background import (
    remove_debris,
    remove_flat_background,
    remove_soft_shadow,
    strip_shadow_result,
)
from spritegen.effects import export_effect
from spritegen.generate import (
    DEFAULT_SERVER,
    ensure_server,
    load_config,
    run_workflow_all,
    slugify,
)
from spritegen.palette import extract_palette
from spritegen.pixelize import pixelize

VIDEO_PROMPT = (
    "pixel art game sprite animation of {subject}, {motion}, "
    "the character stays centered in frame, plain white background, "
    "flat shading, limited color palette"
)
VIDEO_NEGATIVE_EXTRA = (
    ", camera movement, camera zoom, panning, background change, "
    "realistic, 3d render, blur"
)
# En modo libre el negativo de estilo.json no sirve: prohíbe justo lo que aquí
# se busca (degradados suaves, fotorrealismo). Este es el negativo genérico de
# video: solo defectos, nada de estilo.
FREE_NEGATIVE = (
    "low quality, worst quality, blurry, jpeg artifacts, watermark, text, "
    "static image, no motion, distorted, deformed hands, extra limbs, "
    "flickering, duplicated frames"
)
# Duración típica de un ciclo de locomoción. Se muestrea SOLO esa ventana del
# clip: repartir los frames por los 5 s completos mete varias zancadas en el
# sheet y el ciclo tartamudea al reproducirse en bucle.
CYCLE_SECONDS = 0.8
# El modelo tarda unos frames en arrancar el movimiento desde la imagen fija
WARMUP_SECONDS = 0.25


def _fit_video_size(size: tuple[int, int], target_w: int, target_h: int) -> tuple[int, int]:
    """Tamaño de video que conserva el aspecto de la imagen de arranque con el
    mismo coste de cómputo que el declarado por el motor. Múltiplos de 16, que
    es el paso que exige Wan. Sin esto, una imagen cuadrada estirada a 832x480
    sale deformada."""
    w, h = size
    if w <= 0 or h <= 0:
        return target_w, target_h
    scale = math.sqrt((target_w * target_h) / (w * h))
    fit_w = max(16, int(round(w * scale / 16)) * 16)
    fit_h = max(16, int(round(h * scale / 16)) * 16)
    return fit_w, fit_h


def _normalize_length(length: int | None, default: int) -> int:
    """Los VAE de video comprimen 4 frames en 1, así que el nodo exige 4n+1.
    Un valor cualquiera (de la API o del CLI) se redondea al 4n+1 más cercano
    en vez de reventar en ComfyUI."""
    if not length or length < 5:
        return default
    return max(5, round((length - 1) / 4) * 4 + 1)


def _cycle_indices(total: int, frames_out: int, fps: int, cycle_seconds: float) -> list[int]:
    """Índices de una sola zancada. Con cycle_seconds <= 0 recorre el clip
    entero (útil para movimientos no cíclicos: un ataque, una muerte)."""
    if total <= 1:
        return [0]
    if cycle_seconds <= 0:
        return sorted({round(i * (total - 1) / max(1, frames_out - 1))
                       for i in range(frames_out)})
    window = max(frames_out, round(cycle_seconds * fps))
    # Paso ENTERO: con paso fraccionario el redondeo deja huecos desiguales
    # (4,6,7,9,10...) y la cadencia del ciclo cojea al reproducirse
    step = max(1, round(window / frames_out))
    start = min(total - 1, round(WARMUP_SECONDS * fps))
    # Si la ventana se sale del clip, se retrasa el arranque antes de acortar
    start = max(0, min(start, total - 1 - step * (frames_out - 1)))
    idx = [start + i * step for i in range(frames_out)]
    return [i for i in idx if i <= total - 1]


def animate_video_sprite(
    motion: str,
    base_raw: Path,
    base_subject: str,
    frames_out: int = 8,
    seed: int | None = None,
    native: int = 128,
    scale: int = 6,
    colors: int | None = 32,
    palette: list[tuple[int, int, int]] | None = None,
    length: int | None = None,
    engine_id: str = "wan22_14b_pixel",
    cycle_seconds: float | None = None,
    prev_frames: list[Path] | None = None,
    prev_segments: list[int] | None = None,
    parent_id: str | None = None,
    server: str = DEFAULT_SERVER,
) -> Path:
    """Genera el ciclo por video y lo registra en el historial. Devuelve el GIF.

    Con `prev_frames` funciona en modo EXTENSIÓN: `base_raw` es el último frame
    del clip anterior y el resultado es la unión de los dos tramos. El clip
    padre no se toca: queda en el historial con sus propios archivos."""
    engine = eng.get_engine(engine_id)
    if engine.get("kind") != "video":
        raise ValueError(f"El motor '{engine['label']}' no genera video")
    eng.require_installed(engine)
    style = load_config()
    seed = seed if seed is not None else random.randrange(2**31)
    p = engine["params"]
    raw_output = bool(p.get("raw_output"))
    if prev_frames and not raw_output:
        raise ValueError(
            f"El motor '{engine['label']}' pixeliza su salida y no puede encadenar "
            "clips: elige un motor de video libre para continuar un clip"
        )
    fps = int(p.get("fps", 16))
    length = _normalize_length(length, int(p["length"]))
    if cycle_seconds is None:
        cycle_seconds = 0.0 if raw_output else CYCLE_SECONDS

    ensure_server(server)
    # Imagen de arranque: el raw compuesto sobre blanco, al tamaño del video
    start = Image.open(base_raw).convert("RGBA")
    canvas = Image.new("RGB", start.size, (255, 255, 255))
    canvas.paste(start, mask=start.getchannel("A"))
    if prev_frames:
        # Al continuar un clip manda SU tamaño, no el del motor: si el motor
        # pide más resolución, el tramo nuevo se generaría grande para acabar
        # reducido al unirlo — pagando el coste y tirando la ganancia
        with Image.open(prev_frames[0]) as previo:
            width, height = _fit_video_size(previo.size, *previo.size)
    else:
        width, height = _fit_video_size(canvas.size, p["width"], p["height"])
    canvas = canvas.resize((width, height), Image.Resampling.LANCZOS)
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        canvas.save(tmp, format="PNG")
        tmp_path = Path(tmp.name)
    try:
        start_name = upload_image(server, tmp_path)
    finally:
        tmp_path.unlink(missing_ok=True)

    if p.get("raw_prompt"):
        # Video libre: el texto del usuario va tal cual, sin plantilla de estilo
        prompt = motion
        negative = FREE_NEGATIVE
    else:
        # replace, no format: un prompt del usuario con llaves reventaría .format
        prompt = (VIDEO_PROMPT.replace("{subject}", base_subject)
                              .replace("{motion}", motion))
        negative = style["negative_prompt"] + VIDEO_NEGATIVE_EXTRA
    print(f"Generando video '{motion}' con {engine['label']} (seed {seed}, "
          f"{width}x{height}, {length} frames = {length / fps:.1f} s a {fps} fps) "
          "— puede tardar varios minutos...")
    frames_png = run_workflow_all(
        server,
        eng.build_video_graph(engine, prompt, negative, start_name, seed,
                              length=length, width=width, height=height),
        timeout=int(p.get("timeout", 3600)),
    )
    total = len(frames_png)

    if raw_output:
        # Video libre: el clip completo es el resultado, sin post-proceso
        print(f"Video listo: {total} frames a {width}x{height}.")
        clip = [Image.open(io.BytesIO(b)).convert("RGB") for b in frames_png]
        nombre = f"libre_{slugify(motion, 16)}_{seed}"
        etiqueta = f"{base_subject} · {motion} (video libre)"
        segments = None
        if prev_frames:
            # El frame 0 reproduce la imagen de arranque, que ES el último frame
            # del tramo anterior: si no se descarta, la costura repite un frame
            # y el clip da un tirón ahí
            nuevos = clip[1:]
            previos = [Image.open(p).convert("RGB") for p in prev_frames]
            if nuevos and nuevos[0].size != previos[0].size:
                # Cambiar de motor entre tramos cambiaría el tamaño; el sheet y
                # el GIF exigen que todos los frames midan lo mismo
                nuevos = [f.resize(previos[0].size, Image.Resampling.LANCZOS)
                          for f in nuevos]
            clip = previos + nuevos
            segments = list(prev_segments or [len(previos)]) + [len(nuevos)]
            nombre = f"libre_x{len(segments)}_{seed}"
            etiqueta = f"{base_subject} + {motion}"[:90]
            print(f"Encadenado: {len(segments)} tramos, {len(clip)} frames "
                  f"= {len(clip) / fps:.1f} s en total.")
        total = len(clip)
        return export_effect(
            clip,
            name=nombre,
            subject=etiqueta,
            fps=fps,
            scale=1,
            seed=seed,
            parent=parent_id,
            segments=segments,
            # Sin video_frames: aquí el GIF principal ya ES el clip completo,
            # guardarlo dos veces solo duplica decenas de MB
            video_fps=fps,
            # Hoja de contactos de 24 frames como máximo, en cuadrícula: aquí el
            # sheet solo sirve para ver la evolución del clip de un vistazo
            sheet_sample=24,
            sheet_cols=max(1, int(math.ceil(math.sqrt(min(total, 24))))),
            # Aquí el GIF ES el entregable, no una miniatura de sprite: se deja
            # al tamaño nativo de los frames unidos (agrandarlo solo duplicaría
            # píxeles), que puede no ser el del tramo recién generado
            gif_max_side=max(clip[0].size),
            # WebP en vez de GIF: color completo de 24 bits y ~8x menos peso
            # (91 MB -> 11 MB en un clip de 3 tramos) con el mismo Pillow. El
            # pixel art se queda en GIF, que ahí es lo estándar y basta
            anim_format="webp",
            raw_video=True,
        )

    indices = _cycle_indices(total, frames_out, fps, cycle_seconds)
    print(f"Video listo: {total} frames crudos; se toman {len(indices)} "
          f"de una zancada ({indices[0]}–{indices[-1]}).")

    shared_palette = palette
    natives = []
    for idx in indices:
        img = Image.open(io.BytesIO(frames_png[idx]))
        img = remove_flat_background(img, threshold=style.get("bg_removal_threshold", 60))
        # Wan mancha el fondo con motas cálidas que quedarían flotando
        img = remove_debris(img)
        if style.get("remove_shadow", True):
            img = remove_soft_shadow(img)
        result = pixelize(
            img, native=native, scale=1, colors=colors,
            palette=shared_palette, method=p.get("pixelize_method", "nearest"),
            clean=True,
        )
        if style.get("remove_shadow", True):
            # Misma etapa que generate/animate: sin ella los frames de video
            # conservaban la sombra de contacto bajo el sujeto
            result = strip_shadow_result(result, 1)
        # Segunda pasada anti-motas EN NATIVO: los rastros tenues que unían
        # una mota al sujeto desaparecen al cuantizar, y ahí ya es una isla
        native_img = remove_debris(result.native, min_frac=0.005)
        if shared_palette is None:
            shared_palette = extract_palette(native_img, n=colors or 32)
        natives.append(native_img)

    # El clip completo de Wan se guarda como GIF para poder verlo en la GUI
    video_imgs = [Image.open(io.BytesIO(b)).convert("RGB") for b in frames_png]
    return export_effect(
        natives,
        name=f"video_{slugify(motion, 16)}_{seed}",
        subject=f"{base_subject} · {motion} (video)",
        fps=10,
        scale=scale,
        seed=seed,
        video_frames=video_imgs,
        video_fps=fps,
    )

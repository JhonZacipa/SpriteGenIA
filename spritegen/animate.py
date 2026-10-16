from __future__ import annotations

import json
import random
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import requests
from PIL import Image

from spritegen.background import (
    remove_flat_background,
    remove_soft_shadow,
    strip_shadow_result,
)
from spritegen.generate import (
    DEFAULT_SERVER,
    PROJECT_ROOT,
    ensure_server,
    load_config,
    run_workflow,
    slugify,
    unique_stem,
)
from spritegen.palette import extract_palette
from spritegen.pixelize import pixelize
from spritegen.poses import ANIMATIONS, ensure_poses
from spritegen.sheet import make_sheet

CONTROLNET_FILE = "xinsir-openpose-sdxl.safetensors"


@dataclass
class AnimationResult:
    subject: str
    anim: str
    seed: int
    frames: list[Path]
    sheet: Path
    gif: Path


def upload_image(server: str, path: str | Path) -> str:
    """Sube una imagen al directorio input de ComfyUI y devuelve su nombre."""
    path = Path(path)
    try:
        with open(path, "rb") as f:
            resp = requests.post(
                f"{server}/upload/image",
                files={"image": (path.name, f, "image/png")},
                data={"overwrite": "true"},
                timeout=60,
            )
    except requests.RequestException as exc:
        raise RuntimeError(f"No se pudo subir {path.name} a ComfyUI: {exc}") from exc
    if not resp.ok:
        raise RuntimeError(f"ComfyUI rechazó la subida de {path.name}: {resp.text[:400]}")
    return resp.json()["name"]


def build_anim_workflow(
    cfg: dict[str, Any],
    subject: str,
    seed: int,
    pose_name: str,
    base_name: str | None = None,
    denoise: float = 0.85,
    cn_strength: float = 1.0,
) -> dict[str, Any]:
    """Workflow SDXL + LoRA + ControlNet OpenPose (formato API de ComfyUI)."""
    # replace en lugar de format: la plantilla puede traer otras llaves {}
    prompt = cfg["prompt_template"].replace("{subject}", subject)
    wf: dict[str, Any] = {
        "ckpt": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": cfg["checkpoint"]},
        },
        "lora": {
            "class_type": "LoraLoader",
            "inputs": {
                "model": ["ckpt", 0],
                "clip": ["ckpt", 1],
                "lora_name": cfg["lora"],
                "strength_model": cfg["lora_strength"],
                "strength_clip": cfg["lora_strength"],
            },
        },
        "pos": {
            "class_type": "CLIPTextEncode",
            "inputs": {"clip": ["lora", 1], "text": prompt},
        },
        "neg": {
            "class_type": "CLIPTextEncode",
            "inputs": {"clip": ["lora", 1], "text": cfg["negative_prompt"]},
        },
        "cn": {
            "class_type": "ControlNetLoader",
            "inputs": {"control_net_name": CONTROLNET_FILE},
        },
        "pose": {"class_type": "LoadImage", "inputs": {"image": pose_name}},
        "cn_apply": {
            "class_type": "ControlNetApplyAdvanced",
            "inputs": {
                "positive": ["pos", 0],
                "negative": ["neg", 0],
                "control_net": ["cn", 0],
                "image": ["pose", 0],
                "strength": cn_strength,
                "start_percent": 0.0,
                "end_percent": 0.85,
            },
        },
        "sampler": {
            "class_type": "KSampler",
            "inputs": {
                "model": ["lora", 0],
                "positive": ["cn_apply", 0],
                "negative": ["cn_apply", 1],
                "seed": seed,
                "steps": cfg["steps"],
                "cfg": cfg["cfg"],
                "sampler_name": cfg["sampler"],
                "scheduler": cfg["scheduler"],
                "denoise": 1.0,
            },
        },
        "decode": {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["sampler", 0], "vae": ["ckpt", 2]},
        },
        "save": {
            "class_type": "SaveImage",
            "inputs": {"images": ["decode", 0], "filename_prefix": "spritegen_anim"},
        },
    }
    if base_name:
        # img2img: el sprite base ancla identidad y colores; la pose la manda
        # el ControlNet y el denoise decide cuánta libertad hay para moverse
        wf["base"] = {"class_type": "LoadImage", "inputs": {"image": base_name}}
        wf["enc"] = {
            "class_type": "VAEEncode",
            "inputs": {"pixels": ["base", 0], "vae": ["ckpt", 2]},
        }
        wf["sampler"]["inputs"]["latent_image"] = ["enc", 0]
        wf["sampler"]["inputs"]["denoise"] = denoise
    else:
        wf["latent"] = {
            "class_type": "EmptyLatentImage",
            "inputs": {"width": cfg["width"], "height": cfg["height"], "batch_size": 1},
        }
        wf["sampler"]["inputs"]["latent_image"] = ["latent", 0]
    return wf


def animate_sprite(
    subject: str,
    anim: str = "walk",
    seed: int | None = None,
    base: str | Path | None = None,
    denoise: float = 0.85,
    native: int = 128,
    scale: int = 6,
    colors: int | None = 32,
    palette: list[tuple[int, int, int]] | None = None,
    cn_strength: float = 1.0,
    steps: int | None = None,
    cfg_scale: float | None = None,
    server: str = DEFAULT_SERVER,
    on_progress: Callable[[int, int], None] | None = None,
) -> AnimationResult:
    """Genera todos los frames de un ciclo, el sprite sheet y un GIF de preview.

    Consistencia entre frames: misma semilla, mismo prompt y, si no hay paleta
    global, la paleta del primer frame se fija para los demás.
    """
    from spritegen import engines as eng

    eng.require_installed(eng.get_engine("sdxl_pixelart"))  # el esqueleto usa SDXL
    cfg = load_config()
    if steps:
        cfg["steps"] = steps
    if cfg_scale:
        cfg["cfg"] = cfg_scale
    pose_paths = ensure_poses(anim)  # valida integradas y ciclos personalizados
    spec = ANIMATIONS.get(anim, {})
    fps = spec.get("fps", 8)
    # Los ciclos de frente/espalda añaden su pista de vista al prompt
    hint = spec.get("hint")
    prompt_subject = f"{subject}, {hint}" if hint else subject
    total = len(pose_paths)
    seed = seed if seed is not None else random.randrange(2**31)

    ensure_server(server)
    base_name = upload_image(server, base) if base else None

    meta_dir = PROJECT_ROOT / "output" / "meta"
    meta_dir.mkdir(parents=True, exist_ok=True)
    slug = unique_stem(meta_dir, f"{slugify(subject, 32)}_{anim}_{seed}")
    frames_dir = PROJECT_ROOT / "output" / "frames" / slug
    frames_dir.mkdir(parents=True, exist_ok=True)
    sheet_path = PROJECT_ROOT / "output" / f"{slug}_sheet.png"
    gif_path = PROJECT_ROOT / "output" / f"{slug}.gif"

    shared_palette = palette
    frame_paths: list[Path] = []
    try:
        for i, pose_path in enumerate(pose_paths):
            if on_progress:
                on_progress(i, total)
            print(f"Frame {i + 1}/{total} ({anim})...")
            pose_name = upload_image(server, pose_path)
            wf = build_anim_workflow(
                cfg, prompt_subject, seed, pose_name, base_name, denoise, cn_strength
            )
            png = run_workflow(server, wf)
            raw_path = frames_dir / f"raw_{i:02d}.png"
            raw_path.write_bytes(png)

            img = remove_flat_background(
                Image.open(raw_path), threshold=cfg.get("bg_removal_threshold", 60)
            )
            if cfg.get("remove_shadow", True):
                img = remove_soft_shadow(img)
            result = pixelize(
                img,
                native=native,
                scale=scale,
                colors=colors,
                palette=shared_palette,
                method="nearest",
                clean=True,
            )
            if cfg.get("remove_shadow", True):
                result = strip_shadow_result(result, scale)
            if shared_palette is None:
                # La paleta del primer frame amarra los colores de todo el ciclo
                shared_palette = extract_palette(result.native, n=colors or 32)
            frame_path = frames_dir / f"frame_{i:02d}.png"
            result.final.save(frame_path)
            frame_paths.append(frame_path)
        if on_progress:
            on_progress(total, total)

        sheet = make_sheet(frame_paths, cols=total)
        sheet.save(sheet_path)
        save_gif(frame_paths, gif_path, fps=fps)
    except BaseException:
        # Sin meta json las salidas parciales serían invisibles para el
        # historial (imposibles de borrar desde la GUI): se limpian aquí
        shutil.rmtree(frames_dir, ignore_errors=True)
        sheet_path.unlink(missing_ok=True)
        gif_path.unlink(missing_ok=True)
        raise

    meta = {
        "kind": "animation",
        "subject": subject,
        "anim": anim,
        # El flujo de esqueleto es siempre-SDXL (ControlNet OpenPose):
        # no es un motor elegible, pero sí un dato cierto del resultado
        "engine": "sdxl_pixelart",
        "seed": seed,
        "frames": total,
        "sprite": gif_path.name,
        "sheet": sheet_path.name,
        "native": native,
        "scale": scale,
        "colors": colors,
        "used_palette": palette is not None,
        "denoise": denoise if base_name else None,
        "steps": cfg["steps"],
        "cfg": cfg["cfg"],
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    (meta_dir / f"{slug}.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Sprite sheet: {sheet_path}")
    print(f"GIF preview : {gif_path}")
    return AnimationResult(
        subject=subject, anim=anim, seed=seed,
        frames=frame_paths, sheet=sheet_path, gif=gif_path,
    )


def save_gif(frame_paths: list[Path], out: Path, fps: int, max_side: int = 384) -> None:
    """Animación de preview sobre fondo gris neutro (el GIF no soporta alfa
    parcial). El formato lo decide la EXTENSIÓN de `out`:

    - .gif : 256 colores por frame. Correcto para pixel art, y es lo que
      esperan las herramientas externas para un sprite.
    - .webp: color completo de 24 bits y ~8x menos peso, con el mismo Pillow y
      sin dependencias. El navegador lo reproduce en un <img> igual que un GIF,
      así que el visor no nota la diferencia. Para clips de video largos.

    El lado mayor se lleva a `max_side` CONSERVANDO la proporción: los sprites
    son cuadrados y quedan igual que siempre, pero un clip de video libre en
    16:9 no se aplasta."""
    frames = []
    for p in frame_paths:
        im = Image.open(p).convert("RGBA")
        bg = Image.new("RGB", im.size, (59, 64, 72))
        bg.paste(im, mask=im.getchannel("A"))
        escala = max_side / max(bg.size)
        destino = (max(1, round(bg.width * escala)), max(1, round(bg.height * escala)))
        # NEAREST preserva el pixel art; en fotográfico da un aliasing aceptable
        # para un preview y evita mezclar colores fuera de la paleta
        bg = bg.resize(destino, Image.Resampling.NEAREST)
        frames.append(bg)
    extra = {}
    if out.suffix.lower() == ".webp":
        # quality 88: medido sobre un clip real de 489 frames -> q80 17 MB,
        # q88 ~25 MB, q92 37 MB. El salto de 80 a 92 duplica el peso para una
        # mejora sutil; 88 recoge casi toda la ganancia en degradados
        extra = {"format": "WEBP", "quality": 88, "method": 4}
    frames[0].save(
        out,
        save_all=True,
        append_images=frames[1:],
        duration=int(1000 / fps),
        loop=0,
        **extra,
    )

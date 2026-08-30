"""Motores de generación intercambiables.

Cada motor declara en config/motores.json su arquitectura, archivos de modelo
y parámetros por defecto. Este módulo comprueba qué motores están instalados
(los archivos existen en ComfyUI/models/) y construye el workflow API de
ComfyUI para cada arquitectura:

- sdxl   : checkpoint + LoRA clásicos (KSampler, CFG real con negative).
- zimage : Z-Image Turbo (DiT 6B destilado, cfg 1, negativo anulado, shift 3).
- flux2  : FLUX.2 Klein 4B destilado (SamplerCustomAdvanced + Flux2Scheduler),
           con modo edición por imagen de referencia (ReferenceLatent).
- wan22  : Wan 2.2 TI2V 5B, imagen→video (Wan22ImageToVideoLatent).
- wan22_moe : Wan 2.2 I2V A14B, imagen→video con MoE de DOS expertos
           (high noise + low noise) que se muestrean en cadena con dos
           KSamplerAdvanced. Nunca están los dos en memoria a la vez.

Las recetas provienen de los blueprints oficiales incluidos en el propio
ComfyUI instalado, así que los class_type coinciden con esta versión.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENGINES_PATH = PROJECT_ROOT / "config" / "motores.json"
MODELS_DIR = PROJECT_ROOT / "ComfyUI" / "models"


def load_registry() -> dict[str, Any]:
    return json.loads(ENGINES_PATH.read_text(encoding="utf-8"))


def get_engine(engine_id: str | None = None) -> dict[str, Any]:
    reg = load_registry()
    engine_id = engine_id or reg.get("default")
    for engine in reg["engines"]:
        if engine["id"] == engine_id:
            return engine
    known = ", ".join(e["id"] for e in reg["engines"])
    raise ValueError(f"Motor desconocido '{engine_id}'. Disponibles: {known}")


def resolve_file(folder: str, spec: str) -> str | None:
    """De una spec "a|b" devuelve el primer archivo que exista en models/."""
    for name in spec.split("|"):
        if (MODELS_DIR / folder / name).exists():
            return name
    return None


def list_loras() -> list[str]:
    """Archivos .safetensors disponibles en ComfyUI/models/loras."""
    d = MODELS_DIR / "loras"
    if not d.is_dir():
        return []
    return sorted(p.name for p in d.glob("*.safetensors"))


def _chain_loras(
    wf: dict[str, Any], loras: list[dict[str, Any]] | None, model_ref: list,
    prefix: str = "lora",
) -> list:
    """Encadena N LoraLoaderModelOnly sobre `model_ref` y devuelve la salida
    del último. Cada LoRA es {"name": str, "strength": float}. Los LoRA se
    aplican SIEMPRE que estén cargados: el prompt no los activa ni desactiva,
    solo sus palabras de activación refuerzan el efecto.

    `prefix` separa las claves del grafo cuando se encadenan LoRA sobre más de
    un modelo en el mismo workflow (los dos expertos de un MoE)."""
    for i, lora in enumerate(loras or []):
        name = (lora.get("name") or "").strip()
        if not name or not (MODELS_DIR / "loras" / name).exists():
            continue
        key = f"{prefix}_{i}"
        wf[key] = {
            "class_type": "LoraLoaderModelOnly",
            "inputs": {"model": model_ref, "lora_name": name,
                       "strength_model": float(lora.get("strength", 1.0))},
        }
        model_ref = [key, 0]
    return model_ref


def _clip_loader(engine: dict[str, Any], clip_type: str) -> dict[str, Any]:
    """Nodo cargador del text encoder según el formato del archivo.

    Los encoders .gguf (cuantizados o abliterados) no los carga el CLIPLoader
    estándar: necesitan CLIPLoaderGGUF, de la extensión ComfyUI-GGUF, que
    acepta los mismos inputs salvo `device`."""
    name = resolve_file("text_encoders", engine["files"]["text_encoders"][0])
    if name and name.lower().endswith(".gguf"):
        return {"class_type": "CLIPLoaderGGUF",
                "inputs": {"clip_name": name, "type": clip_type}}
    return {"class_type": "CLIPLoader",
            "inputs": {"clip_name": name, "type": clip_type, "device": "default"}}


def _unet_loader(name: str, weight_dtype: str = "default") -> dict[str, Any]:
    """Nodo cargador del modelo de difusión según el formato del archivo.

    Los .gguf cuantizados los carga UnetLoaderGGUF (extensión ComfyUI-GGUF),
    que busca en las mismas carpetas que diffusion_models y NO acepta
    weight_dtype: la cuantización ya viene en el archivo."""
    if name and name.lower().endswith(".gguf"):
        return {"class_type": "UnetLoaderGGUF", "inputs": {"unet_name": name}}
    return {"class_type": "UNETLoader",
            "inputs": {"unet_name": name, "weight_dtype": weight_dtype}}


def engine_status(engine: dict[str, Any]) -> tuple[bool, list[str]]:
    missing = []
    for folder, specs in engine.get("files", {}).items():
        for spec in specs:
            if resolve_file(folder, spec) is None:
                missing.append(f"{folder}/{spec.split('|')[0]}")
    return (not missing, missing)


def list_engines() -> list[dict[str, Any]]:
    reg = load_registry()
    out = []
    for engine in reg["engines"]:
        installed, missing = engine_status(engine)
        out.append({
            "id": engine["id"],
            "label": engine["label"],
            "kind": engine["kind"],
            "description": engine.get("description", ""),
            "installed": installed,
            "missing": missing,
            "params": engine.get("params", {}),
            "default": engine["id"] == reg.get("default"),
        })
    return out


def require_installed(engine: dict[str, Any]) -> None:
    installed, missing = engine_status(engine)
    if not installed:
        raise RuntimeError(
            f"Al motor '{engine['label']}' le faltan archivos: {', '.join(missing)}"
        )


def _lora_file(engine: dict[str, Any]) -> str | None:
    lora = engine.get("params", {}).get("lora")
    if not lora:
        return None
    return resolve_file("loras", lora)


# ---------------------------------------------------------------------------
# Constructores de workflow (formato API de ComfyUI)
# ---------------------------------------------------------------------------

def build_image_graph(
    engine: dict[str, Any],
    prompt: str,
    negative: str,
    seed: int,
    steps: int | None = None,
    cfg: float | None = None,
    width: int | None = None,
    height: int | None = None,
    loras: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    arch = engine["arch"]
    p = engine["params"]
    steps = steps or p["steps"]
    cfg = cfg if cfg is not None else p["cfg"]
    width = width or p["width"]
    height = height or p["height"]

    if arch == "sdxl":
        return _sdxl_graph(p, prompt, negative, seed, steps, cfg, width, height)
    if arch == "zimage":
        return _zimage_graph(engine, prompt, seed, steps, cfg, width, height)
    if arch == "flux2":
        return _flux2_graph(engine, prompt, seed, steps, cfg, width, height,
                            ref_image=None, loras=loras)
    raise ValueError(f"Arquitectura de imagen no soportada: {arch}")


def build_edit_graph(
    engine: dict[str, Any],
    prompt: str,
    ref_image_name: str,
    seed: int,
    steps: int | None = None,
    width: int | None = None,
    height: int | None = None,
    loras: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """El latente de salida debe medir lo mismo que la referencia para no
    distorsionar; pásale width/height del sprite de referencia."""
    if engine["arch"] != "flux2":
        raise ValueError("La edición por referencia requiere el motor FLUX.2 Klein")
    p = engine["params"]
    steps = steps or p.get("edit_steps", 8)
    return _flux2_graph(engine, prompt, seed, steps, p["cfg"],
                        width or p["width"], height or p["height"],
                        ref_image=ref_image_name, loras=loras)


def build_video_graph(
    engine: dict[str, Any],
    prompt: str,
    negative: str,
    start_image_name: str,
    seed: int,
    length: int | None = None,
    width: int | None = None,
    height: int | None = None,
) -> dict[str, Any]:
    if engine["arch"] not in ("wan22", "wan22_moe"):
        raise ValueError("El video requiere un motor Wan 2.2")
    p = engine["params"]
    width = width or p["width"]
    height = height or p["height"]
    length = length or p["length"]
    if engine["arch"] == "wan22_moe":
        return _wan22_moe_graph(engine, prompt, negative, start_image_name,
                                seed, length, width, height)
    model_file = resolve_file("diffusion_models", engine["files"]["diffusion_models"][0])

    wf: dict[str, Any] = {
        "unet": _unet_loader(model_file, p.get("weight_dtype", "default")),
        "clip": _clip_loader(engine, "wan"),
        "vae": {"class_type": "VAELoader",
                "inputs": {"vae_name": resolve_file("vae", engine["files"]["vae"][0])}},
        "pos": {"class_type": "CLIPTextEncode",
                "inputs": {"clip": ["clip", 0], "text": prompt}},
        "neg": {"class_type": "CLIPTextEncode",
                "inputs": {"clip": ["clip", 0], "text": negative}},
        "start": {"class_type": "LoadImage", "inputs": {"image": start_image_name}},
        "latent": {"class_type": "Wan22ImageToVideoLatent",
                   "inputs": {"vae": ["vae", 0], "width": width, "height": height,
                              "length": length, "batch_size": 1,
                              "start_image": ["start", 0]}},
        "shift": {"class_type": "ModelSamplingSD3",
                  "inputs": {"model": ["unet", 0], "shift": p.get("shift", 8)}},
        "sampler": {"class_type": "KSampler",
                    "inputs": {"model": ["shift", 0], "positive": ["pos", 0],
                               "negative": ["neg", 0], "latent_image": ["latent", 0],
                               "seed": seed, "steps": p["steps"], "cfg": p["cfg"],
                               "sampler_name": p["sampler"], "scheduler": p["scheduler"],
                               "denoise": 1.0}},
        "decode": {"class_type": "VAEDecode",
                   "inputs": {"samples": ["sampler", 0], "vae": ["vae", 0]}},
        "save": {"class_type": "SaveImage",
                 "inputs": {"images": ["decode", 0], "filename_prefix": "spritegen_video"}},
    }
    lora = _lora_file(engine)
    if lora:
        wf["shift"]["inputs"]["model"] = _chain_loras(
            wf, [{"name": lora, "strength": p.get("lora_strength", 1.0)}], ["unet", 0]
        )
    return wf


def _expert_loras(engine: dict[str, Any], side: str) -> list[dict[str, Any]]:
    """LoRA que se aplican a UN experto del MoE: primero el acelerador
    lightx2v de su lado (high/low), después el LoRA de estilo, que es común a
    los dos expertos porque comparten arquitectura."""
    p = engine["params"]
    out = []
    accel = p.get(f"lora_{side}")
    if accel:
        out.append({"name": accel, "strength": p.get("lora_accel_strength", 1.0)})
    style = p.get("lora")
    if style:
        out.append({"name": style, "strength": p.get("lora_strength", 1.0)})
    return out


def _wan22_moe_graph(
    engine: dict[str, Any],
    prompt: str,
    negative: str,
    start_image_name: str,
    seed: int,
    length: int,
    width: int,
    height: int,
) -> dict[str, Any]:
    """Wan 2.2 I2V A14B: MoE de dos expertos muestreados en cadena.

    El experto high noise resuelve la composición y el movimiento en los
    primeros pasos y pasa el latente con ruido residual al low noise, que
    remata el detalle. Cada uno lleva su propio LoRA acelerador lightx2v (4
    pasos totales a cfg 1) más el LoRA de estilo, si el motor declara uno.
    Receta tomada del template oficial video_wan2_2_14B_i2v.json.
    """
    p = engine["params"]
    specs = engine["files"]["diffusion_models"]
    if len(specs) < 2:
        raise ValueError(
            f"El motor '{engine['id']}' es un MoE: necesita DOS entradas en "
            "files.diffusion_models (high noise y low noise, en ese orden)"
        )
    high_file = resolve_file("diffusion_models", specs[0])
    low_file = resolve_file("diffusion_models", specs[1])
    steps = int(p.get("steps", 4))
    # Paso en el que el experto high noise cede el latente al low noise
    boundary = max(1, min(steps - 1, int(p.get("boundary_step", steps // 2))))
    dtype = p.get("weight_dtype", "default")

    wf: dict[str, Any] = {
        "clip": _clip_loader(engine, "wan"),
        "vae": {"class_type": "VAELoader",
                "inputs": {"vae_name": resolve_file("vae", engine["files"]["vae"][0])}},
        "pos": {"class_type": "CLIPTextEncode",
                "inputs": {"clip": ["clip", 0], "text": prompt}},
        "neg": {"class_type": "CLIPTextEncode",
                "inputs": {"clip": ["clip", 0], "text": negative}},
        "start": {"class_type": "LoadImage", "inputs": {"image": start_image_name}},
        # Devuelve (positive, negative, latent): mete la imagen de arranque en
        # el condicionamiento, no solo en el latente
        "i2v": {"class_type": "WanImageToVideo",
                "inputs": {"positive": ["pos", 0], "negative": ["neg", 0],
                           "vae": ["vae", 0], "width": width, "height": height,
                           "length": length, "batch_size": 1,
                           "start_image": ["start", 0]}},
        "unet_high": _unet_loader(high_file, dtype),
        "unet_low": _unet_loader(low_file, dtype),
    }
    high_ref = _chain_loras(wf, _expert_loras(engine, "high"), ["unet_high", 0], "lhigh")
    low_ref = _chain_loras(wf, _expert_loras(engine, "low"), ["unet_low", 0], "llow")
    shift = p.get("shift", 5)
    wf["shift_high"] = {"class_type": "ModelSamplingSD3",
                        "inputs": {"model": high_ref, "shift": shift}}
    wf["shift_low"] = {"class_type": "ModelSamplingSD3",
                       "inputs": {"model": low_ref, "shift": shift}}
    common = {"steps": steps, "cfg": p["cfg"],
              "sampler_name": p["sampler"], "scheduler": p["scheduler"],
              "positive": ["i2v", 0], "negative": ["i2v", 1]}
    wf["k_high"] = {"class_type": "KSamplerAdvanced",
                    "inputs": {**common, "model": ["shift_high", 0],
                               "add_noise": "enable", "noise_seed": seed,
                               "latent_image": ["i2v", 2],
                               "start_at_step": 0, "end_at_step": boundary,
                               "return_with_leftover_noise": "enable"}}
    wf["k_low"] = {"class_type": "KSamplerAdvanced",
                   "inputs": {**common, "model": ["shift_low", 0],
                              "add_noise": "disable", "noise_seed": 0,
                              "latent_image": ["k_high", 0],
                              "start_at_step": boundary, "end_at_step": 10000,
                              "return_with_leftover_noise": "disable"}}
    wf["decode"] = {"class_type": "VAEDecode",
                    "inputs": {"samples": ["k_low", 0], "vae": ["vae", 0]}}
    wf["save"] = {"class_type": "SaveImage",
                  "inputs": {"images": ["decode", 0],
                             "filename_prefix": "spritegen_video"}}
    return wf


def _sdxl_graph(p, prompt, negative, seed, steps, cfg, width, height):
    return {
        "ckpt": {"class_type": "CheckpointLoaderSimple",
                 "inputs": {"ckpt_name": p["checkpoint"]}},
        "lora": {"class_type": "LoraLoader",
                 "inputs": {"model": ["ckpt", 0], "clip": ["ckpt", 1],
                            "lora_name": p["lora"],
                            "strength_model": p["lora_strength"],
                            "strength_clip": p["lora_strength"]}},
        "pos": {"class_type": "CLIPTextEncode",
                "inputs": {"clip": ["lora", 1], "text": prompt}},
        "neg": {"class_type": "CLIPTextEncode",
                "inputs": {"clip": ["lora", 1], "text": negative}},
        "latent": {"class_type": "EmptyLatentImage",
                   "inputs": {"width": width, "height": height, "batch_size": 1}},
        "sampler": {"class_type": "KSampler",
                    "inputs": {"model": ["lora", 0], "positive": ["pos", 0],
                               "negative": ["neg", 0], "latent_image": ["latent", 0],
                               "seed": seed, "steps": steps, "cfg": cfg,
                               "sampler_name": p["sampler"], "scheduler": p["scheduler"],
                               "denoise": 1.0}},
        "decode": {"class_type": "VAEDecode",
                   "inputs": {"samples": ["sampler", 0], "vae": ["ckpt", 2]}},
        "save": {"class_type": "SaveImage",
                 "inputs": {"images": ["decode", 0], "filename_prefix": "spritegen"}},
    }


def _zimage_graph(engine, prompt, seed, steps, cfg, width, height):
    p = engine["params"]
    wf = {
        "unet": {"class_type": "UNETLoader",
                 "inputs": {"unet_name": resolve_file("diffusion_models", engine["files"]["diffusion_models"][0]),
                            "weight_dtype": "default"}},
        "clip": _clip_loader(engine, "lumina2"),
        "vae": {"class_type": "VAELoader",
                "inputs": {"vae_name": resolve_file("vae", engine["files"]["vae"][0])}},
        "pos": {"class_type": "CLIPTextEncode",
                "inputs": {"clip": ["clip", 0], "text": prompt}},
        "neg": {"class_type": "ConditioningZeroOut",
                "inputs": {"conditioning": ["pos", 0]}},
        "shift": {"class_type": "ModelSamplingAuraFlow",
                  "inputs": {"model": ["unet", 0], "shift": p.get("shift", 3)}},
        "latent": {"class_type": "EmptySD3LatentImage",
                   "inputs": {"width": width, "height": height, "batch_size": 1}},
        "sampler": {"class_type": "KSampler",
                    "inputs": {"model": ["shift", 0], "positive": ["pos", 0],
                               "negative": ["neg", 0], "latent_image": ["latent", 0],
                               "seed": seed, "steps": steps, "cfg": cfg,
                               "sampler_name": p["sampler"], "scheduler": p["scheduler"],
                               "denoise": 1.0}},
        "decode": {"class_type": "VAEDecode",
                   "inputs": {"samples": ["sampler", 0], "vae": ["vae", 0]}},
        "save": {"class_type": "SaveImage",
                 "inputs": {"images": ["decode", 0], "filename_prefix": "spritegen"}},
    }
    lora = _lora_file(engine)
    if lora:
        wf["lora"] = {"class_type": "LoraLoaderModelOnly",
                      "inputs": {"model": ["unet", 0], "lora_name": lora,
                                 "strength_model": p.get("lora_strength", 0.9)}}
        wf["shift"]["inputs"]["model"] = ["lora", 0]
    return wf


def _flux2_graph(engine, prompt, seed, steps, cfg, width, height, ref_image,
                 loras=None):
    p = engine["params"]
    wf = {
        "unet": {"class_type": "UNETLoader",
                 "inputs": {"unet_name": resolve_file("diffusion_models", engine["files"]["diffusion_models"][0]),
                            "weight_dtype": "default"}},
        "clip": _clip_loader(engine, "flux2"),
        "vae": {"class_type": "VAELoader",
                "inputs": {"vae_name": resolve_file("vae", engine["files"]["vae"][0])}},
        "pos": {"class_type": "CLIPTextEncode",
                "inputs": {"clip": ["clip", 0], "text": prompt}},
        "neg": {"class_type": "ConditioningZeroOut",
                "inputs": {"conditioning": ["pos", 0]}},
        "noise": {"class_type": "RandomNoise", "inputs": {"noise_seed": seed}},
        "ksampler_sel": {"class_type": "KSamplerSelect",
                         "inputs": {"sampler_name": p.get("sampler", "euler")}},
        "sigmas": {"class_type": "Flux2Scheduler",
                   "inputs": {"steps": steps, "width": width, "height": height}},
        "latent": {"class_type": "EmptyFlux2LatentImage",
                   "inputs": {"width": width, "height": height, "batch_size": 1}},
        "guider": {"class_type": "CFGGuider",
                   "inputs": {"model": ["unet", 0], "positive": ["pos", 0],  # se reescribe abajo si hay LoRA
                              "negative": ["neg", 0], "cfg": cfg}},
        "sampler": {"class_type": "SamplerCustomAdvanced",
                    "inputs": {"noise": ["noise", 0], "guider": ["guider", 0],
                               "sampler": ["ksampler_sel", 0], "sigmas": ["sigmas", 0],
                               "latent_image": ["latent", 0]}},
        "decode": {"class_type": "VAEDecode",
                   "inputs": {"samples": ["sampler", 0], "vae": ["vae", 0]}},
        "save": {"class_type": "SaveImage",
                 "inputs": {"images": ["decode", 0], "filename_prefix": "spritegen"}},
    }
    if ref_image:
        wf["ref"] = {"class_type": "LoadImage", "inputs": {"image": ref_image}}
        wf["ref_latent"] = {"class_type": "VAEEncode",
                            "inputs": {"pixels": ["ref", 0], "vae": ["vae", 0]}}
        wf["pos_ref"] = {"class_type": "ReferenceLatent",
                         "inputs": {"conditioning": ["pos", 0], "latent": ["ref_latent", 0]}}
        wf["neg_ref"] = {"class_type": "ReferenceLatent",
                         "inputs": {"conditioning": ["neg", 0], "latent": ["ref_latent", 0]}}
        wf["guider"]["inputs"]["positive"] = ["pos_ref", 0]
        wf["guider"]["inputs"]["negative"] = ["neg_ref", 0]
    # LoRAs encadenados entre el modelo y el guider. Si el llamador no pasa
    # ninguno se usan los declarados por el motor en motores.json.
    wf["guider"]["inputs"]["model"] = _chain_loras(
        wf, loras if loras is not None else p.get("loras"), ["unet", 0]
    )
    return wf

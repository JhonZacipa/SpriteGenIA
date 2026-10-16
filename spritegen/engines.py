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
- trellis2 / pixal3d : imagen→malla 3D texturizada (GLB), nodos nativos de
           ComfyUI: tres muestreos encadenados (estructura, forma, textura)
           y el postproceso de malla (remesh, decimado, UV, horneado PBR).

Las recetas provienen de los blueprints oficiales incluidos en el propio
ComfyUI instalado, así que los class_type coinciden con esta versión. La de
3D sale de la plantilla 3d_pixal3d_trellis2_image_to_model.json (paquete
comfyui-workflow-templates), que la versión instalada aún no trae.
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


def build_model3d_graph(
    engine: dict[str, Any],
    image_name: str,
    seed: int,
    faces: int,
    texture: int,
    mask_from_alpha: bool = False,
    remesh: int | None = None,
) -> dict[str, Any]:
    """Imagen → malla 3D texturizada con TRELLIS.2 o Pixal3D nativos.

    Receta de la plantilla oficial con dos recortes MEDIDOS en 16 GB de VRAM
    (ComfyUI 0.33): la cascada de forma va a 1024 (a 1536 el upsample tarda
    26 s por paso) y el remallado a 512 (a 768 RemeshMesh agota la VRAM). Sin
    remallado sale peor y tarda más: decimar la malla del VAE cuesta 2 min.

    Devuelve dos salidas: `save` (el GLB) y `thumb` (miniatura RGBA en vista
    isométrica para el archivo; RenderMesh no ilumina, solo sirve de vista).

    mask_from_alpha: la imagen ya trae el sujeto recortado en su canal alfa.
    Si no, BiRefNet separa el sujeto del fondo dentro del propio grafo.
    remesh: resolución del remallado; por defecto la del motor (el llamador
    la baja para reintentar tras un OOM).
    """
    arch = engine["arch"]
    if arch not in ("trellis2", "pixal3d"):
        raise ValueError(f"Arquitectura 3D no soportada: {arch}")
    p = engine["params"]
    files = engine["files"]
    unet = resolve_file("diffusion_models", files["diffusion_models"][0])
    vae_shape = resolve_file("vae", files["vae"][0])
    vae_tex = resolve_file("vae", files["vae"][1])
    clip_vision = resolve_file("clip_vision", files["clip_vision"][0])

    wf: dict[str, Any] = {}

    def node(key: str, cls: str, **inputs: Any) -> list:
        wf[key] = {"class_type": cls, "inputs": inputs}
        return [key, 0]

    node("clipv", "CLIPVisionLoader", clip_name=clip_vision)
    node("unet", "UNETLoader", unet_name=unet, weight_dtype="default")
    node("vae_shape", "VAELoader", vae_name=vae_shape)
    node("vae_tex", "VAELoader", vae_name=vae_tex)
    node("load", "LoadImage", image=image_name)
    if mask_from_alpha:
        # LoadImage devuelve la máscara INVERTIDA (1 = transparente, la
        # convención del inpainting): ImageCropToMask la quiere al revés
        mask = node("mask", "InvertMask", mask=["load", 1])
    else:
        node("bg_model", "LoadBackgroundRemovalModel",
             bg_removal_name=resolve_file("background_removal",
                                          files["background_removal"][0]))
        mask = node("mask", "RemoveBackground", bg_removal_model=["bg_model", 0],
                    image=["load", 0])
    node("crop", "ImageCropToMask", images=["load", 0], masks=mask, width=1024,
         height=1024, pad_factor=float(p.get("pad_factor", 1.0)), grow_mask=0,
         background="#000000")
    if arch == "trellis2":
        node("cond", "Trellis2Conditioning", clip_vision_model=["clipv", 0],
             image=["crop", 0])
    else:
        node("cond", "Pixal3DConditioning", clip_vision_model=["clipv", 0],
             image=["crop", 0], camera_angle_x=float(p.get("fov", 49.13)))
    pos, neg = ["cond", 0], ["cond", 1]

    # 1 · Estructura dispersa (voxel 32: con "64" el upsample saca «cortinas»).
    # CFGOverride + RescaleCFG replican el guidance interval del pipeline original
    node("cfg_ss", "CFGOverride", model=["unet", 0], cfg=1.0, start_percent=0.667,
         end_percent=1.0)
    node("rescale_ss", "RescaleCFG", model=["cfg_ss", 0], multiplier=0.7)
    node("shift_ss", "ModelSamplingSD3", model=["rescale_ss", 0], shift=5.0)
    node("latent_ss", "EmptyTrellis2LatentStructure", batch_size=1)
    node("k_ss", "KSampler", model=["shift_ss", 0], positive=pos, negative=neg,
         latent_image=["latent_ss", 0], seed=seed, steps=12, cfg=7.5,
         sampler_name="euler", scheduler="normal", denoise=1.0)
    node("dec_ss", "VaeDecodeStructureTrellis2", samples=["k_ss", 0],
         vae=["vae_shape", 0], resolution="32")

    # 2 · Forma a 512 y cascada a la resolución final
    node("stage_shape", "Trellis2ShapeStage", positive=pos, negative=neg,
         voxel=["dec_ss", 0])
    node("cfg_sh", "CFGOverride", model=["unet", 0], cfg=1.0, start_percent=0.769,
         end_percent=1.0)
    node("rescale_sh", "RescaleCFG", model=["cfg_sh", 0], multiplier=0.5)
    node("k_sh", "KSampler", model=["rescale_sh", 0], positive=["stage_shape", 0],
         negative=["stage_shape", 1], latent_image=["stage_shape", 2], seed=seed,
         steps=20, cfg=7.5, sampler_name="euler", scheduler="normal", denoise=1.0)
    node("up", "Trellis2UpsampleStage", positive=["stage_shape", 0],
         negative=["stage_shape", 1], shape_latent=["k_sh", 0], vae=["vae_shape", 0],
         target_resolution=int(p.get("cascade", 1024)))
    node("k_up", "KSampler", model=["rescale_sh", 0], positive=["up", 0],
         negative=["up", 1], latent_image=["up", 2], seed=seed, steps=12, cfg=7.5,
         sampler_name="euler", scheduler="simple", denoise=1.0)
    node("dec_sh", "VaeDecodeShapeTrellis", samples=["k_up", 0], vae=["vae_shape", 0])

    # 3 · Textura, a cfg 1 (como en la plantilla)
    node("stage_tex", "Trellis2TextureStage", positive=["up", 0], negative=["up", 1],
         shape_latent=["k_up", 0])
    node("k_tex", "KSampler", model=["unet", 0], positive=["stage_tex", 0],
         negative=["stage_tex", 1], latent_image=["stage_tex", 2], seed=seed,
         steps=12, cfg=1.0, sampler_name="euler", scheduler="normal", denoise=1.0)
    node("dec_tex", "VaeDecodeTextureTrellis", samples=["k_tex", 0],
         vae=["vae_tex", 0], shape_subdivides=["dec_sh", 1])

    # 4 · Postproceso: remallado → decimado → UV → horneado PBR, relieve y AO.
    # Las DynamicCombo viajan en la API como "campo" + "campo.subcampo"
    # precluster_max_verts reduce la malla del VAE antes de remallar: su consumo
    # crece con ella, y con 20 M (el valor de la plantilla) una casa en calidad
    # «detalle» agotó la VRAM incluso remallando a 512
    node("remesh", "RemeshMesh", mesh=["dec_sh", 0],
         resolution=int(remesh or p.get("remesh", 512)),
         sign_mode="udf", band=1.0, project_back=0.0, fix_poles=False, smooth_iters=20,
         drop_small_components=0.01,
         precluster_max_verts=int(p.get("remesh_precluster", 20_000_000)),
         **{"sign_mode.qef": False, "sign_mode.drop_inverted_components": False,
            "sign_mode.drop_enclosed_components": False})
    node("decimate", "DecimateMesh", mesh=["remesh", 0], target_face_count=int(faces),
         placement_mode="midpoint")
    node("smooth", "MeshSmoothNormals", mesh=["decimate", 0], crease_angle=180.0)
    node("unwrap", "UnwrapMesh", mesh=["smooth", 0], segmenter="pec",
         resolution=int(texture), padding=1, weld_distance=0.0002)
    # reference_mesh: proyecta cada texel sobre la superficie densa antes de
    # muestrear el color, para que la malla decimada no salga facetada
    node("bake", "BakeTextureFromVoxel", mesh=["unwrap", 0], voxel_colors=["dec_tex", 0],
         texture_size=int(texture), reference_mesh=["dec_sh", 0])
    node("normal", "BakeNormalMapFromMesh", low_poly=["unwrap", 0], high_poly=["remesh", 0],
         resolution=min(2048, int(texture)), cage_distance=0.05, ignore_backfaces=True)
    node("ao", "BakeAmbientOcclusion", low_poly=["unwrap", 0], high_poly=["remesh", 0],
         resolution=min(1024, int(texture)), samples=64, max_distance=0.71,
         strength=1.0, bias=0.01)
    node("apply", "ApplyTextureToMesh", mesh=["unwrap", 0], base_color=["bake", 0],
         metallic=["bake", 1], roughness=["bake", 2], occlusion=["ao", 0],
         normal_map=["normal", 0])
    node("final", "MeshSmoothNormals", mesh=["apply", 0], crease_angle=180.0)
    node("save", "SaveGLB", mesh=["final", 0], filename_prefix="spritegen3d/modelo")

    # Miniatura para el archivo: girado 45° y elevado 30°, la vista isométrica
    node("rot_y", "RotateMesh", mesh=["final", 0], mode="euler_xyz",
         **{"mode.angle_x": 0.0, "mode.angle_y": 45.0, "mode.angle_z": 0.0})
    node("rot_x", "RotateMesh", mesh=["rot_y", 0], mode="euler_xyz",
         **{"mode.angle_x": 30.0, "mode.angle_y": 0.0, "mode.angle_z": 0.0})
    node("render", "RenderMesh", mesh=["rot_x", 0], mode="texture", width=512,
         height=512, background="#000000")
    node("thumb_alpha", "InvertMask", mask=["render", 1])
    node("thumb_rgba", "JoinImageWithAlpha", image=["render", 0], alpha=["thumb_alpha", 0])
    node("thumb", "SaveImage", images=["thumb_rgba", 0], filename_prefix="spritegen3d/miniatura")
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

from __future__ import annotations

import ctypes
import json
import shutil
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image
from pydantic import BaseModel, Field

from spritegen import engines as eng
from spritegen.animate import animate_sprite, upload_image
from spritegen.animate_video import animate_video_sprite
from spritegen.background import (
    remove_flat_background,
    remove_soft_shadow,
    strip_shadow_result,
)
from spritegen.pixelize import pixelize
from spritegen.effects import (
    export_effect,
    flame_frames,
    list_frames,
    make_cloth,
    smoke_frames,
    sway_frames,
    wave_frames,
)
from spritegen.generate import (
    DEFAULT_SERVER,
    PROJECT_ROOT,
    ensure_server,
    finalize_generation,
    generate_sprite,
    run_workflow,
    server_alive,
    unique_stem,
)
from spritegen.palette import extract_palette, load_palette, save_palette
from spritegen.poses import ANIMATIONS, ASSETS_DIR, ensure_poses
from spritegen.terrain import TERRAIN_DIR, build_tileset, generate_terrain, list_terrains

CONFIG_PATH = PROJECT_ROOT / "config" / "estilo.json"
# Estado de la VISTA (no del estilo): si el historial destapa los elementos
# ocultos. Va en su propio archivo porque estilo.json solo admite claves de
# estilo; mezclarlas rompería los flujos que lo leen.
VIEW_PATH = PROJECT_ROOT / "config" / "vista.json"
PALETTE_PATH = PROJECT_ROOT / "palettes" / "proyecto.txt"
OUTPUT_DIR = PROJECT_ROOT / "output"
META_DIR = OUTPUT_DIR / "meta"
STATIC_DIR = Path(__file__).parent / "static"

# La GPU es una sola: se atiende una generación a la vez
GENERATION_LOCK = threading.Lock()
# Progreso de la animación en curso (frames completados / total)
PROGRESS = {"current": 0, "total": 0}
# Cola de clips encadenados: corre en un hilo aparte para que la GUI (y el
# navegador) puedan cerrarse sin abortarla. Secuencial por diseño: cada clip
# no arranca hasta que el anterior ha escrito su archivo y su meta, así que
# no hace falta ningún delay entre ellos.
BATCH = {
    "running": False, "current": 0, "total": 0, "prompt": "",
    "done": [], "error": None, "cancel": False, "last_id": None,
}


@contextmanager
def generation_lock():
    """Serializa el acceso a la GPU; responde 409 si ya hay trabajo en curso."""
    if not GENERATION_LOCK.acquire(blocking=False):
        raise HTTPException(409, "Ya hay una generación en curso, espera a que termine")
    try:
        yield
    finally:
        GENERATION_LOCK.release()


# ---------- Ocultar contenidos ----------
# Un elemento marcado con `hidden` desaparece del historial de la GUI Y sus
# archivos quedan marcados como ocultos para el Explorador de Windows.

FILE_ATTRIBUTE_HIDDEN = 0x02
_INVALID_ATTRS = 0xFFFFFFFF
_K32 = None


def _kernel32():
    """kernel32 con las firmas declaradas. Sin declarar el restype unsigned,
    el 0xFFFFFFFF que devuelve GetFileAttributesW al fallar llegaría como -1."""
    global _K32
    if _K32 is None and sys.platform == "win32":
        _K32 = ctypes.windll.kernel32
        _K32.GetFileAttributesW.argtypes = [ctypes.c_wchar_p]
        _K32.GetFileAttributesW.restype = ctypes.c_uint32
        _K32.SetFileAttributesW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32]
    return _K32


def _set_os_hidden(path: Path, on: bool) -> None:
    """Marca o desmarca un archivo/carpeta como oculto para el Explorador.
    Preserva el resto de atributos (los del proyecto llevan ARCHIVE y
    NOT_CONTENT_INDEXED) en vez de pisarlos con FILE_ATTRIBUTE_NORMAL.
    No-op silencioso fuera de Windows o si la ruta ya no existe: esconder es un
    extra y nunca debe tumbar la petición."""
    k32 = _kernel32()
    if k32 is None or not path.exists():
        return
    try:
        attrs = k32.GetFileAttributesW(str(path))
        if attrs == _INVALID_ATTRS:
            return
        nuevos = attrs | FILE_ATTRIBUTE_HIDDEN if on else attrs & ~FILE_ATTRIBUTE_HIDDEN
        if nuevos != attrs:
            k32.SetFileAttributesW(str(path), nuevos)
    except OSError:
        pass


def _item_paths(meta: dict, stem: str) -> list[Path]:
    """Archivos y carpetas que componen un elemento del historial. Compartida
    por el ocultado y el borrado para que las dos listas no se desincronicen."""
    rutas: list[Path] = []
    if meta.get("sprite"):
        rutas.append(OUTPUT_DIR / Path(meta["sprite"]).name)
    if meta.get("sheet"):
        rutas.append(OUTPUT_DIR / Path(meta["sheet"]).name)
    if meta.get("raw"):
        rutas.append(OUTPUT_DIR / "raw" / Path(meta["raw"]).name)
    if meta.get("video"):
        rutas.append(OUTPUT_DIR / "raw" / Path(meta["video"]).name)
    frames_dir = OUTPUT_DIR / "frames" / stem
    if frames_dir.is_dir():
        rutas.append(frames_dir)
    # Un terreno guarda además sus tiles base en output/terrain/<id>/
    if meta.get("kind") == "terrain" and meta.get("terrain_id"):
        terreno = TERRAIN_DIR / Path(meta["terrain_id"]).name
        if terreno.is_dir():
            rutas.append(terreno)
    return rutas


def _apply_hidden(meta: dict, stem: str, on: bool) -> None:
    """Propaga el flag a los archivos del elemento. El meta json también va:
    su nombre deriva del prompt, así que delataría el contenido."""
    for ruta in _item_paths(meta, stem):
        _set_os_hidden(ruta, on)
    _set_os_hidden(META_DIR / f"{stem}.json", on)


def _write_meta(stem: str, meta: dict) -> None:
    """Guarda un meta YA EXISTENTE respetando su atributo de oculto. En Windows
    write_text sobre un archivo oculto falla con «acceso denegado» (abre con
    CREATE_ALWAYS + FILE_ATTRIBUTE_NORMAL), así que hay que desmarcarlo antes y
    volver a marcarlo después."""
    path = META_DIR / f"{stem}.json"
    _set_os_hidden(path, False)
    path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    _set_os_hidden(path, bool(meta.get("hidden")))


def _reveal_hidden() -> bool:
    """¿El historial destapa ahora mismo los elementos ocultos? El estado vive
    en el servidor y no en el navegador: en localStorage, un F5 o abrir en otro
    navegador podría destaparlo todo sin querer."""
    try:
        return bool(json.loads(VIEW_PATH.read_text(encoding="utf-8")).get("reveal_hidden"))
    except (OSError, json.JSONDecodeError):
        return False


def _set_reveal_hidden(on: bool) -> None:
    VIEW_PATH.parent.mkdir(parents=True, exist_ok=True)
    VIEW_PATH.write_text(
        json.dumps({"reveal_hidden": bool(on)}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _inherit_hidden(base_meta: dict, stem: str) -> None:
    """Lo derivado de un elemento oculto nace oculto: si no, animarlo, variarlo
    o aplicarle un efecto lo destaparía por la puerta de atrás."""
    if not base_meta.get("hidden"):
        return
    try:
        meta = json.loads((META_DIR / f"{stem}.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    meta["hidden"] = True
    _write_meta(stem, meta)
    _apply_hidden(meta, stem, True)


def _base_sprite(base_id: str, kinds: tuple[str, ...] = ("sprite",)) -> tuple[dict, Path]:
    """Meta + ruta del raw de un elemento del historial usado como base."""
    try:
        meta = _meta_for(Path(base_id).name)
    except (OSError, json.JSONDecodeError):
        raise HTTPException(404, "No se encontró el sprite base")
    if kinds and meta.get("kind", "sprite") not in kinds:
        raise HTTPException(400, "Esta operación solo aplica a sprites individuales")
    raw_name = meta.get("raw")
    raw_path = OUTPUT_DIR / "raw" / Path(raw_name).name if raw_name else None
    if not raw_path or not raw_path.exists():
        raise HTTPException(404, "El sprite no conserva su imagen original de IA")
    return meta, raw_path


def _base_video_clip(base_id: str) -> tuple[dict, list[Path]] | None:
    """Si `base_id` es un clip de video libre, devuelve su meta y sus frames
    ordenados, para extenderlo. Devuelve None si no es encadenable, y así el
    endpoint sigue por la vía normal de «animar un sprite»."""
    try:
        meta = _meta_for(Path(base_id).name)
    except (OSError, json.JSONDecodeError):
        return None
    if meta.get("kind") != "animation":
        return None
    # Los clips libres anteriores al flag `raw_video` se reconocen por su firma:
    # sin reescalado (los ciclos de sprites van a x6) y nombre de modo libre
    libre = meta.get("raw_video") or (
        meta.get("scale") == 1 and str(meta.get("anim", "")).startswith("libre_")
    )
    if not libre:
        return None
    frames = list_frames(OUTPUT_DIR / "frames" / meta["id"])
    if not frames:
        raise HTTPException(404, "El clip ya no conserva sus frames en output/frames")
    return meta, frames


def _resolve_video_base(base_id: str) -> dict:
    """De dónde arranca un clip: si `base_id` es un clip de video libre se
    ENCADENA (arranca de su último frame); si es un sprite, se anima."""
    cadena = _base_video_clip(base_id)
    if cadena:
        meta, frames = cadena
        return {"meta": meta, "raw_path": frames[-1], "prev_frames": frames,
                "prev_segments": meta.get("segments"), "parent_id": meta["id"],
                "engine": "wan22_14b_free"}
    meta, raw_path = _base_sprite(base_id)
    return {"meta": meta, "raw_path": raw_path, "prev_frames": None,
            "prev_segments": None, "parent_id": None, "engine": "wan22_14b_pixel"}

app = FastAPI(title="SpriteGen")


class GenRequest(BaseModel):
    subject: str
    engine: str | None = None
    seed: int | None = None
    native: int = Field(192, ge=32, le=512)
    scale: int = Field(6, ge=1, le=12)
    colors: int = Field(32, ge=2, le=256)
    steps: int | None = Field(None, ge=1, le=80)  # Klein destilado usa 4 pasos
    cfg: float | None = Field(None, ge=1, le=20)
    use_palette: bool = False
    raw_prompt: bool = False  # prompt libre: sin plantilla de estilo ni negative


class StyleConfig(BaseModel):
    # steps/cfg del estilo alimentan los flujos siempre-SDXL (animación por
    # esqueleto y terreno); son opcionales para que la GUI no los pise con
    # los del motor seleccionado
    prompt_template: str
    negative_prompt: str
    lora_strength: float = Field(ge=0, le=1.5)
    steps: int | None = Field(None, ge=1, le=80)
    cfg: float | None = Field(None, ge=1, le=20)
    bg_removal_threshold: int = Field(ge=10, le=200)
    remove_shadow: bool = True


class AnimRequest(BaseModel):
    subject: str
    anim: str = "walk"
    seed: int | None = None
    base_id: str | None = None
    denoise: float = Field(0.85, ge=0.2, le=0.95)
    native: int = Field(128, ge=32, le=512)
    scale: int = Field(6, ge=1, le=12)
    colors: int = Field(32, ge=2, le=256)
    use_palette: bool = False


class EffectRequest(BaseModel):
    type: str  # sway | flame | wave | smoke
    base_id: str | None = None
    amplitude: int | None = Field(None, ge=1, le=24)
    flame_kind: str = "torch"
    size: int = Field(64, ge=24, le=160)
    color: str = "#B22222"
    frames: int | None = Field(None, ge=2, le=24)


class TerrainRequest(BaseModel):
    subject: str
    seed: int | None = None
    variants: int = Field(4, ge=1, le=8)
    colors: int = Field(16, ge=4, le=64)


class TilesetRequest(BaseModel):
    terrain_a: str
    terrain_b: str
    name: str | None = None


class IdRequest(BaseModel):
    id: str


class RevealRequest(BaseModel):
    # El cliente manda el valor que quiere, no un toggle ciego: así dos
    # pestañas abiertas no se pelean por el estado
    on: bool


class VariationRequest(BaseModel):
    base_id: str
    instruction: str
    seed: int | None = None
    raw_prompt: bool = False  # prompt libre: sin el sufijo de estilo pixel art


class AnimVideoRequest(BaseModel):
    base_id: str
    motion: str
    frames: int = Field(8, ge=4, le=16)
    native: int = Field(128, ge=32, le=512)
    scale: int = Field(6, ge=1, le=12)
    colors: int = Field(32, ge=2, le=256)
    use_palette: bool = False
    seed: int | None = None
    engine_id: str | None = None
    # 0 = recorrer el clip entero (movimientos no cíclicos: ataque, muerte)
    cycle_seconds: float | None = Field(None, ge=0, le=5)
    # Frames del clip que genera el modelo; se normaliza a 4n+1 aguas abajo
    length: int | None = Field(None, ge=5, le=201)


class BatchRequest(BaseModel):
    base_id: str
    prompts: list[str] = Field(..., min_length=1, max_length=40)
    engine_id: str | None = None
    length: int | None = Field(None, ge=5, le=201)
    cycle_seconds: float | None = Field(None, ge=0, le=5)
    seed: int | None = None


class PaletteRequest(BaseModel):
    sprite: str


@app.post("/api/generate")
def api_generate(req: GenRequest) -> dict:
    if not req.subject.strip():
        raise HTTPException(400, "Escribe una descripción del sprite")
    palette = None
    if req.use_palette:
        if not PALETTE_PATH.exists():
            raise HTTPException(400, "Aún no existe la paleta global del proyecto")
        palette = load_palette(PALETTE_PATH)
    with generation_lock():
        try:
            result = generate_sprite(
                req.subject.strip(),
                seed=req.seed,
                native=req.native,
                scale=req.scale,
                colors=req.colors,
                palette=palette,
                steps=req.steps,
                cfg_scale=req.cfg,
                engine_id=req.engine,
                raw_prompt=req.raw_prompt,
            )
        except Exception as exc:
            raise HTTPException(500, f"{type(exc).__name__}: {exc}")
    return _meta_for(result.raw.stem)


@app.post("/api/animate")
def api_animate(req: AnimRequest) -> dict:
    if not req.subject.strip():
        raise HTTPException(400, "Escribe una descripción del personaje")
    palette = None
    if req.use_palette:
        if not PALETTE_PATH.exists():
            raise HTTPException(400, "Aún no existe la paleta global del proyecto")
        palette = load_palette(PALETTE_PATH)
    base = None
    base_meta: dict = {}
    if req.base_id:
        base_meta, base = _base_sprite(req.base_id)

    def on_progress(current: int, total: int) -> None:
        PROGRESS["current"] = current
        PROGRESS["total"] = total

    with generation_lock():
        try:
            result = animate_sprite(
                req.subject.strip(),
                anim=req.anim,
                seed=req.seed,
                base=base,
                denoise=req.denoise,
                native=req.native,
                scale=req.scale,
                colors=req.colors,
                palette=palette,
                on_progress=on_progress,
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        except Exception as exc:
            raise HTTPException(500, f"{type(exc).__name__}: {exc}")
        finally:
            PROGRESS["current"] = PROGRESS["total"] = 0
    _inherit_hidden(base_meta, result.gif.stem)
    return _meta_for(result.gif.stem)


@app.get("/api/history")
def api_history() -> list[dict]:
    # El filtro lo decide el servidor, no un parámetro del cliente: que el
    # navegador NO pueda pedir los ocultos por su cuenta es lo que hace que
    # ocultar sea fiable.
    revelar = _reveal_hidden()
    items = []
    for meta_file in META_DIR.glob("*.json"):
        try:
            meta = _meta_for(meta_file.stem)
        except (OSError, json.JSONDecodeError):
            continue
        if meta["hidden"] and not revelar:
            continue
        items.append(meta)
    items.sort(key=lambda m: m.get("ts", ""), reverse=True)
    return items


@app.get("/api/engines")
def api_engines() -> list[dict]:
    return eng.list_engines()


@app.post("/api/variation")
def api_variation(req: VariationRequest) -> dict:
    """Variación del mismo personaje con FLUX.2 Klein (edición por referencia)."""
    if not req.instruction.strip():
        raise HTTPException(400, "Escribe la instrucción de la variación")
    base_meta, raw_path = _base_sprite(req.base_id)
    try:
        engine = eng.get_engine("klein4b")
        eng.require_installed(engine)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(400, str(exc))
    with generation_lock():
        try:
            ensure_server(DEFAULT_SERVER)
            ref_name = upload_image(DEFAULT_SERVER, raw_path)
            with Image.open(raw_path) as ref_img:
                ref_w, ref_h = ref_img.size
            seed = req.seed if req.seed is not None else int(time.time()) % (2**31)
            instruction = req.instruction.strip()
            prompt = (
                instruction if req.raw_prompt
                else f"{instruction}, pixel art style, plain white background"
            )
            png = run_workflow(
                DEFAULT_SERVER,
                eng.build_edit_graph(engine, prompt, ref_name, seed,
                                     width=ref_w, height=ref_h),
            )
            result = finalize_generation(
                png,
                subject=f"{base_meta['subject']} → {req.instruction.strip()}",
                seed=seed,
                engine_id="klein4b",
                native=int(base_meta.get("native") or 192),
                scale=max(1, int(base_meta.get("scale") or 6)),
                colors=int(base_meta.get("colors") or 32),
                steps=engine["params"].get("edit_steps", 8),
                cfg_val=engine["params"]["cfg"],
                raw_prompt=req.raw_prompt,
            )
        except Exception as exc:
            raise HTTPException(500, f"{type(exc).__name__}: {exc}")
    _inherit_hidden(base_meta, result.raw.stem)
    return _meta_for(result.raw.stem)


@app.post("/api/animate_video")
def api_animate_video(req: AnimVideoRequest) -> dict:
    """Ciclo de animación por video (Wan 2.2): identidad perfecta entre frames."""
    if not req.motion.strip():
        raise HTTPException(400, "Describe el movimiento (ej. walk cycle)")
    # Si la base es un clip de video libre, se ENCADENA: arranca de su último
    # frame y el resultado es la unión de los dos tramos
    base = _resolve_video_base(req.base_id)
    base_meta = base["meta"]
    raw_path = base["raw_path"]
    prev_frames = base["prev_frames"]
    prev_segments = base["prev_segments"]
    parent_id = base["parent_id"]
    engine_por_defecto = base["engine"]
    palette = None
    if req.use_palette:
        if not PALETTE_PATH.exists():
            raise HTTPException(400, "Aún no existe la paleta global del proyecto")
        palette = load_palette(PALETTE_PATH)
    with generation_lock():
        try:
            gif = animate_video_sprite(
                req.motion.strip(),
                base_raw=raw_path,
                base_subject=base_meta["subject"],
                frames_out=req.frames,
                seed=req.seed,
                native=req.native,
                scale=req.scale,
                colors=req.colors,
                palette=palette,
                engine_id=req.engine_id or engine_por_defecto,
                cycle_seconds=req.cycle_seconds,
                length=req.length,
                prev_frames=prev_frames,
                prev_segments=prev_segments,
                parent_id=parent_id,
            )
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(400, str(exc))
        except Exception as exc:
            raise HTTPException(500, f"{type(exc).__name__}: {exc}")
    _inherit_hidden(base_meta, gif.stem)
    return _meta_for(gif.stem)


def _run_batch(base_id: str, prompts: list[str], engine_id: str | None,
               length: int | None, cycle_seconds: float | None,
               seed: int | None) -> None:
    """Genera la cola de clips encadenados. Corre en un hilo propio.

    Es SECUENCIAL a propósito: `animate_video_sprite` no retorna hasta que el
    clip está escrito en disco con su meta, así que el siguiente tramo siempre
    encuentra los frames del anterior. Sin delays ni condiciones de carrera."""
    actual = base_id
    try:
        for i, prompt in enumerate(prompts):
            if BATCH["cancel"]:
                BATCH["error"] = f"Cancelada tras {i} de {len(prompts)} clips"
                break
            BATCH["current"] = i + 1
            BATCH["prompt"] = prompt
            base = _resolve_video_base(actual)
            gif = animate_video_sprite(
                prompt,
                base_raw=base["raw_path"],
                base_subject=base["meta"]["subject"],
                seed=seed,
                engine_id=engine_id or base["engine"],
                cycle_seconds=cycle_seconds,
                length=length,
                prev_frames=base["prev_frames"],
                prev_segments=base["prev_segments"],
                parent_id=base["parent_id"],
            )
            # Cada tramo hereda del anterior, así toda la cola nace oculta si
            # lo estaba la base
            _inherit_hidden(base["meta"], gif.stem)
            # El clip recién creado es la base del siguiente tramo
            actual = gif.stem
            BATCH["last_id"] = gif.stem
            BATCH["done"].append(gif.stem)
    except Exception as exc:
        BATCH["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        BATCH["running"] = False
        BATCH["prompt"] = ""
        GENERATION_LOCK.release()


@app.post("/api/animate_video_batch")
def api_animate_video_batch(req: BatchRequest) -> dict:
    """Encola varios clips que se generan y encadenan solos, uno tras otro."""
    prompts = [p.strip() for p in req.prompts if p.strip()]
    if not prompts:
        raise HTTPException(400, "Escribe al menos un prompt")
    # Se valida la base ANTES de arrancar el hilo, para poder responder el error
    _resolve_video_base(req.base_id)
    if not GENERATION_LOCK.acquire(blocking=False):
        raise HTTPException(409, "Ya hay una generación en curso, espera a que termine")
    BATCH.update({"running": True, "current": 0, "total": len(prompts),
                  "prompt": "", "done": [], "error": None, "cancel": False,
                  "last_id": None})
    threading.Thread(
        target=_run_batch,
        args=(req.base_id, prompts, req.engine_id, req.length,
              req.cycle_seconds, req.seed),
        daemon=True,
    ).start()
    return dict(BATCH)


@app.get("/api/batch")
def api_batch_status() -> dict:
    return dict(BATCH)


@app.post("/api/batch/cancel")
def api_batch_cancel() -> dict:
    """Para la cola DESPUÉS del clip en curso; lo generado hasta ahí se
    conserva en el historial. Para abortar el clip actual, usa el botón de
    detener el motor."""
    if BATCH["running"]:
        BATCH["cancel"] = True
    return dict(BATCH)


@app.post("/api/unshadow")
def api_unshadow(req: IdRequest) -> dict:
    """Crea una COPIA del sprite sin sombra de contacto; el original queda intacto."""
    meta, raw_path = _base_sprite(req.id)
    cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    img = remove_flat_background(
        Image.open(raw_path), threshold=cfg.get("bg_removal_threshold", 60)
    )
    img = remove_soft_shadow(img)
    palette = None
    if meta.get("used_palette") and PALETTE_PATH.exists():
        palette = load_palette(PALETTE_PATH)
    scale = max(1, int(meta.get("scale") or 6))
    result = pixelize(
        img,
        native=int(meta.get("native") or 192),
        scale=scale,
        colors=int(meta.get("colors") or 32),
        palette=palette,
        method=meta.get("method") or "nearest",
        clean=True,
    )
    result = strip_shadow_result(result, scale)

    stem = unique_stem(META_DIR, f"{Path(meta['sprite']).stem}_limpio")
    # Copia propia del raw: así borrar la copia nunca afecta al original
    shutil.copyfile(raw_path, OUTPUT_DIR / "raw" / f"{stem}.png")
    result.final.save(OUTPUT_DIR / f"{stem}.png")
    new_meta = {
        "subject": f"{meta['subject']} (sin sombra)",
        "seed": meta.get("seed", 0),
        "raw": f"{stem}.png",
        "sprite": f"{stem}.png",
        "native": meta.get("native"),
        "scale": scale,
        "colors": meta.get("colors"),
        "method": meta.get("method"),
        "used_palette": bool(meta.get("used_palette")),
        "steps": meta.get("steps", 0),
        "cfg": meta.get("cfg", 0),
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        # La copia de un sprite oculto nace oculta: si no, el botón 🧹 lo
        # devolvería a la vista
        "hidden": bool(meta.get("hidden")),
    }
    (META_DIR / f"{stem}.json").write_text(
        json.dumps(new_meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if new_meta["hidden"]:
        _apply_hidden(new_meta, stem, True)
    return _meta_for(stem)


@app.post("/api/favorite")
def api_favorite(req: IdRequest) -> dict:
    """Alterna la marca ⭐ de un elemento: candidatos al dataset del LoRA (Fase 4)."""
    stem = Path(req.id).name
    meta_path = META_DIR / f"{stem}.json"
    if not meta_path.exists():
        raise HTTPException(404, "No existe esa generación")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["favorite"] = not meta.get("favorite", False)
    _write_meta(stem, meta)
    return _meta_for(stem)


@app.post("/api/hide")
def api_hide(req: IdRequest) -> dict:
    """Alterna la marca 👁 de un elemento: desaparece del historial salvo que
    el interruptor «ver ocultos» esté activo, y sus archivos quedan marcados
    como ocultos también para el Explorador de Windows."""
    stem = Path(req.id).name
    meta_path = META_DIR / f"{stem}.json"
    if not meta_path.exists():
        raise HTTPException(404, "No existe esa generación")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["hidden"] = not meta.get("hidden", False)
    _write_meta(stem, meta)
    _apply_hidden(meta, stem, meta["hidden"])
    return _meta_for(stem)


@app.post("/api/reveal")
def api_reveal(req: RevealRequest) -> dict:
    """Interruptor global del historial. Solo afecta a la VISTA: los archivos
    siguen ocultos en el Explorador mientras el elemento esté marcado."""
    _set_reveal_hidden(req.on)
    return {"reveal_hidden": _reveal_hidden()}


@app.delete("/api/history/{item_id}")
def api_delete_item(item_id: str) -> dict:
    """Elimina una generación del historial y borra sus archivos físicos."""
    stem = Path(item_id).name  # sin rutas: solo el id
    meta_path = META_DIR / f"{stem}.json"
    if not meta_path.exists():
        raise HTTPException(404, "No existe esa generación")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))

    removed: list[str] = []
    # Misma lista que usa el ocultado: así las dos nunca se desincronizan.
    # El atributo de oculto no estorba aquí (solo READONLY bloquea el borrado).
    for path in _item_paths(meta, stem):
        if path.is_dir():
            shutil.rmtree(path)
            removed.append(f"{path.parent.name}/{path.name}/")
        elif path.exists():
            path.unlink()
            removed.append(path.name)
    meta_path.unlink()
    return {"deleted": stem, "files": removed}


@app.get("/api/config")
def api_get_config() -> dict:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


@app.post("/api/config")
def api_save_config(style: StyleConfig) -> dict:
    if "{subject}" not in style.prompt_template:
        raise HTTPException(400, "La plantilla debe contener {subject}")
    cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    cfg.update(style.model_dump(exclude_none=True))
    CONFIG_PATH.write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return cfg


@app.post("/api/palette")
def api_make_palette(req: PaletteRequest) -> dict:
    sprite_path = OUTPUT_DIR / Path(req.sprite).name
    if not sprite_path.exists():
        raise HTTPException(404, f"No existe {req.sprite}")
    colors = extract_palette(Image.open(sprite_path), n=32)
    save_palette(PALETTE_PATH, colors)
    return {"colors": [f"#{r:02X}{g:02X}{b:02X}" for r, g, b in colors]}


@app.get("/api/status")
def api_status() -> dict:
    colors: list[str] = []
    if PALETTE_PATH.exists():
        colors = [
            f"#{r:02X}{g:02X}{b:02X}" for r, g, b in load_palette(PALETTE_PATH)
        ]
    ocultos, terrenos_ocultos = _hidden_summary()
    return {
        "engine_on": server_alive(DEFAULT_SERVER),
        "generating": GENERATION_LOCK.locked(),
        "progress": dict(PROGRESS),
        "palette": colors,
        "anims": _list_anims(),
        # list_terrains() escanea output/terrain/ sin leer los metas, así que
        # un terreno oculto seguiría saliendo en los selectores de tilesets
        "terrains": [t for t in list_terrains() if t["id"] not in terrenos_ocultos],
        "reveal_hidden": _reveal_hidden(),
        "hidden_count": ocultos,
    }


def _hidden_summary() -> tuple[int, set[str]]:
    """Cuántos elementos hay ocultos y qué terrain_id les pertenecen. Los dos
    datos salen del mismo recorrido de los metas.

    Cuesta ~45 ms con 272 metas y se llama cada 15 s: no se cachea a propósito,
    porque el caché habría que invalidarlo desde cuatro sitios (ocultar,
    heredar, unshadow, borrar) y olvidarse de uno daría un contador falso."""
    total = 0
    terrenos: set[str] = set()
    for meta_file in META_DIR.glob("*.json"):
        try:
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not meta.get("hidden"):
            continue
        total += 1
        if meta.get("terrain_id"):
            terrenos.add(meta["terrain_id"])
    return total, terrenos


def _list_anims() -> list[dict]:
    """Ciclos integrados + carpetas de esqueletos propios en assets/poses/."""
    items = []
    for key, spec in ANIMATIONS.items():
        try:
            files = [p.name for p in ensure_poses(key)]
        except (OSError, ValueError):
            continue
        items.append({
            "id": key,
            "label": f"{spec['label']} · {spec['frames']} frames",
            "frames": len(files),
            "files": files,
        })
    if ASSETS_DIR.is_dir():
        for d in sorted(ASSETS_DIR.iterdir()):
            if d.is_dir() and d.name not in ANIMATIONS and not d.name.startswith("_"):
                files = sorted(p.name for p in d.glob("frame_*.png"))
                if files:
                    items.append({
                        "id": d.name,
                        "label": f"{d.name} · {len(files)} frames (propio)",
                        "frames": len(files),
                        "files": files,
                    })
    return items


@app.post("/api/terrain")
def api_terrain(req: TerrainRequest) -> dict:
    if not req.subject.strip():
        raise HTTPException(400, "Escribe la textura del terreno")
    with generation_lock():
        try:
            meta = generate_terrain(
                req.subject.strip(), seed=req.seed,
                variants=req.variants, colors=req.colors,
            )
        except Exception as exc:
            raise HTTPException(500, f"{type(exc).__name__}: {exc}")
    return _meta_for(Path(meta["sprite"]).stem)


@app.post("/api/tileset")
def api_tileset(req: TilesetRequest) -> dict:
    if req.terrain_a == req.terrain_b:
        raise HTTPException(400, "Elige dos terrenos distintos")
    try:
        meta = build_tileset(req.terrain_a, req.terrain_b, name=req.name)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    # El stem del meta coincide con el del sheet (sin el sufijo "_mapa" del preview)
    return _meta_for(Path(meta["sheet"]).stem)


@app.post("/api/effect")
def api_effect(req: EffectRequest) -> dict:
    """Efectos ambientales procedurales: instantáneos, sin GPU."""
    base_img = base_meta = None
    scale = 6
    if req.base_id:
        try:
            base_meta = _meta_for(Path(req.base_id).name)
        except (OSError, json.JSONDecodeError):
            raise HTTPException(404, f"No se encontró el sprite base '{req.base_id}'")
        sprite_path = OUTPUT_DIR / Path(base_meta["sprite"]).name
        if not sprite_path.exists():
            raise HTTPException(404, "El sprite base no existe en disco")
        img = Image.open(sprite_path)
        scale = max(1, int(base_meta.get("scale") or 6))
        base_img = img.resize(
            (img.width // scale, img.height // scale), Image.Resampling.NEAREST
        )
    try:
        if req.type == "sway":
            if base_img is None:
                raise HTTPException(400, "El efecto de mecer necesita un sprite en el visor")
            frames = sway_frames(base_img, frames=req.frames or 6, amplitude=req.amplitude)
            name, subject, fps = "sway", f"{base_meta['subject']} mecido", 6
        elif req.type == "wave":
            if base_img is not None:
                cloth, subject = base_img, f"{base_meta['subject']} ondeando"
            else:
                cloth = make_cloth(96, 64, req.color)
                subject = f"bandera {req.color} ondeando"
            frames = wave_frames(cloth, frames=req.frames or 8, amplitude=req.amplitude)
            name, fps = "wave", 8
        elif req.type == "flame":
            frames = flame_frames(req.flame_kind, size=req.size, frames=req.frames or 6)
            name, subject, fps = f"flame_{req.flame_kind}", f"fuego ({req.flame_kind})", 10
        elif req.type == "smoke":
            frames = smoke_frames(width=max(16, req.size // 2), height=req.size,
                                  frames=req.frames or 8)
            name, subject, fps = "smoke", "humo de chimenea", 8
        else:
            raise HTTPException(400, f"Efecto desconocido '{req.type}'")
        gif = export_effect(frames, name=name, subject=subject, fps=fps, scale=scale)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    _inherit_hidden(base_meta or {}, gif.stem)
    return _meta_for(gif.stem)


@app.get("/api/anims/{anim_id}/preview.gif")
def api_anim_preview(anim_id: str) -> FileResponse:
    """GIF de vista previa de los esqueletos de un ciclo (cacheado en disco)."""
    anim = Path(anim_id).name
    try:
        frames = ensure_poses(anim)
    except ValueError as exc:
        raise HTTPException(404, str(exc))
    cache_dir = ASSETS_DIR / "_previews"
    cache_dir.mkdir(parents=True, exist_ok=True)
    gif = cache_dir / f"{anim}.gif"
    newest = max(p.stat().st_mtime for p in frames)
    if not gif.exists() or gif.stat().st_mtime < newest:
        fps = ANIMATIONS.get(anim, {}).get("fps", 8)
        imgs = []
        for p in frames:
            im = Image.open(p).convert("RGB")
            im.thumbnail((256, 256), Image.Resampling.LANCZOS)
            imgs.append(im)
        imgs[0].save(
            gif,
            save_all=True,
            append_images=imgs[1:],
            duration=int(1000 / fps),
            loop=0,
        )
    return FileResponse(gif, media_type="image/gif")


@app.post("/api/engine/stop")
def api_engine_stop() -> dict:
    if GENERATION_LOCK.locked():
        raise HTTPException(409, "Hay una generación en curso: espera a que termine antes de apagar el motor")
    # ExecutablePath siempre contiene la carpeta ComfyUI (el CommandLine no,
    # si se arrancó con run_comfyui.bat desde dentro del directorio)
    subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-Command",
            "Get-CimInstance Win32_Process -Filter \"Name LIKE 'python%'\" | "
            "Where-Object { $_.ExecutablePath -like '*ComfyUI*' -or $_.CommandLine -like '*ComfyUI*main.py*' } | "
            "ForEach-Object { Stop-Process -Id $_.ProcessId -Force }",
        ],
        capture_output=True,
        timeout=30,
    )
    time.sleep(1)
    return {"engine_on": server_alive(DEFAULT_SERVER)}


def _meta_for(stem: str) -> dict:
    meta = json.loads((META_DIR / f"{stem}.json").read_text(encoding="utf-8"))
    meta["id"] = stem
    meta["kind"] = meta.get("kind", "sprite")
    # Normalizado siempre: los metas anteriores a esta función no traen la clave
    meta["hidden"] = bool(meta.get("hidden", False))
    meta["sprite_url"] = f"/output/{meta['sprite']}" if meta.get("sprite") else None
    if meta.get("sheet"):
        meta["raw_url"] = f"/output/{meta['sheet']}"
    else:
        meta["raw_url"] = f"/output/raw/{meta['raw']}"
    if meta.get("video"):
        meta["video_url"] = f"/output/raw/{meta['video']}"
    return meta


OUTPUT_DIR.mkdir(exist_ok=True)
(OUTPUT_DIR / "raw").mkdir(exist_ok=True)
META_DIR.mkdir(exist_ok=True)
# Cada arranque parte con los ocultos TAPADOS. El interruptor persiste entre
# F5 y entre pestañas (que era el objetivo), pero dejarlo encendido de un día
# para otro expondría lo escondido sin querer, y ese fallo es peor que el de
# tener que volver a pulsarlo.
_set_reveal_hidden(False)
ASSETS_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/poses", StaticFiles(directory=ASSETS_DIR), name="poses")
app.mount("/output", StaticFiles(directory=OUTPUT_DIR), name="output")
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")

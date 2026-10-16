from __future__ import annotations

import json
import os
import random
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests
from PIL import Image

from spritegen import engines as eng
from spritegen import livefeed
from spritegen.background import (
    remove_flat_background,
    remove_soft_shadow,
    strip_shadow_result,
)
from spritegen.pixelize import pixelize

PROJECT_ROOT = Path(__file__).resolve().parents[1]
COMFY_DIR = PROJECT_ROOT / "ComfyUI"
CONFIG_PATH = PROJECT_ROOT / "config" / "estilo.json"
DEFAULT_SERVER = "http://127.0.0.1:8188"

# La consola de Windows usa cp1252: sin esto, imprimir un subject con "→" o
# "—" (los que crean las variaciones) lanza UnicodeEncodeError y tumba la
# generación entera. `replace` evita el fallo incluso en consolas limitadas.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass  # stream sin reconfigure (redirigido o ya cerrado)


def load_config() -> dict[str, Any]:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def unique_stem(meta_dir: Path, base: str) -> str:
    """Stem que no pisa ninguna salida previa: sufijos _vN consultando el
    meta json (regla del proyecto: NUNCA sobreescribir salidas)."""
    stem, version = base, 2
    while (meta_dir / f"{stem}.json").exists():
        stem = f"{base}_v{version}"
        version += 1
    return stem


def build_workflow(cfg: dict[str, Any], subject: str, seed: int) -> dict[str, Any]:
    """(Compatibilidad) Workflow SDXL clásico usando la config de estilo."""
    prompt = cfg["prompt_template"].replace("{subject}", subject)
    engine = eng.get_engine("sdxl_pixelart")
    return eng.build_image_graph(
        engine, prompt, cfg["negative_prompt"], seed,
        steps=cfg.get("steps"), cfg=cfg.get("cfg"),
        width=cfg.get("width"), height=cfg.get("height"),
    )


def server_alive(server: str) -> bool:
    try:
        return requests.get(f"{server}/system_stats", timeout=3).ok
    except requests.RequestException:
        return False


def ensure_server(server: str, startup_timeout: int = 180) -> None:
    """Arranca ComfyUI en segundo plano si no está corriendo."""
    if server_alive(server):
        return
    python = COMFY_DIR / ".venv" / "Scripts" / "python.exe"
    if not python.exists():
        raise RuntimeError(
            f"No existe {python}. Instala ComfyUI primero (ver README, Fase 2)."
        )
    # Lock de fichero: evita que dos clientes simultáneos (CLI + GUI) arranquen
    # dos ComfyUI durante la ventana en que aún no responde
    lock = COMFY_DIR / "comfyui.spawn.lock"

    def _claim_lock() -> bool:
        try:
            fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            return False
        os.close(fd)
        return True

    spawned = _claim_lock()
    if not spawned:
        # Lock huérfano de un arranque muerto: se retira con un rename atómico
        # (solo un proceso lo consigue), sin la ventana en que un unlink tras
        # exists()/stat() borraría el lock FRESCO de otro proceso
        try:
            stale = time.time() - lock.stat().st_mtime > 300
        except OSError:
            stale = False  # desapareció entre medias: su dueño sigue activo
        if stale:
            claim = lock.with_name(f"{lock.name}.{os.getpid()}")
            try:
                os.replace(lock, claim)
                claim.unlink(missing_ok=True)
            except OSError:
                pass  # otro proceso reclamó el huérfano primero
            spawned = _claim_lock()
    if not spawned:
        print("Otro proceso ya está arrancando ComfyUI; esperando a que responda...")
    try:
        if spawned:
            log = COMFY_DIR / "comfyui.log"
            print(f"ComfyUI no está corriendo: arrancándolo ahora (log en {log})...")
            with open(log, "ab") as out:
                subprocess.Popen(
                    # --reserve-vram: reserva mínima (0,1 GB) para el escritorio; casi
                    # toda la VRAM va a los modelos (a 0 el PC se congela)
                    # Sin --cache-none (retirado el 20/09/2026): la caché por defecto
                    # (--cache-ram) retiene los modelos entre generaciones, así el 2º
                    # clip Wan no recarga los expertos desde disco. Cuesta RAM en reposo
                    # (~9 GB): apagar el motor al terminar sigue siendo lo recomendado
                    # --preview-method auto: emite previews del latente por su
                    # WebSocket (latent2rgb, coste ínfimo) para la miniatura
                    # en vivo de la GUI (spritegen/livefeed.py)
                    [
                        str(python), "main.py",
                        "--reserve-vram", "0.1",
                        "--preview-method", "auto",
                    ],
                    cwd=COMFY_DIR,
                    stdout=out,
                    stderr=subprocess.STDOUT,
                    creationflags=subprocess.DETACHED_PROCESS
                    | subprocess.CREATE_NEW_PROCESS_GROUP,
                )
        deadline = time.time() + startup_timeout
        while time.time() < deadline:
            if server_alive(server):
                print("ComfyUI listo.")
                return
            time.sleep(2)
        raise RuntimeError(
            f"ComfyUI no respondió en {startup_timeout}s; revisa {COMFY_DIR / 'comfyui.log'}"
        )
    finally:
        if spawned:
            lock.unlink(missing_ok=True)


def run_workflow(server: str, workflow: dict[str, Any], timeout: int = 600) -> bytes:
    """Encola el workflow y devuelve la primera imagen resultante."""
    return run_workflow_all(server, workflow, timeout=timeout)[0]


def run_workflow_all(
    server: str, workflow: dict[str, Any], timeout: int = 600
) -> list[bytes]:
    """Encola el workflow, espera y devuelve TODAS las imágenes (PNG en bytes)
    del nodo `save`.

    Un workflow de video devuelve cada frame como una imagen del batch."""
    entry = _run_and_wait(server, workflow, timeout)
    images = entry.get("outputs", {}).get("save", {}).get("images", [])
    if not images:
        raise RuntimeError("ComfyUI terminó el workflow sin devolver ninguna imagen")
    return [_download(server, info) for info in images]


def run_workflow_files(
    server: str, workflow: dict[str, Any], timeout: int = 600
) -> dict[str, list[tuple[str, bytes]]]:
    """Como run_workflow_all, pero devuelve los archivos de TODOS los nodos de
    salida: {id del nodo: [(nombre, bytes), ...]}.

    Lo necesitan los grafos con más de una salida o con salidas que no son
    imágenes, como el GLB de SaveGLB (que llega bajo la clave "3d"). Se acepta
    cualquier lista de ficheros, sea cual sea su clave, porque la v0.40 de
    ComfyUI cambió el formato de las salidas 3D."""
    entry = _run_and_wait(server, workflow, timeout)
    result: dict[str, list[tuple[str, bytes]]] = {}
    for node_id, outputs in entry.get("outputs", {}).items():
        for items in outputs.values():
            if not isinstance(items, list):
                continue
            for info in items:
                if isinstance(info, dict) and info.get("filename"):
                    result.setdefault(node_id, []).append(
                        (info["filename"], _download(server, info)))
    return result


def _download(server: str, info: dict[str, Any]) -> bytes:
    """Baja un archivo de salida de ComfyUI (imagen, GLB...) por /view."""
    resp = requests.get(
        f"{server}/view",
        params={
            "filename": info["filename"],
            "subfolder": info.get("subfolder", ""),
            "type": info.get("type", "output"),
        },
        timeout=120,
    )
    resp.raise_for_status()
    return resp.content


def _run_and_wait(server: str, workflow: dict[str, Any], timeout: int) -> dict[str, Any]:
    """Encola el workflow y espera a que ComfyUI lo dé por terminado.

    Devuelve su entrada de /history. ComfyUI solo escribe esa entrada al
    acabar la ejecución, así que su aparición ya significa «terminado»."""
    try:
        resp = requests.post(
            f"{server}/prompt",
            # El client_id DEBE coincidir con el del WebSocket de livefeed:
            # ComfyUI dirige progress y previews solo al socket de ese id
            json={"prompt": workflow, "client_id": livefeed.CLIENT_ID},
            timeout=30,
        )
    except requests.RequestException as exc:
        raise RuntimeError(f"No se pudo contactar a ComfyUI en {server}: {exc}") from exc
    if not resp.ok:
        raise RuntimeError(f"ComfyUI rechazó el workflow: {resp.text[:800]}")
    prompt_id = resp.json()["prompt_id"]

    deadline = time.time() + timeout
    polls = 0
    poll_failures = 0
    job_missing = False
    # livefeed solo informa (paso de muestreo y preview para la GUI); quien
    # decide cuándo terminó el trabajo sigue siendo el polling de abajo
    with livefeed.watching(server, prompt_id):
        while time.time() < deadline:
            try:
                history = requests.get(f"{server}/history/{prompt_id}", timeout=30).json()
                poll_failures = 0
            except requests.RequestException as exc:
                # Un hiccup transitorio no debe abandonar el trabajo; si la
                # conexión no vuelve, se cancela para no dejarlo huérfano en la GPU
                poll_failures += 1
                if poll_failures >= 3:
                    _cancel_job(server, prompt_id)
                    raise RuntimeError(
                        "Se perdió la conexión con ComfyUI a mitad de la generación "
                        f"({exc}). Revisa {COMFY_DIR / 'comfyui.log'}"
                    ) from exc
                time.sleep(1.5)
                continue
            entry = history.get(prompt_id)
            if entry:
                status = entry.get("status", {})
                if status.get("status_str") == "error":
                    raise RuntimeError(f"Error ejecutando el workflow: {_error_text(status)}")
                return entry
            # Cada ~12 s se comprueba que el trabajo siga en cola: si ComfyUI se
            # reinició a mitad, el historial quedaría vacío para siempre
            polls += 1
            if polls % 8 == 0 and not entry:
                if not _job_pending(server, prompt_id):
                    if job_missing:  # segunda comprobación consecutiva sin rastro
                        raise RuntimeError(
                            "ComfyUI perdió el trabajo (¿se reinició el motor a "
                            "mitad de la generación?). Vuelve a intentarlo."
                        )
                    job_missing = True
                else:
                    job_missing = False
            time.sleep(1.5)
        _cancel_job(server, prompt_id)
        raise RuntimeError(f"La generación superó el tiempo máximo ({timeout}s)")


def _error_text(status: dict[str, Any]) -> str:
    """El error legible de un workflow fallido: nodo y mensaje de la excepción
    (p. ej. un OOM de RemeshMesh), en vez de volcar toda la lista de mensajes."""
    messages = status.get("messages", [])
    for msg in messages:
        if not (isinstance(msg, (list, tuple)) and len(msg) == 2):
            continue
        kind, data = msg
        if kind == "execution_error" and isinstance(data, dict):
            texto = str(data.get("exception_message", "")).strip().splitlines()
            return f"{data.get('node_type', '?')}: {' '.join(texto[:3])[:600]}"
    return json.dumps(messages)[:1200]


# Familias de modelos pesados que no conviene tener a la vez en la RAM: los
# dos expertos de Wan ocupan ~21 GB y TRELLIS.2 ~9 GB, y lo que decide el
# tiempo de una generación es la RAM libre (gotcha 11c)
_FAMILY = {"current": None}


def free_models(server: str) -> None:
    """Pide a ComfyUI que descargue los modelos y libere su memoria. Nunca lanza."""
    try:
        requests.post(f"{server}/free",
                      json={"unload_models": True, "free_memory": True}, timeout=30)
    except requests.RequestException:
        pass


def switch_family(server: str, family: str) -> None:
    """Libera la memoria de ComfyUI al pasar de una familia pesada a otra
    (vídeo ↔ 3D). Repetir la misma familia no libera nada: así el segundo
    modelo 3D seguido no recarga los pesos."""
    previous = _FAMILY["current"]
    _FAMILY["current"] = family
    if previous is not None and previous != family:
        print(f"Cambio de familia de modelos ({previous} → {family}): liberando memoria de ComfyUI...")
        free_models(server)


def _job_pending(server: str, prompt_id: str) -> bool:
    """¿Sigue el trabajo en la cola de ComfyUI (ejecutándose o pendiente)?"""
    try:
        queue = requests.get(f"{server}/queue", timeout=15).json()
    except requests.RequestException:
        return True  # ante la duda, seguir esperando: el poll ya vigila la conexión
    for key in ("queue_running", "queue_pending"):
        for item in queue.get(key, []):
            if len(item) > 1 and item[1] == prompt_id:
                return True
    return False


def _cancel_job(server: str, prompt_id: str) -> None:
    """Cancela un trabajo huérfano para que no siga ocupando la GPU."""
    try:
        requests.post(f"{server}/queue", json={"delete": [prompt_id]}, timeout=15)
        requests.post(f"{server}/interrupt", timeout=15)
    except requests.RequestException:
        pass


@dataclass
class GenerationResult:
    subject: str
    seed: int
    raw: Path
    sprite: Path | None


def slugify(text: str, maxlen: int = 40) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
    return slug[:maxlen] or "sprite"


def generate_sprite(
    subject: str,
    seed: int | None = None,
    server: str = DEFAULT_SERVER,
    keep_bg: bool = False,
    raw_only: bool = False,
    native: int = 192,
    scale: int = 6,
    colors: int | None = 32,
    palette: list[tuple[int, int, int]] | None = None,
    method: str | None = None,
    clean: bool = True,
    steps: int | None = None,
    cfg_scale: float | None = None,
    engine_id: str | None = None,
    raw_prompt: bool = False,
) -> GenerationResult:
    """Pipeline completo: prompt -> motor elegido -> fondo/sombra -> pixelizador.

    raw_prompt: envía la descripción TAL CUAL, sin la plantilla de estilo ni
    el negative prompt globales (imágenes libres, no necesariamente sprites)."""
    cfg = load_config()
    engine = eng.get_engine(engine_id)
    eng.require_installed(engine)
    eff_steps = steps or engine["params"]["steps"]
    eff_cfg = cfg_scale if cfg_scale is not None else engine["params"]["cfg"]
    cfg["steps"], cfg["cfg"] = eff_steps, eff_cfg  # para los metadatos
    seed = seed if seed is not None else random.randrange(2**31)

    ensure_server(server)
    if raw_prompt:
        prompt, negative = subject, ""
    else:
        prompt = cfg["prompt_template"].replace("{subject}", subject)
        negative = cfg["negative_prompt"]
    print(f"Generando '{subject}' con {engine['label']} (seed {seed}, {eff_steps} pasos)...")
    png = run_workflow(
        server,
        eng.build_image_graph(
            engine, prompt, negative, seed,
            steps=steps, cfg=cfg_scale,
        ),
    )

    return finalize_generation(
        png, subject=subject, seed=seed, engine_id=engine["id"],
        native=native, scale=scale, colors=colors, palette=palette,
        method=method, clean=clean, keep_bg=keep_bg, raw_only=raw_only,
        steps=eff_steps, cfg_val=eff_cfg, raw_prompt=raw_prompt,
    )


def finalize_generation(
    png: bytes,
    *,
    subject: str,
    seed: int,
    engine_id: str,
    native: int = 192,
    scale: int = 6,
    colors: int | None = 32,
    palette: list[tuple[int, int, int]] | None = None,
    method: str | None = None,
    clean: bool = True,
    keep_bg: bool = False,
    raw_only: bool = False,
    steps: int = 0,
    cfg_val: float = 0.0,
    raw_prompt: bool = False,
) -> GenerationResult:
    """Segunda mitad del pipeline: raw -> fondo/sombra -> pixelizado -> historial."""
    cfg = load_config()
    if method is None:
        # Cada motor declara su reducción: "nearest" conserva los pseudo-píxeles
        # de SDXL+LoRA; "box" limpia mejor las salidas suaves (Klein, Z-Image)
        try:
            method = eng.get_engine(engine_id)["params"].get("pixelize_method", "nearest")
        except ValueError:
            method = "nearest"
    raw_dir = PROJECT_ROOT / "output" / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    meta_dir = PROJECT_ROOT / "output" / "meta"
    meta_dir.mkdir(parents=True, exist_ok=True)
    # Nombre único: repetir subject+seed (p. ej. con otros colores) no debe
    # sobreescribir la versión anterior en silencio
    stem = unique_stem(meta_dir, f"{slugify(subject)}_{seed}")
    raw_path = raw_dir / f"{stem}.png"
    raw_path.write_bytes(png)
    print(f"Imagen cruda: {raw_path}")

    img = Image.open(raw_path)
    if not keep_bg:
        img = remove_flat_background(
            img, threshold=cfg.get("bg_removal_threshold", 60)
        )
        if cfg.get("remove_shadow", True):
            img = remove_soft_shadow(img)

    out: Path | None = None
    if not raw_only:
        result = pixelize(
            img,
            native=native,
            scale=scale,
            colors=colors,
            palette=palette,
            method=method,
            clean=clean,
        )
        if not keep_bg and cfg.get("remove_shadow", True):
            result = strip_shadow_result(result, scale)
        out = PROJECT_ROOT / "output" / f"{stem}.png"
        result.final.save(out)
        print(f"Sprite final: {out} ({result.final.size[0]}x{result.final.size[1]} px)")

    meta = {
        "subject": subject,
        "engine": engine_id,
        "seed": seed,
        "raw": raw_path.name,
        "sprite": out.name if out else None,
        "native": native,
        "scale": scale,
        "colors": colors,
        "method": method,
        "used_palette": palette is not None,
        "raw_prompt": raw_prompt,
        "steps": steps,
        "cfg": cfg_val,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    (meta_dir / f"{stem}.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return GenerationResult(subject=subject, seed=seed, raw=raw_path, sprite=out)

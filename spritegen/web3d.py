"""Versión web de los modelos 3D: un GLB ligero para escenas de Three.js.

El GLB que sale de TRELLIS.2 es el «maestro»: texturas PNG de 1024–2048 px y
geometría sin comprimir (5–25 MB). Para la web se pasa por `gltf-transform
optimize` (Node, instalado en tools/gltf con `npm install`), que simplifica la
malla dentro de una tolerancia, comprime la geometría con meshopt y convierte
las texturas a WebP a un tamaño máximo. Medido: castillo 5,4 → 1,1 MB (web) /
0,5 MB (ligera); casa 22,9 → 2,9 / 1,5 MB, en uno o dos segundos.

La versión web lleva las extensiones EXT_meshopt_compression,
EXT_texture_webp y KHR_mesh_quantization: Three.js las lee con GLTFLoader
más MeshoptDecoder. Para importar en un motor de juego conviene el GLB
maestro, que no depende de ninguna extensión.

Cada calidad se guarda como `output/models/<stem>_<calidad>.glb` y queda
apuntada en la ficha del modelo, en `web[<calidad>]`.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import time
from pathlib import Path

from spritegen.generate import PROJECT_ROOT
from spritegen.model3d import META_DIR, MODELS_DIR, glb_stats
from spritegen.ocultos import set_os_hidden, write_meta_file

GLTF_DIR = PROJECT_ROOT / "tools" / "gltf"
CLI_JS = GLTF_DIR / "node_modules" / "@gltf-transform" / "cli" / "bin" / "cli.js"

# simplify-error: tolerancia como fracción del tamaño del modelo. Con la de
# por defecto (0,0001) apenas se quitan caras; la versión ligera pide además
# quedarse con un cuarto de los vértices si el error lo permite
PRESETS = {
    "web": {
        "label": "Web · texturas de 1024 px",
        "args": ["--compress", "meshopt", "--texture-compress", "webp",
                 "--texture-size", "1024"],
    },
    "ligero": {
        "label": "Ligera · texturas de 512 px y la mitad de caras",
        "args": ["--compress", "meshopt", "--texture-compress", "webp",
                 "--texture-size", "512", "--simplify-ratio", "0.25",
                 "--simplify-error", "0.002"],
    },
}


def _herramienta() -> list[str]:
    node = shutil.which("node")
    if not node:
        raise RuntimeError("Falta Node.js (https://nodejs.org): gltf-transform corre sobre él")
    if not CLI_JS.exists():
        raise RuntimeError(
            "Falta gltf-transform: ejecuta `npm install` dentro de tools\\gltf "
            "(conviene apuntar la caché de npm a otro disco si C: va justo)"
        )
    return [node, str(CLI_JS)]


def web_version(stem: str, preset: str = "web") -> dict:
    """Crea (o reutiliza) la versión web de un modelo y la apunta en su ficha.
    Devuelve la ficha actualizada."""
    if preset not in PRESETS:
        raise ValueError(f"Calidad web desconocida '{preset}'. Disponibles: {', '.join(PRESETS)}")
    ficha = META_DIR / f"{Path(stem).name}.json"
    if not ficha.exists():
        raise ValueError("No se encontró el modelo 3D")
    meta = json.loads(ficha.read_text(encoding="utf-8"))
    if meta.get("kind") != "model3d" or not meta.get("model"):
        raise ValueError("Esta operación solo aplica a modelos 3D")
    origen = MODELS_DIR / meta["model"]
    if not origen.exists():
        raise ValueError(f"Falta el GLB del modelo: {origen.name}")

    destino = MODELS_DIR / f"{ficha.stem}_{preset}.glb"
    previa = (meta.get("web") or {}).get(preset)
    # La salida es determinista: si ya existe, rehacerla daría el mismo archivo
    if previa and (MODELS_DIR / previa["file"]).exists():
        return meta

    temporal = destino.with_name(destino.stem + ".tmp.glb")
    t0 = time.time()
    proc = subprocess.run(
        _herramienta() + ["optimize", str(origen), str(temporal)] + PRESETS[preset]["args"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600,
    )
    if proc.returncode != 0 or not temporal.exists():
        temporal.unlink(missing_ok=True)
        salida = (proc.stderr or proc.stdout or "").strip().splitlines()
        raise RuntimeError("gltf-transform falló: " + (" ".join(salida[-3:]) or "sin mensaje"))
    temporal.replace(destino)
    datos = destino.read_bytes()
    stats = glb_stats(datos)
    meta.setdefault("web", {})[preset] = {
        "file": destino.name,
        "mb": round(len(datos) / 2**20, 2),
        "faces": stats["triangles"],
        "texture": max(stats["textures"], default=0),
        "seconds": round(time.time() - t0, 1),
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    write_meta_file(ficha, meta)
    if meta.get("hidden"):
        set_os_hidden(destino, True)   # lo derivado de un oculto nace oculto
    print(f"Versión {preset}: output/models/{destino.name} · {meta['web'][preset]['mb']} MB, "
          f"{stats['triangles']} triángulos (el maestro pesa {origen.stat().st_size / 2**20:.2f} MB)")
    return meta

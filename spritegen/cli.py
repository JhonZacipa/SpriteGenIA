from __future__ import annotations

import argparse
import glob
import sys
from pathlib import Path

from PIL import Image

from spritegen.palette import extract_palette, load_palette, save_palette
from spritegen.pixelize import count_colors, pixelize
from spritegen.sheet import make_sheet


def _cmd_generate(args: argparse.Namespace) -> None:
    # Import perezoso: requiere `requests` y solo aplica con ComfyUI instalado
    from spritegen.generate import generate_sprite

    palette = load_palette(args.palette) if args.palette else None
    generate_sprite(
        args.subject,
        seed=args.seed,
        server=args.server,
        keep_bg=args.keep_bg,
        raw_only=args.raw_only,
        native=args.native,
        scale=args.scale,
        colors=args.colors,
        palette=palette,
        method=args.method,
        clean=args.clean,
        steps=args.steps,
        cfg_scale=args.cfg,
        engine_id=args.engine,
        raw_prompt=args.raw_prompt,
    )


def _cmd_animate(args: argparse.Namespace) -> None:
    from spritegen.animate import animate_sprite

    palette = load_palette(args.palette) if args.palette else None
    animate_sprite(
        args.subject,
        anim=args.anim,
        seed=args.seed,
        base=args.base,
        denoise=args.denoise,
        native=args.native,
        scale=args.scale,
        colors=args.colors,
        palette=palette,
        cn_strength=args.cn_strength,
        steps=args.steps,
        cfg_scale=args.cfg,
        server=args.server,
    )


def _cmd_effect(args: argparse.Namespace) -> None:
    from spritegen.effects import (
        export_effect,
        flame_frames,
        make_cloth,
        smoke_frames,
        sway_frames,
        wave_frames,
    )

    if args.type == "sway":
        if not args.input:
            raise SystemExit("El efecto sway requiere --input <sprite de árbol/arbusto>")
        img = Image.open(args.input)
        if args.in_scale > 1:
            img = img.resize(
                (img.width // args.in_scale, img.height // args.in_scale),
                Image.Resampling.NEAREST,
            )
        frames = sway_frames(img, frames=args.frames or 6, amplitude=args.amplitude)
        export_effect(frames, name="sway", fps=6, scale=args.scale,
                      subject=f"{Path(args.input).stem} mecido por el viento")
    elif args.type == "flame":
        frames = flame_frames(args.kind, size=args.size, frames=args.frames or 6)
        export_effect(frames, name=f"flame_{args.kind}", fps=10, scale=args.scale,
                      subject=f"fuego ({args.kind})")
    elif args.type == "wave":
        if args.input:
            img = Image.open(args.input)
            if args.in_scale > 1:
                img = img.resize(
                    (img.width // args.in_scale, img.height // args.in_scale),
                    Image.Resampling.NEAREST,
                )
            subject = f"{Path(args.input).stem} ondeando"
        else:
            img = make_cloth(args.width, args.height, args.color, args.color2)
            subject = f"bandera {args.color} ondeando"
        frames = wave_frames(img, frames=args.frames or 8,
                             amplitude=args.amplitude, anchor=args.anchor)
        export_effect(frames, name="wave", fps=8, scale=args.scale, subject=subject)
    elif args.type == "smoke":
        frames = smoke_frames(width=max(16, args.size // 2), height=args.size,
                              frames=args.frames or 8)
        export_effect(frames, name="smoke", fps=8, scale=args.scale,
                      subject="humo de chimenea")


def _cmd_engines(args: argparse.Namespace) -> None:
    from spritegen.engines import list_engines

    for e in list_engines():
        estado = "✔ instalado" if e["installed"] else f"✘ faltan: {', '.join(e['missing'])}"
        marca = " (defecto)" if e["default"] else ""
        print(f"{e['id']:<16} [{e['kind']}] {e['label']}{marca} — {estado}")


def _base_de_video(entrada: str | None, continuar: str | None) -> dict:
    """De dónde arranca un clip en la CLI: una imagen (`--input`) o el último
    frame de un clip ya generado (`--continue-from`). Espeja lo que hace
    `_resolve_video_base` en el servidor."""
    import json

    from spritegen.effects import list_frames
    from spritegen.generate import PROJECT_ROOT

    if continuar:
        stem = Path(continuar).stem
        frames = list_frames(PROJECT_ROOT / "output" / "frames" / stem)
        if not frames:
            raise SystemExit(f"El clip '{stem}' no conserva frames en output/frames")
        sujeto = stem
        segments = None
        meta_path = PROJECT_ROOT / "output" / "meta" / f"{stem}.json"
        if meta_path.exists():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            segments = meta.get("segments")
            sujeto = meta.get("subject") or stem
        return {"raw": frames[-1], "subject": sujeto, "prev_frames": frames,
                "prev_segments": segments, "parent_id": stem, "encadena": True}
    if not entrada:
        raise SystemExit("Indica --input (imagen base) o --continue-from (clip a continuar)")
    ruta = Path(entrada)
    return {"raw": ruta, "subject": ruta.stem, "prev_frames": None,
            "prev_segments": None, "parent_id": None, "encadena": False}


def _cmd_animate_video(args: argparse.Namespace) -> None:
    from spritegen.animate_video import animate_video_sprite

    palette = load_palette(args.palette) if args.palette else None
    base = _base_de_video(args.input, args.continue_from)
    if base["encadena"] and args.engine == "wan22_14b_pixel":
        args.engine = "wan22_14b_free"
    entrada, sujeto = base["raw"], base["subject"]
    prev_frames = base["prev_frames"]
    prev_segments = base["prev_segments"]
    parent_id = base["parent_id"]

    animate_video_sprite(
        args.motion,
        base_raw=entrada,
        base_subject=sujeto,
        prev_frames=prev_frames,
        prev_segments=prev_segments,
        parent_id=parent_id,
        frames_out=args.frames,
        seed=args.seed,
        native=args.native,
        scale=args.scale,
        colors=args.colors,
        palette=palette,
        engine_id=args.engine,
        cycle_seconds=args.cycle,
        length=args.length,
        server=args.server,
    )


def _cmd_animate_queue(args: argparse.Namespace) -> None:
    """Cola de clips: cada prompt genera un tramo que continúa al anterior.

    Secuencial por construcción: `animate_video_sprite` no retorna hasta que el
    clip está escrito, así que el siguiente siempre encuentra sus frames."""
    from spritegen.animate_video import animate_video_sprite

    actual_input, actual_continue = args.input, args.continue_from
    total = len(args.prompts)
    hechos = []
    for i, prompt in enumerate(args.prompts, 1):
        base = _base_de_video(actual_input, actual_continue)
        engine = args.engine
        if base["encadena"] and engine == "wan22_14b_pixel":
            engine = "wan22_14b_free"
        print(f"\n=== Clip {i}/{total}: {prompt} ===")
        gif = animate_video_sprite(
            prompt,
            base_raw=base["raw"],
            base_subject=base["subject"],
            prev_frames=base["prev_frames"],
            prev_segments=base["prev_segments"],
            parent_id=base["parent_id"],
            seed=args.seed,
            engine_id=engine,
            cycle_seconds=args.cycle,
            length=args.length,
            server=args.server,
        )
        hechos.append(gif)
        # El clip recién creado es la base del siguiente tramo
        actual_input, actual_continue = None, gif.stem
    print(f"\nCola terminada: {len(hechos)} clips. Resultado final: {hechos[-1]}")


def _cmd_terrain(args: argparse.Namespace) -> None:
    from spritegen.terrain import generate_terrain

    generate_terrain(
        args.subject,
        seed=args.seed,
        variants=args.variants,
        colors=args.colors,
        server=args.server,
    )


def _cmd_tileset(args: argparse.Namespace) -> None:
    from spritegen.terrain import build_tileset

    build_tileset(args.terrain_a, args.terrain_b, name=args.name)


def _cmd_pixelize(args: argparse.Namespace) -> None:
    img = Image.open(args.input)
    if args.remove_bg is not None:
        from spritegen.background import remove_flat_background

        img = remove_flat_background(img, threshold=args.remove_bg)
    if getattr(args, "remove_shadow", False):
        from spritegen.background import remove_soft_shadow

        img = remove_soft_shadow(img)
    palette = load_palette(args.palette) if args.palette else None
    result = pixelize(
        img,
        native=args.native,
        scale=args.scale,
        colors=args.colors,
        palette=palette,
        method=args.method,
        dither=args.dither,
        clean=args.clean,
    )
    if getattr(args, "remove_shadow", False):
        from spritegen.background import strip_shadow_result

        result = strip_shadow_result(result, args.scale)
    out = Path(args.output) if args.output else Path(args.input).with_name(
        Path(args.input).stem + "_px.png"
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    result.final.save(out)
    print(f"Sprite: {out}")
    print(f"  Rejilla nativa : {result.native.size[0]}x{result.native.size[1]} px")
    print(f"  Tamaño final   : {result.final.size[0]}x{result.final.size[1]} px (x{args.scale})")
    print(f"  Colores        : {count_colors(result.native)}")
    if args.save_native:
        native_out = out.with_name(out.stem + "_nativo.png")
        result.native.save(native_out)
        print(f"  Versión nativa : {native_out}")


def _cmd_extract_palette(args: argparse.Namespace) -> None:
    colors = extract_palette(Image.open(args.input), n=args.n)
    save_palette(args.output, colors)
    print(f"Paleta de {len(colors)} colores guardada en {args.output}")


def _cmd_sheet(args: argparse.Namespace) -> None:
    # PowerShell no expande comodines para procesos externos: se hace aquí
    paths: list[str] = []
    for pattern in args.inputs:
        matches = sorted(glob.glob(pattern))
        if not matches:
            if any(c in pattern for c in "*?["):
                raise SystemExit(f"El patrón '{pattern}' no encontró ningún archivo")
            matches = [pattern]
        paths.extend(matches)
    sheet = make_sheet(paths, cols=args.cols)
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    sheet.save(args.output)
    print(f"Sprite sheet de {len(paths)} frames ({sheet.size[0]}x{sheet.size[1]} px): {args.output}")


def _console_utf8() -> None:
    """La consola de Windows no siempre habla UTF-8: `cmd` arranca en cp850/1252
    y, al redirigir la salida a un pipe o a un archivo, Python usa la
    codificación del sistema. Sin esto, imprimir los ✔/✘ del listado de motores
    revienta con UnicodeEncodeError en un equipo recién instalado."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError, ValueError):
            pass  # salida ya redirigida a algo que no admite reconfigurarse


def main() -> None:
    _console_utf8()
    parser = argparse.ArgumentParser(
        prog="spritegen",
        description="Generador de sprites pixel art: pixelización, paletas y sprite sheets.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("generate", help="Generar un sprite desde un prompt (ComfyUI + LoRA pixel art)")
    p.add_argument("subject", help='Descripción del sprite, ej: "casa medieval con tejado de paja"')
    p.add_argument("--engine", help="Motor: sdxl_pixelart, zimage_turbo, klein4b (def. según config/motores.json)")
    p.add_argument("--seed", type=int, help="Semilla fija para reproducir un resultado")
    p.add_argument("--server", default="http://127.0.0.1:8188", help="URL del servidor ComfyUI")
    p.add_argument("--steps", type=int, help="Pasos de muestreo (def. según el motor)")
    p.add_argument("--cfg", type=float, help="Guidance scale (def. según el motor)")
    p.add_argument("--keep-bg", action="store_true", help="No quitar el fondo chroma")
    p.add_argument("--raw-only", action="store_true", help="Solo la imagen cruda, sin pixelizar")
    p.add_argument("--native", type=int, default=192, help="Rejilla real del sprite (def. 192)")
    p.add_argument("--scale", type=int, default=6, help="Reescalado nítido (def. 6)")
    p.add_argument("--colors", type=int, default=32, help="Colores de la cuantización (def. 32)")
    p.add_argument("--palette", help="Paleta fija del proyecto (prioridad sobre --colors)")
    p.add_argument("--method", choices=["box", "lanczos", "nearest"], default=None,
                   help="Reducción a rejilla (def. según el motor: nearest en SDXL, box en Klein/Z-Image)")
    p.add_argument("--raw-prompt", action="store_true", dest="raw_prompt",
                   help="Enviar la descripción TAL CUAL (sin plantilla de estilo ni negative)")
    p.add_argument("--clean", action=argparse.BooleanOptionalAction, default=True,
                   help="Limpieza de píxeles sueltos (def. activada; --no-clean para omitir)")
    p.set_defaults(func=_cmd_generate)

    p = sub.add_parser("animate", help="Generar un ciclo de animación (frames + sprite sheet + GIF)")
    p.add_argument("subject", help='Descripción del personaje, ej: "orc warrior, full body, side view"')
    p.add_argument("--anim", default="walk",
                   help="Ciclo: walk (8 frames), idle (4) o el nombre de una carpeta propia en assets/poses/")
    p.add_argument("--seed", type=int, help="Semilla fija compartida por todos los frames")
    p.add_argument("--base", help="Imagen base (raw) para conservar la identidad vía img2img")
    p.add_argument("--denoise", type=float, default=0.85,
                   help="Con --base: libertad de movimiento (0.3 fiel/estático, 0.95 libre; def. 0.85)")
    p.add_argument("--cn-strength", type=float, default=1.0, dest="cn_strength",
                   help="Fuerza del esqueleto de pose (def. 1.0)")
    p.add_argument("--native", type=int, default=128, help="Rejilla real por frame (def. 128)")
    p.add_argument("--scale", type=int, default=6, help="Reescalado nítido (def. 6)")
    p.add_argument("--colors", type=int, default=32, help="Colores (def. 32; el frame 1 fija la paleta del ciclo)")
    p.add_argument("--palette", help="Paleta fija del proyecto")
    p.add_argument("--steps", type=int, help="Pasos de muestreo")
    p.add_argument("--cfg", type=float, help="Guidance scale")
    p.add_argument("--server", default="http://127.0.0.1:8188", help="URL del servidor ComfyUI")
    p.set_defaults(func=_cmd_animate)

    p = sub.add_parser("engines", help="Listar los motores de generación y su estado")
    p.set_defaults(func=_cmd_engines)

    p = sub.add_parser("animate-video", help="Ciclo de animación por video (Wan 2.2, identidad perfecta)")
    p.add_argument("motion", help='Movimiento, ej: "walk cycle" / "idle breathing" / "attack slash"')
    p.add_argument("--input", help="Imagen base (el raw del sprite)")
    p.add_argument("--continue-from", dest="continue_from",
                   help="Id de un clip de video libre: lo continúa desde su último frame "
                        "y guarda la unión como entrada nueva")
    p.add_argument("--frames", type=int, default=8, help="Frames a extraer del video (def. 8)")
    p.add_argument("--seed", type=int, help="Semilla fija")
    p.add_argument("--native", type=int, default=128, help="Rejilla real por frame (def. 128)")
    p.add_argument("--scale", type=int, default=6, help="Reescalado nítido (def. 6)")
    p.add_argument("--colors", type=int, default=32, help="Colores (def. 32)")
    p.add_argument("--palette", help="Paleta fija del proyecto")
    p.add_argument("--engine", default="wan22_14b_pixel",
                   help="Motor de video (ver `engines`): wan22_14b_pixel | wan22_14b_free | wan22_5b")
    p.add_argument("--cycle", type=float, default=None,
                   help="Segundos de la zancada a muestrear (def. 0.8); 0 = todo el clip")
    p.add_argument("--length", type=int, default=None,
                   help="Frames del clip, 4n+1 (49=3,1s · 81=5,1s · 121=7,6s a 16 fps)")
    p.add_argument("--server", default="http://127.0.0.1:8188", help="URL del servidor ComfyUI")
    p.set_defaults(func=_cmd_animate_video)

    p = sub.add_parser("animate-queue",
                       help="Cola de clips: varios prompts que se generan y encadenan solos")
    p.add_argument("prompts", nargs="+",
                   help='Un prompt por clip, en orden: "she turns" "she smiles" ...')
    p.add_argument("--input", help="Imagen base del primer clip")
    p.add_argument("--continue-from", dest="continue_from",
                   help="Id de un clip existente: la cola arranca continuándolo")
    p.add_argument("--engine", default="wan22_14b_free", help="Motor de video para toda la cola")
    p.add_argument("--length", type=int, default=None,
                   help="Frames por clip, 4n+1 (81 = 5,1 s a 16 fps)")
    p.add_argument("--cycle", type=float, default=0,
                   help="0 (def.) = clip completo, lo normal en video libre")
    p.add_argument("--seed", type=int, help="Semilla fija para todos los clips")
    p.add_argument("--server", default="http://127.0.0.1:8188", help="URL del servidor ComfyUI")
    p.set_defaults(func=_cmd_animate_queue)

    p = sub.add_parser("terrain", help="Generar un terreno: variantes de tile seamless de 64px")
    p.add_argument("subject", help='Textura, ej: "dense green grass" o "dry dirt ground"')
    p.add_argument("--seed", type=int, help="Semilla fija")
    p.add_argument("--variants", type=int, default=4, help="Variantes de tile a extraer (def. 4)")
    p.add_argument("--colors", type=int, default=16, help="Colores del terreno (def. 16)")
    p.add_argument("--server", default="http://127.0.0.1:8188", help="URL del servidor ComfyUI")
    p.set_defaults(func=_cmd_terrain)

    p = sub.add_parser("tileset", help="Combinar dos terrenos: 16 transiciones + tileset + mapa demo")
    p.add_argument("terrain_a", help="Terreno dominante (carpeta en output/terrain/)")
    p.add_argument("terrain_b", help="Terreno secundario")
    p.add_argument("--name", help="Nombre del tileset (def. derivado de ambos)")
    p.set_defaults(func=_cmd_tileset)

    p = sub.add_parser("effect", help="Efectos ambientales procedurales (sin GPU, loop perfecto)")
    p.add_argument("type", choices=["sway", "flame", "wave", "smoke"],
                   help="sway: mecer vegetación · flame: fuego · wave: tela/bandera · smoke: humo")
    p.add_argument("--input", help="Sprite base (sway y wave)")
    p.add_argument("--in-scale", type=int, default=1, dest="in_scale",
                   help="Factor para reducir el sprite base a su rejilla nativa (ej. 6)")
    p.add_argument("--frames", type=int, help="Frames del ciclo (def. según efecto)")
    p.add_argument("--amplitude", type=int, help="Amplitud del movimiento en px nativos")
    p.add_argument("--scale", type=int, default=6, help="Reescalado nítido de salida (def. 6)")
    p.add_argument("--kind", choices=["torch", "campfire", "candle"], default="torch",
                   help="flame: tipo de fuego (def. torch)")
    p.add_argument("--size", type=int, default=64, help="flame/smoke: alto en px nativos (def. 64)")
    p.add_argument("--color", default="#B22222", help="wave sin --input: color de la tela")
    p.add_argument("--color2", help="wave: segunda franja opcional")
    p.add_argument("--width", type=int, default=96, help="wave: ancho de la tela (def. 96)")
    p.add_argument("--height", type=int, default=64, help="wave: alto de la tela (def. 64)")
    p.add_argument("--anchor", choices=["left", "top"], default="left",
                   help="wave: amarre al mástil (left) o colgante (top)")
    p.set_defaults(func=_cmd_effect)

    p = sub.add_parser("pixelize", help="Convertir una imagen en pixel art real")
    p.add_argument("input", help="Imagen de entrada (PNG/JPG/WebP...)")
    p.add_argument("-o", "--output", help="PNG de salida (por defecto <nombre>_px.png)")
    p.add_argument("--native", type=int, default=160, help="Lado mayor de la rejilla real (def. 160)")
    p.add_argument("--scale", type=int, default=6, help="Factor de reescalado nítido (def. 6)")
    p.add_argument("--colors", type=int, default=32, help="Cuantización automática a N colores (def. 32)")
    p.add_argument("--palette", help="Archivo de paleta fija (prioridad sobre --colors)")
    p.add_argument("--method", choices=["box", "lanczos", "nearest"], default="box",
                   help="Filtro de reducción (def. box; nearest si la fuente ya es pseudo-pixel-art)")
    p.add_argument("--dither", action="store_true", help="Tramado Floyd-Steinberg")
    p.add_argument("--clean", action="store_true", help="Eliminar píxeles sueltos")
    p.add_argument("--remove-bg", type=int, metavar="UMBRAL",
                   help="Quitar el fondo plano antes de pixelizar (umbral, ej. 60-100)")
    p.add_argument("--remove-shadow", action="store_true", dest="remove_shadow",
                   help="Quitar la sombra de contacto bajo el sujeto")
    p.add_argument("--save-native", action="store_true", help="Guardar también la versión nativa sin escalar")
    p.set_defaults(func=_cmd_pixelize)

    p = sub.add_parser("extract-palette", help="Extraer la paleta de un sprite aprobado")
    p.add_argument("input", help="Imagen de la que extraer colores")
    p.add_argument("-n", type=int, default=32, help="Número de colores (def. 32)")
    p.add_argument("-o", "--output", default="palettes/proyecto.txt", help="Archivo de paleta destino")
    p.set_defaults(func=_cmd_extract_palette)

    p = sub.add_parser("sheet", help="Unir frames en un sprite sheet")
    p.add_argument("inputs", nargs="+", help="Frames (admite comodines: frames/caminar_*.png)")
    p.add_argument("-o", "--output", required=True, help="PNG del sprite sheet")
    p.add_argument("--cols", type=int, help="Columnas (por defecto todos en una fila)")
    p.set_defaults(func=_cmd_sheet)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

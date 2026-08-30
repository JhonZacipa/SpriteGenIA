from __future__ import annotations

import numpy as np
from PIL import Image

Color = tuple[int, int, int]


def hex_to_rgb(value: str) -> Color:
    value = value.lstrip("#")
    return tuple(int(value[i : i + 2], 16) for i in (0, 2, 4))


def remove_flat_background(img: Image.Image, threshold: int = 60) -> Image.Image:
    """Vuelve transparente el fondo plano de un sprite generado.

    El color de fondo se estima con la mediana de un marco de 4 px del borde,
    y solo se eliminan los píxeles parecidos a él que estén CONECTADOS al
    borde (flood fill), de modo que ventanas u ojos del mismo color interior
    sobreviven.
    """
    rgba = np.asarray(img.convert("RGBA")).astype(np.int32).copy()
    rgb = rgba[..., :3]

    frame = np.concatenate(
        [
            rgb[:4].reshape(-1, 3),
            rgb[-4:].reshape(-1, 3),
            rgb[:, :4].reshape(-1, 3),
            rgb[:, -4:].reshape(-1, 3),
        ]
    )
    bg = np.median(frame, axis=0)

    diff = rgb - bg
    dist = np.sqrt((diff**2).sum(axis=-1))
    # Croma relativa al fondo: un píxel de fondo (o su anti-aliasing) se separa
    # del color de fondo por IGUAL en los tres canales; la piel u otros tonos
    # claros comparten distancia pero no neutralidad. Sin esta guarda el flood
    # se cuela en zonas cálidas claras (brazos) y las vacía por dentro.
    chroma = diff.max(axis=-1) - diff.min(axis=-1)
    candidate = (dist < threshold) & (chroma < max(14, threshold * 0.45))

    seeds = np.zeros_like(candidate)
    seeds[0, :] = seeds[-1, :] = seeds[:, 0] = seeds[:, -1] = True
    reach = _flood(seeds & candidate, candidate)

    rgba[reach, 3] = 0

    # Bolsas de fondo ENCERRADAS (entre un brazo en alto y la cabeza, bajo un
    # asa...): el flood desde el borde no las alcanza. Solo se borra un
    # componente si es prácticamente EXACTO al color de fondo (pureza media,
    # neutralidad y tamaño mínimo): ojos, dientes, ventanas o ropa clara del
    # sujeto llevan sombreado y no cumplen.
    pure = (
        (rgba[..., 3] > 0) & ~reach
        & (dist < min(24, threshold * 0.4)) & (chroma < 12)
    )
    if pure.any():
        h, w = pure.shape
        min_area = max(400, int(h * w * 0.002))
        for comp in _iter_components(pure, pure, max_components=16):
            if comp.sum() >= min_area and dist[comp].mean() < 10:
                rgba[comp, 3] = 0

    _erode_halo(
        rgba, dist, limit=threshold * 1.8,
        chroma=chroma, chroma_limit=max(18, threshold * 0.55),
    )
    return Image.fromarray(rgba.astype(np.uint8))


def remove_chroma(
    img: Image.Image, key: Color = (255, 0, 255), threshold: int = 95
) -> Image.Image:
    """Chroma key clásico contra un color fijo (fallback manual)."""
    rgba = np.asarray(img.convert("RGBA")).astype(np.int32).copy()
    key_arr = np.array(key, dtype=np.int32)
    dist = np.sqrt(((rgba[..., :3] - key_arr) ** 2).sum(axis=-1))
    rgba[dist < threshold, 3] = 0
    _erode_halo(rgba, dist, limit=threshold * 1.8)
    return Image.fromarray(rgba.astype(np.uint8))


def remove_debris(img: Image.Image, min_frac: float = 0.01) -> Image.Image:
    """Elimina islas opacas diminutas desconectadas del sujeto principal.

    Pensado para frames de video: Wan mancha el fondo blanco con motas cálidas
    que el flood (con guarda de croma) respeta, y quedan flotando alrededor del
    personaje. Se conserva todo componente >= min_frac del área del mayor, así
    que un efecto grande separado del cuerpo (un arco de ataque) sobrevive."""
    rgba = np.asarray(img.convert("RGBA")).copy()
    opaque = rgba[..., 3] > 0
    if not opaque.any():
        return img
    labels = np.zeros(opaque.shape, dtype=np.int32)
    n = 0
    while n < 128:
        remaining = opaque & (labels == 0)
        if not remaining.any():
            break
        sy, sx = np.argwhere(remaining)[0]
        seed = np.zeros_like(opaque)
        seed[sy, sx] = True
        n += 1
        labels[_flood(seed, opaque)] = n
    if n <= 1:
        return img
    areas = np.bincount(labels.ravel(), minlength=n + 1)
    keep_min = max(1, int(areas[1 : n + 1].max() * min_frac))
    kill = opaque & (labels == 0)  # si se superó el tope, el resto es morralla
    for i in range(1, n + 1):
        if areas[i] < keep_min:
            kill |= labels == i
    if not kill.any():
        return img
    rgba[kill] = 0
    return Image.fromarray(rgba)


def remove_soft_shadow(
    img: Image.Image, max_grad: int = 18, max_sat: int = 70
) -> Image.Image:
    """Elimina sombras difusas en la imagen cruda (alta resolución).

    La firma física de una sombra pintada por la IA es que es DIFUSA:
    gradiente local suave, sin los contornos duros del arte. Se marcan los
    píxeles suaves, poco saturados y de luminancia media de la mitad inferior
    que estén conectados al exterior: el flood se detiene en los contornos
    dibujados, así que no entra al objeto aunque la sombra lo toque.
    """
    rgba = np.asarray(img.convert("RGBA")).copy()
    h, w = rgba.shape[:2]
    opaque = rgba[..., 3] > 0
    if not opaque.any():
        return img
    rows = np.where(opaque.any(axis=1))[0]
    y_top, y_bottom = int(rows[0]), int(rows[-1])
    height = max(1, y_bottom - y_top)

    rgb = rgba[..., :3].astype(np.int16)
    lum = rgb.mean(axis=-1)
    sat = rgb.max(axis=-1) - rgb.min(axis=-1)
    # Gradiente solo entre pares de píxeles AMBOS visibles: la frontera con
    # el fondo ya borrado no debe contar como borde duro
    both_x = opaque[:, :-1] & opaque[:, 1:]
    both_y = opaque[:-1, :] & opaque[1:, :]
    gx = np.abs(np.diff(lum, axis=1)) * both_x
    gy = np.abs(np.diff(lum, axis=0)) * both_y
    grad = np.zeros_like(lum)
    grad[:, :-1] = np.maximum(grad[:, :-1], gx)
    grad[:, 1:] = np.maximum(grad[:, 1:], gx)
    grad[:-1, :] = np.maximum(grad[:-1, :], gy)
    grad[1:, :] = np.maximum(grad[1:, :], gy)

    ys = np.arange(h)[:, None]
    candidate = (
        opaque
        & (grad <= max_grad)
        & (sat <= max_sat)
        & (lum >= 60) & (lum <= 245)
        & (ys >= y_top + 0.5 * height)
    )
    if not candidate.any():
        return img

    transparent = ~opaque
    reach = _flood(candidate & _touching(transparent), candidate)
    if not reach.any():
        return img

    # Solo se borran componentes CHATAS (más anchas que altas): una sombra
    # siempre lo es; una hoja de espada o una pierna clara es vertical y
    # se conserva aunque el flood la haya alcanzado
    removed = False
    for comp in _iter_components(reach, reach, max_components=6):
        crows = np.where(comp.any(axis=1))[0]
        ccols = np.where(comp.any(axis=0))[0]
        comp_h = int(crows[-1] - crows[0] + 1)
        comp_w = int(ccols[-1] - ccols[0] + 1)
        if comp_w >= 1.4 * comp_h:
            rgba[comp] = 0
            removed = True
    return Image.fromarray(rgba) if removed else img


def remove_contact_shadow(img: Image.Image, max_sat: int = 36) -> Image.Image:
    """Elimina la sombra de contacto que la IA pinta bajo el sujeto.

    Una sombra de contacto cumple cuatro condiciones a la vez: es casi neutra
    (baja saturación), de luminancia media, está en la mitad inferior del
    contenido, y forma una mancha CHATA (mucho más ancha que alta) conectada
    al exterior que toca la base. Piezas grises del propio sujeto (botas,
    armaduras, piedras) fallan alguna de esas condiciones y se conservan.
    Devuelve la misma imagen si no encuentra nada que borrar.
    """
    rgba = np.asarray(img.convert("RGBA")).copy()
    h, w = rgba.shape[:2]
    opaque = rgba[..., 3] > 0
    if not opaque.any():
        return img
    rows = np.where(opaque.any(axis=1))[0]
    y_top, y_bottom = int(rows[0]), int(rows[-1])
    height = max(1, y_bottom - y_top)

    rgb = rgba[..., :3].astype(np.int16)
    sat = rgb.max(axis=-1) - rgb.min(axis=-1)
    lum = rgb.mean(axis=-1)
    ys = np.arange(h)[:, None]
    candidate = (
        opaque
        & (sat <= max_sat)
        & (lum >= 55) & (lum <= 235)
        & (ys >= y_top + 0.55 * height)
    )
    if not candidate.any():
        return img

    transparent = ~opaque
    seeds = candidate & _touching(transparent)

    removed = False
    # la sombra puede partirse en manchas (izq/der de los pies)
    for comp in _iter_components(seeds, candidate, max_components=8):
        crows = np.where(comp.any(axis=1))[0]
        ccols = np.where(comp.any(axis=0))[0]
        comp_h = int(crows[-1] - crows[0] + 1)
        comp_w = int(ccols[-1] - ccols[0] + 1)
        reaches_bottom = crows[-1] >= y_bottom - max(2, round(height * 0.05))
        if comp_w >= 2.2 * comp_h and reaches_bottom:
            rgba[comp] = 0
            removed = True

    # Regla B: sombra "flotante" bajo voladizos (aleros, copas, brazos).
    # En su columna, el ÚLTIMO segmento opaco es fino, está pegado al suelo
    # y hay un hueco transparente entre él y el contenido de arriba. Un pie
    # o una bota nunca cumple: conecta con la pierna sin hueco.
    opaque = rgba[..., 3] > 0
    max_seg = max(2, 0.11 * height)
    floor = y_bottom - max(2, round(height * 0.12))
    for x in range(w):
        idx = np.where(opaque[:, x])[0]
        if len(idx) < 2:
            continue
        breaks = np.where(np.diff(idx) > 1)[0]
        if len(breaks) == 0:
            continue  # un solo segmento: podría ser una puntera, se protege
        last_start = int(idx[breaks[-1] + 1])
        last_end = int(idx[-1])
        gap = last_start - int(idx[breaks[-1]]) - 1
        seg_h = last_end - last_start + 1
        if (
            seg_h <= max_seg
            and last_start >= y_top + 0.72 * height
            and last_end >= floor
            and gap >= 3
        ):
            seg = slice(last_start, last_end + 1)
            if sat[seg, x].mean() <= 60 and 55 <= lum[seg, x].mean() <= 238:
                rgba[seg, x] = 0
                removed = True

    # Pasada final: roer filamentos residuales de sombra en la zona baja
    # (píxeles color-sombra casi rodeados de vacío; una esquina legítima del
    # sprite tiene como mucho 5 vecinos vacíos, se exige 6)
    ys_grid = np.arange(h)[:, None]
    low_zone = ys_grid >= y_top + 0.72 * height
    shadow_color = (sat <= 60) & (lum >= 55) & (lum <= 238)
    for _ in range(3):
        opaque = rgba[..., 3] > 0
        empty = ~opaque
        neighbors = np.zeros((h, w), dtype=np.int16)
        for dy, dx in ((-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)):
            shifted = np.ones_like(empty)
            src = empty[
                max(0, -dy) : h - max(0, dy) or h,
                max(0, -dx) : w - max(0, dx) or w,
            ]
            shifted[
                max(0, dy) : h - max(0, -dy) or h,
                max(0, dx) : w - max(0, -dx) or w,
            ] = src
            neighbors += shifted
        gnaw = opaque & low_zone & shadow_color & (neighbors >= 6)
        if not gnaw.any():
            break
        rgba[gnaw] = 0
        removed = True

    return Image.fromarray(rgba) if removed else img


def strip_shadow_result(result, scale: int):
    """Aplica remove_contact_shadow al nativo de un PixelizeResult y
    reescala; devuelve el mismo result si no había sombra."""
    from spritegen.pixelize import PixelizeResult

    native = remove_contact_shadow(result.native)
    if native is result.native:
        return result
    final = native.resize(
        (native.width * scale, native.height * scale), Image.Resampling.NEAREST
    )
    return PixelizeResult(final=final, native=native)


def _erode_halo(
    rgba: np.ndarray,
    dist: np.ndarray,
    limit: float,
    chroma: np.ndarray | None = None,
    chroma_limit: float | None = None,
) -> None:
    """Recorta dos anillos de borde que sigan tirando al color de fondo,
    para reducir el halo del anti-aliasing. Modifica `rgba` in place.
    Con `chroma` solo roe píxeles aún neutros respecto al fondo (los blends
    del anti-aliasing), sin morder piel u otros tonos claros legítimos."""
    for _ in range(2):
        transparent = rgba[..., 3] == 0
        halo = ~transparent & _touching(transparent) & (dist < limit)
        if chroma is not None and chroma_limit is not None:
            halo &= chroma < chroma_limit
        rgba[halo, 3] = 0


def _flood(seeds: np.ndarray, allowed: np.ndarray) -> np.ndarray:
    """Flood fill vectorizado: expande `seeds` dentro de `allowed` (4 vecinos)
    por dilatación hasta estabilizar y devuelve la máscara alcanzada."""
    reach = seeds & allowed
    while True:
        grown = reach.copy()
        grown[1:, :] |= reach[:-1, :]
        grown[:-1, :] |= reach[1:, :]
        grown[:, 1:] |= reach[:, :-1]
        grown[:, :-1] |= reach[:, 1:]
        grown &= allowed
        if (grown == reach).all():
            return reach
        reach = grown


def _touching(mask: np.ndarray) -> np.ndarray:
    """Píxeles con algún vecino (4 conexos) dentro de `mask`."""
    near = np.zeros_like(mask)
    near[1:, :] |= mask[:-1, :]
    near[:-1, :] |= mask[1:, :]
    near[:, 1:] |= mask[:, :-1]
    near[:, :-1] |= mask[:, 1:]
    return near


def _iter_components(seeds: np.ndarray, allowed: np.ndarray, max_components: int):
    """Componentes conexas de `allowed` alcanzables desde `seeds`, de una en
    una (hasta max_components)."""
    visited = np.zeros_like(allowed)
    for _ in range(max_components):
        remaining = seeds & ~visited
        if not remaining.any():
            return
        sy, sx = np.argwhere(remaining)[0]
        comp = np.zeros_like(allowed)
        comp[sy, sx] = True
        comp = _flood(comp, allowed)
        visited |= comp
        yield comp

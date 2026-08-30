"""Esqueletos OpenPose procedurales para ciclos de animación.

El ControlNet OpenPose espera el render estándar: fondo negro, huesos como
segmentos gruesos y articulaciones como círculos, con la paleta canónica de
18 keypoints (formato BODY_18). Aquí se generan poses paramétricas sin
depender de packs externos: locomoción cíclica (senos/cosenos) y acciones
por keyframes.

Vistas: perfil (mirando a la derecha), frente (facing camera) y espalda.
En OpenPose frontal el lado DERECHO del sujeto queda a la IZQUIERDA de la
imagen; de espaldas coincide con la imagen, no hay nariz/ojos y sí orejas.
"""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw

ASSETS_DIR = Path(__file__).resolve().parents[1] / "assets" / "poses"

# Paleta canónica del render OpenPose
COLORS = [
    (255, 0, 0), (255, 85, 0), (255, 170, 0), (255, 255, 0), (170, 255, 0),
    (85, 255, 0), (0, 255, 0), (0, 255, 85), (0, 255, 170), (0, 255, 255),
    (0, 170, 255), (0, 85, 255), (0, 0, 255), (85, 0, 255), (170, 0, 255),
    (255, 0, 255), (255, 0, 170), (255, 0, 85),
]
# Huesos entre keypoints BODY_18 (0=nariz, 1=cuello, 2-4 brazo D, 5-7 brazo I,
# 8-10 pierna D, 11-13 pierna I, 14/15 ojos, 16/17 orejas)
LIMBS = [
    (1, 2), (1, 5), (2, 3), (3, 4), (5, 6), (6, 7), (1, 8), (8, 9), (9, 10),
    (1, 11), (11, 12), (12, 13), (1, 0), (0, 14), (14, 16), (0, 15), (15, 17),
]

Punto = tuple[float, float] | None


def render_pose(kps: list[Punto], size: int = 1024) -> Image.Image:
    img = Image.new("RGB", (size, size), (0, 0, 0))
    d = ImageDraw.Draw(img)
    grosor = max(4, size // 120)
    for i, (a, b) in enumerate(LIMBS):
        if kps[a] is None or kps[b] is None:
            continue
        d.line([kps[a], kps[b]], fill=COLORS[i % len(COLORS)], width=grosor)
    r = max(5, size // 110)
    for j, p in enumerate(kps):
        if p is None:
            continue
        d.ellipse([p[0] - r, p[1] - r, p[0] + r, p[1] + r], fill=COLORS[j])
    return img


def _polar(origin: tuple[float, float], angle_deg: float, length: float) -> tuple[float, float]:
    """Punto a `length` de origin. Ángulo desde la vertical hacia abajo;
    positivo = hacia delante (+x en vista de perfil)."""
    a = math.radians(angle_deg)
    return (origin[0] + length * math.sin(a), origin[1] + length * math.cos(a))


# ---------------------------------------------------------------------------
# Figura de PERFIL (mirando a la derecha)
# ---------------------------------------------------------------------------

def _side_figure(
    cx: float,
    s: float,
    bob: float,
    legs,   # ((swing, flex) pierna D, (swing, flex) pierna I) en grados
    arms,   # ((swing, flex) brazo D, (swing, flex) brazo I) en grados
    *,
    pelvis_dy: float = 0.0,
    lean: float = 0.0,        # inclinación del torso hacia delante (grados)
    head: tuple[float, float] = (0.0, 0.0),  # desplazamiento extra de la cabeza
) -> list[Punto]:
    pelvis_y = 560 * s + bob + pelvis_dy * s
    lean_r = math.radians(lean)
    neck = (cx + 255 * s * math.sin(lean_r), pelvis_y - 255 * s * math.cos(lean_r))

    hx, hy = head
    nose = (neck[0] + (58 + hx) * s, neck[1] - (90 - hy) * s)
    eye_r = (neck[0] + (60 + hx) * s, neck[1] - (109 - hy) * s)
    ear_r = (neck[0] + (18 + hx) * s, neck[1] - (105 - hy) * s)

    thigh, shin = 175 * s, 170 * s
    upper_arm, forearm = 135 * s, 120 * s

    def leg(spec, side):
        swing, flex = spec
        hip = (cx + side * 4 * s, pelvis_y)
        knee = _polar(hip, swing, thigh)
        ankle = _polar(knee, swing - flex, shin)  # la tibia flexiona hacia atrás
        return hip, knee, ankle

    def arm(spec, side):
        swing, flex = spec
        shoulder = (neck[0] + side * 7 * s, neck[1] + 10 * s)
        elbow = _polar(shoulder, swing, upper_arm)
        wrist = _polar(elbow, swing + flex, forearm)  # el codo flexiona hacia delante
        return shoulder, elbow, wrist

    hip_r, knee_r, ank_r = leg(legs[0], +1)
    hip_l, knee_l, ank_l = leg(legs[1], -1)
    sho_r, elb_r, wri_r = arm(arms[0], +1)
    sho_l, elb_l, wri_l = arm(arms[1], -1)

    # Perfil mirando a la derecha: ojo y oreja izquierdos quedan ocultos
    return [
        nose, neck,
        sho_r, elb_r, wri_r,
        sho_l, elb_l, wri_l,
        hip_r, knee_r, ank_r,
        hip_l, knee_l, ank_l,
        eye_r, None, ear_r, None,
    ]


# ---------------------------------------------------------------------------
# Figura FRONTAL / DE ESPALDAS (para top-down: frente y espalda)
# ---------------------------------------------------------------------------

def _facing_figure(
    cx: float,
    s: float,
    bob: float,
    legs_fs: tuple[tuple[float, float], tuple[float, float]],  # (lift 0..1, stride -1..1) D, I
    arm_flex: tuple[float, float],   # flexión de brazo (0..1) D, I
    facing: str,                     # "front" | "back"
    sway: float = 0.0,               # balanceo lateral del cuerpo (px a escala 1024)
) -> list[Punto]:
    side_r = -1 if facing == "front" else +1  # x del lado derecho del sujeto
    cxb = cx + sway * s
    pelvis_y = 560 * s + bob
    neck = (cxb, 300 * s + bob)

    if facing == "front":
        nose = (cxb, 205 * s + bob)
        eye_r = (cxb + side_r * 22 * s, 192 * s + bob)
        eye_l = (cxb - side_r * 22 * s, 192 * s + bob)
        ear_r = (cxb + side_r * 40 * s, 202 * s + bob)
        ear_l = (cxb - side_r * 40 * s, 202 * s + bob)
    else:
        # De espaldas: sin cara; solo orejas
        nose = eye_r = eye_l = None
        ear_r = (cxb + side_r * 38 * s, 200 * s + bob)
        ear_l = (cxb - side_r * 38 * s, 200 * s + bob)

    def leg(spec, sx):
        lift, stride = spec
        hip = (cxb + sx * 26 * s, pelvis_y)
        # lift acorta la pierna (rodilla al frente); stride planta el pie
        # adelante (más abajo en pantalla) o atrás (más arriba)
        knee = (hip[0] + sx * 3 * s * lift, hip[1] + 175 * s * (1 - 0.32 * lift))
        ankle = (knee[0], knee[1] + 170 * s * (1 - 0.30 * lift) + 14 * s * stride)
        return hip, knee, ankle

    def arm(flex, sx):
        shoulder = (cxb + sx * 55 * s, 312 * s + bob)
        elbow = (shoulder[0] + sx * 8 * s, shoulder[1] + 135 * s)
        wrist = (elbow[0] + sx * 10 * s * flex, elbow[1] + 120 * s * (1 - 0.45 * flex))
        return shoulder, elbow, wrist

    hip_r, knee_r, ank_r = leg(legs_fs[0], side_r)
    hip_l, knee_l, ank_l = leg(legs_fs[1], -side_r)
    sho_r, elb_r, wri_r = arm(arm_flex[0], side_r)
    sho_l, elb_l, wri_l = arm(arm_flex[1], -side_r)

    return [
        nose, neck,
        sho_r, elb_r, wri_r,
        sho_l, elb_l, wri_l,
        hip_r, knee_r, ank_r,
        hip_l, knee_l, ank_l,
        eye_r, eye_l, ear_r, ear_l,
    ]


# ---------------------------------------------------------------------------
# Locomoción cíclica
# ---------------------------------------------------------------------------

def walk_pose(t: float, size: int = 1024) -> list[Punto]:
    """Caminata de perfil, fase t ∈ [0,1)."""
    s = size / 1024
    phase = 2 * math.pi * t
    bob = -14 * s * abs(math.sin(phase))

    def leg(offset):
        swing = 34 * math.sin(phase + offset)
        lift = 55 * max(0.0, math.sin(phase + offset - math.pi / 2))
        return (swing, 12 + lift)

    def arm(offset):
        return (-26 * math.sin(phase + offset), 28)

    return _side_figure(
        512 * s, s, bob,
        legs=(leg(0.0), leg(math.pi)),
        arms=(arm(math.pi), arm(0.0)),  # brazos en contrafase con su pierna
    )


def idle_pose(t: float, size: int = 1024) -> list[Punto]:
    """Reposo de perfil con respiración sutil."""
    s = size / 1024
    phase = 2 * math.pi * t
    bob = -5 * s * (0.5 + 0.5 * math.sin(phase))
    sway = 2 * math.sin(phase)
    return _side_figure(
        512 * s, s, bob,
        legs=((3.0, 8), (-3.0, 8)),
        arms=((5.0 + sway, 14), (3.0 + sway, 14)),
    )


def _walk_facing(t: float, size: int, facing: str) -> list[Punto]:
    s = size / 1024
    phase = 2 * math.pi * t
    bob = -9 * s * abs(math.sin(phase))
    # stride: el pie se planta adelante/atrás; lift: rodilla arriba al pasar
    stride_r, stride_l = math.sin(phase), math.sin(phase + math.pi)
    lift_r = max(0.0, math.cos(phase))
    lift_l = max(0.0, math.cos(phase + math.pi))
    flex_r = 0.2 + 0.4 * max(0.0, stride_l)  # brazos en contrafase
    flex_l = 0.2 + 0.4 * max(0.0, stride_r)
    return _facing_figure(
        512 * s, s, bob,
        ((lift_r, stride_r), (lift_l, stride_l)),
        (flex_r, flex_l),
        facing,
        sway=6 * math.sin(phase),
    )


def walk_down_pose(t: float, size: int = 1024) -> list[Punto]:
    return _walk_facing(t, size, "front")


def walk_up_pose(t: float, size: int = 1024) -> list[Punto]:
    return _walk_facing(t, size, "back")


def _idle_facing(t: float, size: int, facing: str) -> list[Punto]:
    s = size / 1024
    phase = 2 * math.pi * t
    bob = -5 * s * (0.5 + 0.5 * math.sin(phase))
    breath = 0.08 + 0.06 * math.sin(phase)
    return _facing_figure(
        512 * s, s, bob,
        ((0.0, 0.0), (0.0, 0.0)),
        (breath, breath),
        facing,
        sway=1.5 * math.sin(phase),
    )


def idle_down_pose(t: float, size: int = 1024) -> list[Punto]:
    return _idle_facing(t, size, "front")


def idle_up_pose(t: float, size: int = 1024) -> list[Punto]:
    return _idle_facing(t, size, "back")


# ---------------------------------------------------------------------------
# Acciones por keyframes (perfil)
# ---------------------------------------------------------------------------

def _kf(t: float, frames: int) -> int:
    return min(frames - 1, int(round(t * frames)))


def attack_pose(t: float, size: int = 1024) -> list[Punto]:
    """Golpe con el brazo derecho: anticipación → carga → golpe → recuperación."""
    s = size / 1024
    i = _kf(t, 5)
    arm_r = [(-30, 25), (-140, 35), (100, 8), (55, 10), (12, 20)][i]
    arm_l = [(8, 18), (25, 25), (-25, 15), (-12, 15), (6, 18)][i]
    lean = [3, -8, 18, 12, 4][i]
    dy = [0, -6, 6, 4, 0][i]
    return _side_figure(
        512 * s, s, 0.0,
        legs=((20, 10), (-16, 14)),
        arms=(arm_r, arm_l),
        pelvis_dy=dy, lean=lean,
    )


def hurt_pose(t: float, size: int = 1024) -> list[Punto]:
    """Retroceso al recibir daño."""
    s = size / 1024
    i = _kf(t, 3)
    arm_r = [(-15, 20), (-45, 20), (-20, 20)][i]
    arm_l = [(-20, 22), (-60, 25), (-28, 22)][i]
    lean = [-6, -22, -10][i]
    dy = [0, 10, 4][i]
    head = [(0, 0), (-12, 0), (-4, 0)][i]
    return _side_figure(
        512 * s, s, 0.0,
        legs=((8, 12), (-26, 30)),
        arms=(arm_r, arm_l),
        pelvis_dy=dy, lean=lean, head=head,
    )


def death_pose(t: float, size: int = 1024) -> list[Punto]:
    """Colapso: impacto → caída → de rodillas → desplome → tumbado."""
    s = size / 1024
    cx = 512 * s
    i = _kf(t, 5)
    if i == 4:
        # Tumbado boca arriba, cabeza a la izquierda (pose manual)
        g = 885 * s

        def p(dx: float, dy: float) -> tuple[float, float]:
            return (cx + dx * s, g + dy * s)

        return [
            p(-150, -38),                              # nariz (cara hacia arriba)
            p(-95, -18),                               # cuello
            p(-80, -30), p(-15, -34), p(45, -30),      # brazo D
            p(-80, -6), p(-18, -2), p(40, -6),         # brazo I
            p(15, -22), p(105, -20), p(195, -24),      # pierna D
            p(15, -8), p(105, -6), p(195, -10),        # pierna I
            p(-160, -52), None, p(-138, -60), None,    # ojo/oreja visibles
        ]
    arm_r = [(-45, 20), (-20, 10), (5, 5), (60, 10), None][i]
    arm_l = [(-60, 25), (-30, 12), (-5, 5), (50, 12), None][i]
    legs = [
        ((8, 12), (-26, 30)),
        ((6, 70), (-10, 75)),
        ((4, 85), (-6, 88)),
        ((10, 80), (-4, 85)),
        None,
    ][i]
    lean = [-22, -14, -5, 55, 0][i]
    dy = [10, 90, 170, 200, 0][i]
    return _side_figure(512 * s, s, 0.0, legs=legs, arms=(arm_r, arm_l),
                        pelvis_dy=dy, lean=lean)


def pickup_pose(t: float, size: int = 1024) -> list[Punto]:
    """Agacharse y recoger un objeto del suelo con la mano derecha."""
    s = size / 1024
    i = _kf(t, 4)
    arm_r = [(6, 15), (55, 15), (75, 5), (35, 60)][i]
    arm_l = [(-4, 15), (-8, 18), (-10, 20), (-6, 18)][i]
    lean = [2, 30, 48, 10][i]
    dy = [0, 40, 70, 10][i]
    flex = [(8, 8), (45, 50), (70, 72), (14, 14)][i]
    return _side_figure(
        512 * s, s, 0.0,
        legs=((10, flex[0]), (-8, flex[1])),
        arms=(arm_r, arm_l),
        pelvis_dy=dy, lean=lean,
    )


def cast_pose(t: float, size: int = 1024) -> list[Punto]:
    """Lanzar un hechizo: recoger energía y proyectarla al frente."""
    s = size / 1024
    i = _kf(t, 5)
    arm_r = [(6, 15), (-10, 120), (85, 5), (95, 5), (25, 30)][i]
    arm_l = [(-4, 15), (-15, 125), (80, 8), (90, 8), (20, 30)][i]
    lean = [0, -4, 10, 12, 2][i]
    dy = [0, 4, 0, -4, 0][i]
    return _side_figure(
        512 * s, s, 0.0,
        legs=((12, 10), (-12, 14)),
        arms=(arm_r, arm_l),
        pelvis_dy=dy, lean=lean,
    )


def celebrate_pose(t: float, size: int = 1024) -> list[Punto]:
    """Celebración: brazos al cielo con un pequeño salto."""
    s = size / 1024
    i = _kf(t, 4)
    arm_r = [(6, 15), (110, 10), (172, 5), (95, 20)][i]
    arm_l = [(-4, 15), (105, 12), (-172, 5), (90, 20)][i]
    dy = [0, -6, -35, 0][i]
    legs = [
        ((4, 8), (-4, 8)),
        ((8, 12), (-8, 12)),
        ((15, 35), (-15, 35)),  # piernas recogidas en el aire
        ((5, 10), (-5, 10)),
    ][i]
    return _side_figure(512 * s, s, 0.0, legs=legs, arms=(arm_r, arm_l), pelvis_dy=dy)


# ---------------------------------------------------------------------------
# Registro de ciclos
# ---------------------------------------------------------------------------

ANIMATIONS: dict[str, dict] = {
    "walk": {"frames": 8, "pose": walk_pose, "fps": 10, "label": "Caminar (perfil)"},
    "walk_down": {"frames": 8, "pose": walk_down_pose, "fps": 10,
                  "label": "Caminar (frente)", "hint": "front view, facing camera"},
    "walk_up": {"frames": 8, "pose": walk_up_pose, "fps": 10,
                "label": "Caminar (espalda)", "hint": "seen from behind, back view"},
    "idle": {"frames": 4, "pose": idle_pose, "fps": 5, "label": "Reposo (perfil)"},
    "idle_down": {"frames": 4, "pose": idle_down_pose, "fps": 5,
                  "label": "Reposo (frente)", "hint": "front view, facing camera"},
    "idle_up": {"frames": 4, "pose": idle_up_pose, "fps": 5,
                "label": "Reposo (espalda)", "hint": "seen from behind, back view"},
    "attack": {"frames": 5, "pose": attack_pose, "fps": 10, "label": "Ataque (perfil)"},
    "hurt": {"frames": 3, "pose": hurt_pose, "fps": 8, "label": "Daño (perfil)"},
    "death": {"frames": 5, "pose": death_pose, "fps": 6, "label": "Muerte (perfil)"},
    "pickup": {"frames": 4, "pose": pickup_pose, "fps": 8, "label": "Recoger (perfil)"},
    "cast": {"frames": 5, "pose": cast_pose, "fps": 8, "label": "Hechizo (perfil)"},
    "celebrate": {"frames": 4, "pose": celebrate_pose, "fps": 6, "label": "Celebrar (perfil)"},
}


def ensure_poses(anim: str, size: int = 1024, force: bool = False) -> list[Path]:
    """Genera (si faltan) y devuelve los esqueletos PNG del ciclo `anim`.

    Además de los ciclos integrados, acepta ciclos personalizados: una carpeta
    `assets/poses/<nombre>/` con esqueletos OpenPose puestos a mano por el
    usuario, nombrados frame_00.png, frame_01.png, ...
    """
    if anim not in ANIMATIONS:
        custom_dir = ASSETS_DIR / anim
        custom = sorted(custom_dir.glob("frame_*.png")) if custom_dir.is_dir() else []
        if custom:
            return custom
        raise ValueError(
            f"Animación desconocida '{anim}'. Integradas: {', '.join(ANIMATIONS)}. "
            f"Para un ciclo propio crea la carpeta {custom_dir} y pon dentro "
            "frame_00.png, frame_01.png, ... (esqueletos OpenPose sobre fondo negro)"
        )
    spec = ANIMATIONS[anim]
    out_dir = ASSETS_DIR / anim
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for i in range(spec["frames"]):
        path = out_dir / f"frame_{i:02d}.png"
        if force or not path.exists():
            kps = spec["pose"](i / spec["frames"], size)
            render_pose(kps, size).save(path)
        paths.append(path)
    return paths

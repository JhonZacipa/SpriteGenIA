"""Escucha en vivo del WebSocket de ComfyUI: paso de muestreo y preview.

ComfyUI empuja por ws://<server>/ws dos cosas que su API REST no da:
los mensajes JSON ``progress`` (paso actual del sampler, ``value``/``max``)
y frames binarios ``PREVIEW_IMAGE`` con un JPEG del latente a medio
desruido (solo si arranca con ``--preview-method``). Este módulo los vuelca
en el dict ``LIVE``, que el servidor de la GUI expone en ``/api/live``.

Es un canal puramente informativo: el polling HTTP de ``run_workflow_all``
sigue siendo quien decide cuándo terminó el trabajo. Si ``websocket-client``
no está instalado o la conexión falla, todo funciona igual pero sin
progreso fino ni miniatura.

La conexión es ÚNICA y persistente por proceso (no una por workflow): el
handler de ComfyUI hace ``sockets.pop(sid)`` al cerrar, así que reconectar
con el mismo clientId puede desregistrar la conexión nueva si el cierre de
la vieja se procesa después. Con una sola conexión viva no hay churn. El
clientId lleva el PID para que CLI y GUI (procesos distintos) no se pisen
el registro entre sí, y debe ser el MISMO que viaja en el POST /prompt:
ComfyUI dirige progress y previews solo al socket de ese clientId.
"""
from __future__ import annotations

import json
import os
import struct
import threading
import time
from contextlib import contextmanager
from typing import Iterator

try:
    import websocket  # paquete websocket-client (opcional)
except ImportError:
    websocket = None

CLIENT_ID = f"spritegen-{os.getpid()}"

# Estado compartido con app/server.py (mismo proceso). Escritor único: el
# hilo de escucha (solo hay un workflow a la vez); los lectores hacen
# lecturas atómicas de claves sueltas, sin lock.
LIVE = {
    "active": False,      # hay un workflow vigilándose ahora mismo
    "step": 0,            # paso de muestreo actual (mensaje `progress`)
    "step_total": 0,
    "preview": None,      # bytes del último preview (JPEG casi siempre)
    "preview_fmt": "jpeg",
    "preview_seq": 0,     # crece con cada preview: cache-buster para la GUI
    "node": None,         # id del nodo que se ejecuta ahora (mensaje `executing`)
}

_PREVIEW_IMAGE = 1  # BinaryEventTypes.PREVIEW_IMAGE (ComfyUI/protocol.py)

_JOB = threading.Event()  # el hilo solo conecta mientras hay trabajo
_STATE = {"url": "", "prompt_id": ""}
_THREAD_LOCK = threading.Lock()
_thread: threading.Thread | None = None


@contextmanager
def watching(server: str, prompt_id: str) -> Iterator[None]:
    """Vigila un workflow mientras dura el bloque. Nunca lanza."""
    if websocket is None:
        yield
        return
    _STATE["url"] = (
        server.replace("https://", "wss://").replace("http://", "ws://")
        + f"/ws?clientId={CLIENT_ID}"
    )
    _STATE["prompt_id"] = prompt_id
    LIVE.update(active=True, step=0, step_total=0, node=None)
    _ensure_thread()
    _JOB.set()
    try:
        yield
    finally:
        _JOB.clear()
        LIVE["active"] = False


def _ensure_thread() -> None:
    global _thread
    with _THREAD_LOCK:
        if _thread is None or not _thread.is_alive():
            _thread = threading.Thread(target=_listen, daemon=True, name="livefeed")
            _thread.start()


def _listen() -> None:
    ws = None
    while True:
        if ws is None:
            _JOB.wait()  # sin trabajo no se (re)conecta: ComfyUI puede estar apagado
            try:
                ws = websocket.create_connection(_STATE["url"], timeout=5)
                ws.settimeout(1.0)
            except Exception:
                # Pausa antes de reintentar: da tiempo a ComfyUI a reap-ear la
                # conexión anterior (su pop(sid) tardío desregistraría esta)
                time.sleep(1.5)
                continue
        try:
            opcode, data = ws.recv_data()
        except websocket.WebSocketTimeoutException:
            continue  # sin mensajes este segundo; la conexión sigue viva
        except Exception:
            try:
                ws.close()
            except Exception:
                pass
            ws = None
            continue
        try:
            _handle(opcode, data)
        except Exception:
            pass  # un mensaje malformado no debe tumbar la escucha


def _handle(opcode: int, data) -> None:
    if opcode == websocket.ABNF.OPCODE_TEXT:
        msg = json.loads(data)
        if msg.get("type") not in ("progress", "executing"):
            return
        d = msg.get("data", {})
        # Solo el workflow vigilado: entre trabajos llegan mensajes rancios
        if not _JOB.is_set() or d.get("prompt_id") != _STATE["prompt_id"]:
            return
        if msg["type"] == "executing":
            # Etapa en curso: en los grafos con nodos largos que no muestrean
            # (remallado, horneado 3D) es el único progreso que hay
            LIVE["node"] = d.get("node")
            LIVE.update(step=0, step_total=0)
            return
        LIVE["step"] = int(d["value"])
        LIVE["step_total"] = int(d["max"])
    elif opcode == websocket.ABNF.OPCODE_BINARY:
        # Frame binario de ComfyUI: [4B evento][4B formato: 1 JPEG · 2 PNG][imagen]
        if len(data) < 8 or not _JOB.is_set():
            return
        event, fmt = struct.unpack_from(">II", data)
        if event != _PREVIEW_IMAGE:
            return
        LIVE["preview_fmt"] = "png" if fmt == 2 else "jpeg"
        LIVE["preview"] = bytes(data[8:])
        LIVE["preview_seq"] += 1

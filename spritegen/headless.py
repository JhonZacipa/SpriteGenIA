"""Navegador sin ventana para la CLI: Chrome (o Edge) headless por CDP.

El horneado 3D → sprites lo pinta Three.js con WebGL, así que la CLI no
puede hacerlo en Python: abre la misma página que usaría la GUI en un Chrome
sin ventana y le pide el resultado por el protocolo de DevTools (CDP), con el
`websocket-client` que el proyecto ya trae para el progreso en vivo.

`navegador()` abre el navegador con un perfil temporal (en W:, nunca en C:)
y devuelve un objeto con `evaluar(expr)`, que espera promesas y devuelve el
valor o lanza el error de la página tal cual. `servidor_gui()` da la URL del
servidor de la GUI: el que ya esté abierto o, si no hay ninguno, uno de usar
y tirar dentro del propio proceso de la CLI.
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

import requests
import websocket

from spritegen.generate import PROJECT_ROOT

# Perfiles temporales del navegador: dentro del proyecto (W:) y fuera de git
CACHE_DIR = PROJECT_ROOT / ".cache" / "headless"

CANDIDATOS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    # Edge es Chromium y viene con Windows: sirve igual si no hay Chrome
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]


GUI_URL = "http://127.0.0.1:8787"


def _vivo(url: str) -> bool:
    try:
        return requests.get(f"{url}/api/status", timeout=3).ok
    except requests.RequestException:
        return False


@contextmanager
def servidor_gui(url: str = GUI_URL) -> Iterator[str]:
    """La página de horneado y el endpoint que pixeliza los sirve el servidor
    de la GUI. Si ya está abierto (run_gui.bat) se usa ese; si no, se levanta
    uno temporal en un puerto libre, en un hilo de este proceso, y se apaga al
    terminar. No hace falta ComfyUI: el horneado no usa el motor de IA."""
    if _vivo(url):
        yield url
        return
    import uvicorn

    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))   # para importar app.server
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        puerto = s.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config("app.server:app", host="127.0.0.1",
                                           port=puerto, log_level="warning"))
    hilo = threading.Thread(target=server.run, daemon=True, name="gui-temporal")
    hilo.start()
    temporal = f"http://127.0.0.1:{puerto}"
    limite = time.time() + 30
    while not server.started:
        if not hilo.is_alive() or time.time() > limite:
            raise RuntimeError("No se pudo levantar el servidor temporal de la GUI")
        time.sleep(0.1)
    try:
        yield temporal
    finally:
        server.should_exit = True
        hilo.join(timeout=10)


def buscar_navegador(preferido: str | None = None) -> str:
    for ruta in ([preferido] if preferido else []) + CANDIDATOS:
        if ruta and Path(ruta).is_file():
            return ruta
    raise RuntimeError(
        "No se encontró Chrome ni Edge. Indica la ruta con --browser "
        "(p. ej. --browser \"C:\\...\\chrome.exe\")"
    )


class Pagina:
    """Una pestaña controlada por CDP."""

    def __init__(self, ws: websocket.WebSocket):
        self._ws = ws
        self._id = 0

    def _llamar(self, metodo: str, params: dict, timeout: float) -> dict:
        self._id += 1
        mi_id = self._id
        self._ws.settimeout(timeout)
        self._ws.send(json.dumps({"id": mi_id, "method": metodo, "params": params}))
        while True:
            msg = json.loads(self._ws.recv())
            if msg.get("id") == mi_id:   # el resto son eventos: se ignoran
                if "error" in msg:
                    raise RuntimeError(f"CDP {metodo}: {msg['error'].get('message')}")
                return msg.get("result", {})

    def evaluar(self, expresion: str, timeout: float = 60) -> Any:
        """Evalúa en la página (esperando si es una promesa) y devuelve el valor.
        Si la página lanza, se relanza aquí con su mensaje."""
        res = self._llamar("Runtime.evaluate", {
            "expression": expresion, "awaitPromise": True, "returnByValue": True,
        }, timeout)
        if "exceptionDetails" in res:
            det = res["exceptionDetails"]
            texto = (det.get("exception") or {}).get("description") or det.get("text") or "error"
            # La primera línea basta (el resto es la pila de la página), y sin
            # el «Error: » que antepone el navegador
            raise RuntimeError(texto.splitlines()[0].removeprefix("Error: "))
        return res.get("result", {}).get("value")

    def esperar(self, expresion: str, timeout: float = 60) -> Any:
        """Repite `expresion` hasta que dé algo verdadero (la página carga
        sus módulos de forma asíncrona tras abrirse)."""
        limite = time.time() + timeout
        while time.time() < limite:
            valor = self.evaluar(expresion, timeout=10)
            if valor:
                return valor
            time.sleep(0.25)
        raise RuntimeError(f"La página no llegó a estar lista en {timeout:.0f} s")


@contextmanager
def navegador(url: str, *, ruta: str | None = None, timeout: float = 30) -> Iterator[Pagina]:
    """Abre `url` en un navegador sin ventana y entrega su pestaña. Al salir
    cierra el navegador y borra su perfil temporal."""
    exe = buscar_navegador(ruta)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    perfil = Path(tempfile.mkdtemp(prefix="perfil-", dir=CACHE_DIR))
    proc = subprocess.Popen(
        [
            exe, "--headless=new", f"--user-data-dir={perfil}",
            "--remote-debugging-port=0",   # el puerto real lo escribe en DevToolsActivePort
            "--no-first-run", "--no-default-browser-check", "--disable-extensions",
            # Si el modo sin ventana no tiene GPU, WebGL cae en SwiftShader
            # (render por software), que Chrome ya no activa sin este permiso
            "--enable-unsafe-swiftshader",
            url,
        ],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    ws = None
    try:
        archivo = perfil / "DevToolsActivePort"
        limite = time.time() + timeout
        while not (archivo.exists() and archivo.read_text().strip()):
            if proc.poll() is not None:
                raise RuntimeError(f"El navegador se cerró al arrancar ({exe})")
            if time.time() > limite:
                raise RuntimeError("El navegador no abrió su puerto de depuración")
            time.sleep(0.2)
        puerto = archivo.read_text().splitlines()[0].strip()
        destino = None
        while destino is None and time.time() < limite:
            pestañas = requests.get(f"http://127.0.0.1:{puerto}/json/list", timeout=5).json()
            destino = next((p["webSocketDebuggerUrl"] for p in pestañas
                            if p.get("type") == "page"), None)
            if destino is None:
                time.sleep(0.2)
        if destino is None:
            raise RuntimeError("El navegador no abrió ninguna pestaña")
        # suppress_origin: Chrome rechaza los WebSocket de DevTools que traen
        # cabecera Origin si no se arrancó con --remote-allow-origins
        ws = websocket.create_connection(destino, timeout=timeout, suppress_origin=True)
        yield Pagina(ws)
    finally:
        if ws is not None:
            try:
                ws.close()
            except Exception:
                pass
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        shutil.rmtree(perfil, ignore_errors=True)

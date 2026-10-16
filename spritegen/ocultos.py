"""Atributo «oculto» de Windows para los archivos del historial.

Un elemento marcado con `hidden` desaparece del historial de la GUI Y sus
archivos quedan marcados como ocultos para el Explorador. Lo comparten el
servidor de la GUI y los comandos de la CLI que reescriben una ficha (el
de la versión web de un modelo 3D), porque en Windows no se puede reescribir
con `write_text` un archivo oculto (gotcha 10a).
"""
from __future__ import annotations

import ctypes
import json
import sys
from pathlib import Path

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


def set_os_hidden(path: Path, on: bool) -> None:
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


def write_meta_file(path: Path, meta: dict) -> None:
    """Guarda un meta YA EXISTENTE respetando su atributo de oculto. En Windows
    write_text sobre un archivo oculto falla con «acceso denegado» (abre con
    CREATE_ALWAYS + FILE_ATTRIBUTE_NORMAL), así que hay que desmarcarlo antes y
    volver a marcarlo después."""
    set_os_hidden(path, False)
    path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    set_os_hidden(path, bool(meta.get("hidden")))

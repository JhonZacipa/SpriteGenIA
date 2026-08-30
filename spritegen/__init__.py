from spritegen.palette import extract_palette, load_palette, save_palette
from spritegen.pixelize import PixelizeResult, pixelize
from spritegen.sheet import make_sheet

__version__ = "0.1.0"

__all__ = [
    "pixelize",
    "PixelizeResult",
    "load_palette",
    "save_palette",
    "extract_palette",
    "make_sheet",
]

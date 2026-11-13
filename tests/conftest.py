import math
import os
import shutil
import tempfile
from pathlib import Path

import pytest
from mutagen.easyid3 import EasyID3

# Frame MPEG-1 Layer III, 128 kbps, 44,1 kHz, sin CRC: 417 bytes, 1152 muestras.
_FRAME = b"\xff\xfb\x90\x64" + b"\x00" * 413
_MUESTRAS_POR_FRAME = 1152
_FRECUENCIA = 44100


@pytest.fixture
def crear_mp3():
    def crear(ruta: Path, segundos: float = 3.0, titulo: str | None = None,
              artista: str | None = None) -> Path:
        ruta = Path(ruta)
        ruta.parent.mkdir(parents=True, exist_ok=True)
        frames = math.ceil(segundos * _FRECUENCIA / _MUESTRAS_POR_FRAME)
        ruta.write_bytes(_FRAME * frames)
        if titulo or artista:
            tags = EasyID3()
            if titulo:
                tags["title"] = titulo
            if artista:
                tags["artist"] = artista
            tags.save(ruta)
        return ruta

    return crear


@pytest.fixture
def dir_corto():
    """Directorio de ruta corta (los sockets Unix admiten ~108 caracteres)."""
    base = os.environ.get("XDG_RUNTIME_DIR", "/tmp")
    ruta = Path(tempfile.mkdtemp(prefix="cfm.", dir=base))
    yield ruta
    shutil.rmtree(ruta, ignore_errors=True)

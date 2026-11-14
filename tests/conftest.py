import math
import os
import shutil
import tempfile
from types import SimpleNamespace
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
              artista: str | None = None, album: str | None = None,
              isrc: str | None = None) -> Path:
        ruta = Path(ruta)
        ruta.parent.mkdir(parents=True, exist_ok=True)
        frames = math.ceil(segundos * _FRECUENCIA / _MUESTRAS_POR_FRAME)
        ruta.write_bytes(_FRAME * frames)
        if titulo or artista or album or isrc:
            tags = EasyID3()
            if titulo:
                tags["title"] = titulo
            if artista:
                tags["artist"] = artista
            if album:
                tags["album"] = album
            if isrc:
                tags["isrc"] = isrc
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


@pytest.fixture
def crear_wav():
    from cassette_fm.clips import generar_clip_de_prueba

    def crear(ruta: Path, segundos: float = 4.0) -> Path:
        return generar_clip_de_prueba(Path(ruta), segundos)

    return crear


class SintetizadorFalso:
    """Imita al Sintetizador del servicio DJ: escribe un WAV de `duracion` segundos; puede bloquearse con `puerta`."""

    def __init__(self, duracion: float = 3.0):
        self.duracion = duracion
        self.puerta = None      # threading.Event: si está, sintetizar espera a que se setee
        self.cargado = False
        self.llamadas = []

    def sintetizar(self, fonemas, voz, lang, salida, velocidad=None, texto=None):
        import wave
        if self.puerta is not None:
            assert self.puerta.wait(10), "el sintetizador falso quedó bloqueado"
        self.llamadas.append((fonemas, voz, lang))
        salida = Path(salida)
        salida.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(salida), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(8000)
            w.writeframes(b"\x01\x00" * int(8000 * self.duracion))
        return self.duracion

    def voces(self):
        return ["am_michael", "em_santa"]


@pytest.fixture
def servicio_dj(tmp_path):
    """Fábrica del servicio DJ real (parte 2a) en un hilo, con un sintetizador falso: `servicio_dj(duracion=3.0)`."""
    import random
    import threading

    from cassette_fm.dj.cola import Cola
    from cassette_fm.dj.config import ConfigServicioDJ, RutasDJ
    from cassette_fm.dj.guiones import RegistroGuiones
    from cassette_fm.dj.lexico import Lexico
    from cassette_fm.dj.modo import ModoDJ
    from cassette_fm.dj.produccion import Productor
    from cassette_fm.dj.servidor import crear_servidor

    creados = []

    def crear(duracion: float = 3.0):
        base = tmp_path / f"dj{len(creados)}"
        s = SimpleNamespace()
        s.rutas = RutasDJ(config=base / "cfg" / "config.toml", estado=base / "estado", clips=base / "clips")
        config = ConfigServicioDJ(modelos_dir=base / "sin-modelos")
        s.sintetizador = SintetizadorFalso(duracion)
        s.guiones = RegistroGuiones(s.rutas.guiones)
        productor = Productor(config, s.rutas, s.sintetizador, lambda t, lang: t, Lexico(), s.guiones,
                              azar=random.Random(1))
        s.cola = Cola(productor, trabajadores=1)
        s.modo = ModoDJ()
        s.servidor = crear_servidor(s.cola, s.sintetizador, "127.0.0.1", 0, config.modelos_dir, modo=s.modo,
                                    probar_llm=lambda: True)
        threading.Thread(target=lambda: s.servidor.serve_forever(poll_interval=0.02), daemon=True,
                         name="dj-http-test").start()
        s.url = f"http://127.0.0.1:{s.servidor.server_address[1]}"
        creados.append(s)
        return s

    yield crear
    for s in creados:
        if s.sintetizador.puerta is not None:
            s.sintetizador.puerta.set()
        s.servidor.shutdown()
        s.servidor.server_close()
        s.cola.detener(2)

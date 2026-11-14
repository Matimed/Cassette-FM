import ctypes
import gc
import http.client
import os
import threading
import time
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

from cassette_fm.dj.config import ConfigServicioDJ

ARCHIVOS_MODELO = ("kokoro-v1.0.onnx", "voices-v1.0.bin")
URL_MODELOS = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/"


class ErrorModelos(Exception):
    """Faltan los archivos del modelo de Kokoro, están corruptos o falta el extra [dj]."""


def _devolver_memoria() -> None:
    """Después de soltar Kokoro, glibc se queda con cientos de MB; se le piden de vuelta al sistema."""
    gc.collect()
    try:
        ctypes.CDLL("libc.so.6").malloc_trim(0)
    except (OSError, AttributeError):
        pass          # no es glibc (o no es Linux): no hay nada que devolver


def faltan_modelos(modelos_dir: Path) -> list[Path]:
    modelos_dir = Path(modelos_dir)
    return [modelos_dir / n for n in ARCHIVOS_MODELO
            if not (modelos_dir / n).is_file() or (modelos_dir / n).stat().st_size == 0]


def descargar_modelos(modelos_dir: Path, url_base: str = URL_MODELOS,
                      progreso: Callable[[str], None] = print) -> list[Path]:
    """Baja los archivos que falten (a `<nombre>.part`, renombrando al terminar). Los errores de red se propagan."""
    modelos_dir = Path(modelos_dir)
    bajados = []
    for destino in faltan_modelos(modelos_dir):
        modelos_dir.mkdir(parents=True, exist_ok=True)
        parcial = destino.with_name(destino.name + ".part")
        url = url_base.rstrip("/") + "/" + destino.name
        progreso(f"bajando {destino.name} …")
        try:
            hecho = 0
            try:
                with urllib.request.urlopen(url, timeout=30) as respuesta, open(parcial, "wb") as f:
                    esperado = respuesta.headers.get("Content-Length")
                    while bloque := respuesta.read(1 << 20):
                        f.write(bloque)
                        hecho += len(bloque)
            except http.client.HTTPException as e:       # p. ej. IncompleteRead: la conexión se cortó
                raise OSError(f"la descarga de {destino.name} se cortó: {e}") from e
            if esperado and esperado.isdigit() and hecho != int(esperado):
                raise OSError(f"descarga incompleta de {destino.name}: {hecho} de {esperado} bytes")
            os.replace(parcial, destino)
        except BaseException:
            parcial.unlink(missing_ok=True)
            raise
        progreso(f"listo {destino.name} ({destino.stat().st_size / 1e6:.1f} MB)")
        bajados.append(destino)
    return bajados


def fonemizador() -> Callable[[str, str], str]:
    """(texto, lang) -> fonemas, con el fonemizador de kokoro-onnx; no carga el modelo."""
    try:
        from kokoro_onnx import Tokenizer
    except ImportError as e:
        raise ErrorModelos("falta instalar el extra [dj] (pip install -e '.[dj]')") from e
    tokenizador = Tokenizer()
    lock = threading.Lock()

    def fonemizar(texto: str, lang: str) -> str:
        with lock:
            return tokenizador.phonemize(texto, lang)

    return fonemizar


class Sintetizador:
    """Kokoro con carga a demanda: se carga al primer uso y se descarga tras un rato sin trabajo."""

    def __init__(self, config: ConfigServicioDJ, fabrica: Callable[[], Any] | None = None,
                 reloj: Callable[[], float] = time.monotonic):
        self._config = config
        self._fabrica = fabrica or self._cargar_kokoro
        self._reloj = reloj
        self._lock = threading.Lock()
        self._kokoro = None
        self._ultimo_uso = 0.0

    @property
    def cargado(self) -> bool:
        return self._kokoro is not None

    def _cargar_kokoro(self):
        faltan = faltan_modelos(self._config.modelos_dir)
        if faltan:
            raise ErrorModelos(f"faltan los modelos de Kokoro ({', '.join(p.name for p in faltan)}) en "
                               f"{self._config.modelos_dir}: corré `cassette-dj modelos`")
        try:
            from kokoro_onnx import Kokoro
        except ImportError as e:
            raise ErrorModelos("falta instalar el extra [dj] (pip install -e '.[dj]')") from e
        onnx, voces = (self._config.modelos_dir / n for n in ARCHIVOS_MODELO)
        try:
            return Kokoro(str(onnx), str(voces))
        except Exception as e:
            raise ErrorModelos(f"el modelo de Kokoro está corrupto o no se puede cargar ({type(e).__name__}): "
                               f"borrá {self._config.modelos_dir} y corré `cassette-dj modelos`") from e

    def _modelo(self):
        if self._kokoro is None:
            self._kokoro = self._fabrica()
        return self._kokoro

    def voces(self) -> list[str]:
        with self._lock:
            if self._kokoro is not None:
                return sorted(self._kokoro.get_voices())
        archivo = self._config.modelos_dir / ARCHIVOS_MODELO[1]
        if not archivo.is_file() or archivo.stat().st_size == 0:
            raise ErrorModelos(f"falta {ARCHIVOS_MODELO[1]} en {self._config.modelos_dir}: corré `cassette-dj modelos`")
        import numpy as np
        try:
            with np.load(archivo) as v:
                return sorted(v.files)
        except Exception as e:
            raise ErrorModelos(f"el archivo de voces está corrupto ({type(e).__name__}): borralo y corré "
                               "`cassette-dj modelos`") from e

    def sintetizar(self, fonemas: str, voz: str, lang: str, salida: Path) -> float:
        salida = Path(salida)
        with self._lock:
            kokoro = self._modelo()
            try:
                import numpy as np
                import soundfile
            except ImportError as e:
                raise ErrorModelos("falta instalar el extra [dj] (pip install -e '.[dj]')") from e
            disponibles = list(kokoro.get_voices())
            partes = voz.split("+")
            for parte in partes:
                if parte not in disponibles:
                    raise ValueError(f"la voz {parte!r} no existe; disponibles: {', '.join(sorted(disponibles))}")
            estilo = voz if len(partes) == 1 else np.mean([kokoro.get_voice_style(p) for p in partes], axis=0)
            c = self._config
            audio, frecuencia = kokoro.create(fonemas, voice=estilo, speed=c.velocidad, lang=lang, is_phonemes=True,
                                              sentence_pause=c.pausa_oracion_segundos,
                                              clause_pause=c.pausa_coma_segundos, continuous=c.continuo)
            self._ultimo_uso = self._reloj()
        salida.parent.mkdir(parents=True, exist_ok=True)
        parcial = salida.with_name(salida.name + ".part")
        try:
            soundfile.write(str(parcial), audio, frecuencia, format="WAV", subtype="PCM_16")
            os.replace(parcial, salida)
        except BaseException:
            parcial.unlink(missing_ok=True)
            raise
        return len(audio) / frecuencia

    def descargar_si_ocioso(self) -> bool:
        with self._lock:
            if self._kokoro is None:
                return False
            if self._reloj() - self._ultimo_uso < self._config.descargar_tras_minutos * 60:
                return False
            self._kokoro = None
        _devolver_memoria()
        return True

import math
import struct
import wave
from pathlib import Path

_FRECUENCIA = 22050


def generar_clip_de_prueba(ruta: Path, segundos: float = 8.0) -> Path:
    """WAV mono de 3 ráfagas de tono (400, 500 y 600 Hz) separadas por silencios, para probar la voz.

    Los silencios y el cambio de tono permiten notar a qué altura de la frase se entró."""
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    total = int(segundos * _FRECUENCIA)
    muestras = [0] * total
    rafaga, hueco, margen = 0.2 * segundos, 0.1 * segundos, 0.1 * segundos
    largo = int(rafaga * _FRECUENCIA)
    for k, hz in enumerate((400, 500, 600)):
        inicio = int((margen + k * (rafaga + hueco)) * _FRECUENCIA)
        for j in range(largo):
            if inicio + j >= total:
                break
            envolvente = math.sin(math.pi * j / largo)
            muestras[inicio + j] = int(0.4 * 32767 * envolvente * math.sin(2 * math.pi * hz * j / _FRECUENCIA))
    with wave.open(str(ruta), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(_FRECUENCIA)
        w.writeframes(struct.pack(f"<{total}h", *muestras))
    return ruta


def generar_estatica(ruta: Path, segundos: float = 3.0) -> Path:
    """WAV mono de ruido filtrado (suena a radio entre emisoras), RMS ≈ −24 dBFS, con fundido en los bordes para que
    el bucle no haga click. Se toca mientras una emisora de Spotify empieza a sonar."""
    import random
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    total = int(segundos * _FRECUENCIA)
    azar = random.Random(4)                       # siempre la misma estática
    bajo = 0.0
    crudo = []
    for _ in range(total):
        blanco = azar.uniform(-1.0, 1.0)
        bajo = 0.92 * bajo + 0.08 * blanco         # algo de grave: menos "siseo" y más "radio"
        crudo.append(0.55 * blanco + 0.45 * bajo * 4)
    rms = math.sqrt(sum(x * x for x in crudo) / total)
    escala = 10 ** (-24 / 20) / rms
    fundido = int(0.03 * _FRECUENCIA)
    muestras = []
    for i, x in enumerate(crudo):
        envolvente = min(1.0, i / fundido, (total - 1 - i) / fundido)
        muestras.append(max(-32767, min(32767, int(x * escala * envolvente * 32767))))
    with wave.open(str(ruta), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(_FRECUENCIA)
        w.writeframes(struct.pack(f"<{total}h", *muestras))
    return ruta

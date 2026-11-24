import importlib.util
import math
import struct
from pathlib import Path

import pytest

_RUTA = Path(__file__).resolve().parent.parent / "scripts" / "herramientas" / "calibrar-spotify.py"
_spec = importlib.util.spec_from_file_location("calibrar_spotify", _RUTA)
calibrar = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(calibrar)


def pcm(amplitud, n=8000, silencio=0):
    muestras = [0] * silencio + [int(amplitud * 32767 * math.sin(2 * math.pi * 440 * i / 8000)) for i in range(n)]
    return struct.pack(f"<{len(muestras)}h", *muestras)


def test_nivel_de_un_seno_a_media_escala_es_unos_menos_9_db():
    assert calibrar.nivel_db(pcm(0.5)) == pytest.approx(-9.03, abs=0.1)


def test_el_silencio_no_cuenta_en_el_nivel():
    assert calibrar.nivel_db(pcm(0.5, silencio=8000)) == pytest.approx(calibrar.nivel_db(pcm(0.5)), abs=0.2)


def test_todo_silencio_no_tiene_nivel():
    assert calibrar.nivel_db(b"\x00\x00" * 8000) is None


@pytest.mark.parametrize("local, spotify, actual, esperado", [(-18.0, -22.0, 0.0, 4.0), (-18.0, -15.2, 0.0, -3.0),
                                                              (-18.0, -20.0, 3.0, 5.0), (-10.0, -60.0, 0.0, 30.0)])
def test_ajuste_sugerido(local, spotify, actual, esperado):
    assert calibrar.sugerir_ajuste(local, spotify, actual) == esperado

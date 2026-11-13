import os
import subprocess
import sys
from itertools import islice
from pathlib import Path

import pytest

from cassette_fm.agenda import EPOCA, orden_ciclo, secuencia
from cassette_fm.biblioteca import Estacion, Pista


def estacion(duraciones, nombre="E"):
    return Estacion(nombre, tuple(
        Pista(Path(f"/m/{i}.mp3"), d, f"t{i}") for i, d in enumerate(duraciones)))


E = estacion([100, 200, 150, 120, 80])
L = sum(p.duracion for p in E.pistas)


def test_en_la_epoca_suena_la_primera_del_ciclo_0_desde_cero():
    pista, desde = next(secuencia(E, EPOCA))
    assert pista == orden_ciclo(E, 0)[0]
    assert desde == pytest.approx(0.0)


def test_desplazamiento_dentro_de_la_segunda_pista():
    o = orden_ciclo(E, 0)
    pista, desde = next(secuencia(E, EPOCA + o[0].duracion + 10))
    assert pista == o[1]
    assert desde == pytest.approx(10.0)


def test_ciclo_siguiente():
    pista, desde = next(secuencia(E, EPOCA + L + 5))
    assert pista == orden_ciclo(E, 1)[0]
    assert desde == pytest.approx(5.0)


def test_instante_anterior_a_la_epoca():
    ultima = orden_ciclo(E, -1)[-1]
    pista, desde = next(secuencia(E, EPOCA - 1))
    assert pista == ultima
    assert desde == pytest.approx(ultima.duracion - 1)


def test_siguientes_arrancan_en_cero_y_cruzan_ciclo():
    o0, o1, o2 = (orden_ciclo(E, k) for k in range(3))
    obtenido = list(islice(secuencia(E, EPOCA + L - 1), 7))
    esperado = [(o0[-1], o0[-1].duracion - 1)] + [(p, 0.0) for p in o1] + [(o2[0], 0.0)]
    assert [p for p, _ in obtenido] == [p for p, _ in esperado]
    assert [d for _, d in obtenido] == pytest.approx([d for _, d in esperado])


def test_orden_ciclo_es_permutacion():
    assert sorted(orden_ciclo(E, 7), key=lambda p: str(p.ruta)) == sorted(
        E.pistas, key=lambda p: str(p.ruta))


def test_independiente_del_orden_de_entrada():
    desordenada = Estacion(E.nombre, tuple(reversed(E.pistas)))
    assert orden_ciclo(desordenada, 3) == orden_ciclo(E, 3)


def test_determinista_entre_procesos():
    codigo = (
        "from pathlib import Path\n"
        "from cassette_fm.agenda import orden_ciclo\n"
        "from cassette_fm.biblioteca import Estacion, Pista\n"
        "e = Estacion('E', tuple(Pista(Path(f'/m/{i}.mp3'), d, f't{i}')"
        " for i, d in enumerate([100, 200, 150, 120, 80])))\n"
        "print([str(p.ruta) for p in orden_ciclo(e, 5)])\n"
    )
    esperado = str([str(p.ruta) for p in orden_ciclo(E, 5)])
    for semilla in ("1", "2"):
        out = subprocess.run([sys.executable, "-I", "-c", codigo], capture_output=True,
                             text=True, check=True, env={**os.environ, "PYTHONHASHSEED": semilla})
        assert out.stdout.strip() == esperado


@pytest.mark.parametrize("n", [2, 3, 5])
def test_no_repite_tema_en_el_borde_de_ciclo(n):
    e = estacion([60 + i for i in range(n)])
    for k in range(-50, 200):
        assert orden_ciclo(e, k)[-1] != orden_ciclo(e, k + 1)[0]


def test_estacion_de_una_pista():
    e = estacion([100])
    pista, desde = next(secuencia(e, EPOCA + 250))
    assert pista == e.pistas[0]
    assert desde == pytest.approx(50.0)
    assert [p for p, _ in islice(secuencia(e, EPOCA), 3)] == [e.pistas[0]] * 3


def test_estacion_vacia_da_error():
    with pytest.raises(ValueError):
        next(secuencia(Estacion("V", ()), EPOCA))

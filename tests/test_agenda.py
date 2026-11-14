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


def test_el_desplazamiento_nunca_es_negativo_en_los_bordes():
    for duraciones in ([123.456, 78.9, 201.3], [100.1, 200.2, 150.3, 99.9, 80.7]):
        e = estacion(duraciones)
        total = sum(p.duracion for p in e.pistas)
        for k in range(1, 3000):
            _, desde = next(secuencia(e, EPOCA + k * total))
            assert desde >= 0.0


# --- transiciones y desfase (Etapa 3) ---

from cassette_fm.agenda import desfase, transiciones  # noqa: E402


def test_transiciones_son_posteriores_y_acumulan_duraciones():
    t = EPOCA + 123.0
    (p, d), (s1, _), (s2, _) = list(islice(secuencia(E, t), 3))
    (u1, ini1), (u2, ini2) = list(islice(transiciones(E, t), 2))
    assert u1 == s1 and u2 == s2
    assert ini1 == pytest.approx(t + (p.duracion - d))
    assert ini2 == pytest.approx(ini1 + s1.duracion)
    assert ini1 > t


def test_transiciones_cruzan_ciclos():
    inicios = [i for _, i in islice(transiciones(E, EPOCA + 5), 12)]
    assert all(b > a for a, b in zip(inicios, inicios[1:]))
    assert len(inicios) == 12


def _inicio_de(estacion, instante, n=0):
    return list(islice(transiciones(estacion, instante), n + 1))[n]


def test_desfase_en_el_inicio_exacto_es_cero():
    pista, inicio = _inicio_de(E, EPOCA + 40)
    assert desfase(E, pista, inicio) == pytest.approx(0.0, abs=1e-6)


def test_desfase_positivo_si_la_agenda_ya_avanzo():
    pista, inicio = _inicio_de(E, EPOCA + 40)
    assert desfase(E, pista, inicio + 3) == pytest.approx(3.0)


def test_desfase_negativo_si_la_real_va_adelantada():
    pista, inicio = _inicio_de(E, EPOCA + 40)
    assert desfase(E, pista, inicio - 2) == pytest.approx(-2.0)


def test_desfase_none_si_no_coincide():
    pista, inicio = _inicio_de(E, EPOCA + 40)
    actual = next(secuencia(E, inicio - 2))[0]
    siguiente2, _ = _inicio_de(E, EPOCA + 40, 1)
    otra = next(p for p in E.pistas if p not in (pista, actual))
    assert desfase(E, otra, inicio - 2) is None


def test_desfase_estacion_de_un_tema_elige_el_menor():
    e = estacion([100])
    assert desfase(e, e.pistas[0], EPOCA + 103) == pytest.approx(3.0)
    assert desfase(e, e.pistas[0], EPOCA + 97) == pytest.approx(-3.0)

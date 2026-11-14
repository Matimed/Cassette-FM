import random
from collections import Counter

import pytest

from cassette_fm.dj.config import PESOS_POR_DEFECTO
from cassette_fm.dj.selector import elegir_ingredientes

TODOS = {"cancion", *PESOS_POR_DEFECTO}


def correr(n=5000, **kw):
    azar = random.Random(1)
    kw.setdefault("disponibles", TODOS)
    kw.setdefault("pesos", PESOS_POR_DEFECTO)
    kw.setdefault("recientes", [])
    return [elegir_ingredientes(azar=azar, **kw) for _ in range(n)]


def test_siempre_incluye_la_cancion_primero():
    assert all(r[0] == "cancion" for r in correr(500))


@pytest.mark.parametrize("maximo", [1, 2, 3])
def test_nunca_pasa_del_maximo(maximo):
    resultados = correr(1000, maximo=maximo, pesos={k: 1.0 for k in PESOS_POR_DEFECTO})
    assert max(len(r) for r in resultados) == maximo and all(len(set(r)) == len(r) for r in resultados)


def test_solo_elige_entre_los_disponibles():
    vistos = {i for r in correr(1000, disponibles={"cancion", "hora", "clima"}, maximo=9) for i in r}
    assert vistos == {"cancion", "hora", "clima"}


def test_frecuencias_cercanas_a_los_pesos():
    cuenta = Counter(i for r in correr(5000, maximo=9) for i in r)
    for nombre, peso in PESOS_POR_DEFECTO.items():
        assert cuenta[nombre] / 5000 == pytest.approx(peso, abs=0.05), nombre


def test_la_penalizacion_baja_lo_reciente():
    cuenta = Counter(i for r in correr(5000, maximo=9, recientes=["hora", "hora"]) for i in r)
    assert cuenta["hora"] / 5000 == pytest.approx(0.35 * 0.09, abs=0.02)
    assert cuenta["estacion"] / 5000 == pytest.approx(0.5, abs=0.05)


def test_la_penalizacion_configurable():
    cuenta = Counter(i for r in correr(5000, maximo=9, recientes=["hora"], penalizacion=0.0) for i in r)
    assert cuenta["hora"] == 0


def test_con_recientes_saturado_igual_devuelve_la_cancion():
    saturado = list(PESOS_POR_DEFECTO) * 10
    resultados = correr(300, recientes=saturado)
    assert all(r[0] == "cancion" for r in resultados)


def test_pesos_en_cero_no_se_ofrecen():
    pesos = dict(PESOS_POR_DEFECTO, clima=0.0, dato=0.0)
    vistos = {i for r in correr(2000, pesos=pesos, maximo=9) for i in r}
    assert "clima" not in vistos and "dato" not in vistos


def test_ingrediente_desconocido_sin_peso_no_se_ofrece():
    vistos = {i for r in correr(500, disponibles={"cancion", "raro"}, maximo=9) for i in r}
    assert vistos == {"cancion"}


def test_cuando_hay_mas_ofrecidos_que_lugares_se_prioriza_por_peso():
    pesos = {"hora": 1.0, "clima": 1.0, "dato": 1.0, "album": 0.05}
    cuenta = Counter(i for r in correr(2000, pesos=pesos, disponibles={"cancion", *pesos}, maximo=2) for i in r)
    assert cuenta["album"] < 200 and cuenta["hora"] > 500 and cuenta["clima"] > 500


def test_es_determinista_con_la_misma_semilla():
    a = correr(50)
    assert a == correr(50)

import threading

import pytest

from cassette_fm.dj.modo import MODOS, ModoDJ


def test_arranca_con_el_inicial():
    assert ModoDJ().actual() == "plantillas" and ModoDJ("llm").actual() == "llm"
    assert MODOS == ("plantillas", "llm")


def test_poner_cambia_y_devuelve():
    m = ModoDJ()
    assert m.poner("llm") == "llm" and m.actual() == "llm"
    assert m.poner("plantillas") == "plantillas" and m.actual() == "plantillas"


@pytest.mark.parametrize("malo", ["otro", "", "LLM", None, 3])
def test_modo_invalido_da_ValueError_y_no_cambia(malo):
    m = ModoDJ("llm")
    with pytest.raises(ValueError):
        m.poner(malo)
    assert m.actual() == "llm"
    with pytest.raises(ValueError):
        ModoDJ(malo)


def test_es_seguro_con_hilos():
    m = ModoDJ()

    def alternar():
        for i in range(500):
            m.poner(MODOS[i % 2])
            assert m.actual() in MODOS

    hilos = [threading.Thread(target=alternar) for _ in range(8)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join()
    assert m.actual() in MODOS

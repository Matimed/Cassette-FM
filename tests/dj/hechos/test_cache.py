import sqlite3
import threading
import time

import pytest

from cassette_fm.dj.hechos.cache import CacheHechos


class Reloj:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def test_guarda_y_devuelve(tmp_path):
    c = CacheHechos(tmp_path / "h.sqlite")
    assert c.obtener("a") == (False, None)
    c.guardar("a", {"x": [1, 2]}, 60)
    assert c.obtener("a") == (True, {"x": [1, 2]})


def test_vence_con_el_reloj(tmp_path):
    r = Reloj()
    c = CacheHechos(tmp_path / "h.sqlite", r)
    c.guardar("a", 5, 60)
    r.t += 59
    assert c.obtener("a") == (True, 5)
    r.t += 2
    assert c.obtener("a") == (False, None)


def test_sin_dato_se_cachea_y_se_distingue_de_ausente(tmp_path):
    c = CacheHechos(tmp_path / "h.sqlite")
    c.guardar("a", None, 60)
    assert c.obtener("a") == (True, None) and c.obtener("b") == (False, None)


def test_persiste_entre_instancias(tmp_path):
    CacheHechos(tmp_path / "h.sqlite").guardar("a", "hola", 60)
    assert CacheHechos(tmp_path / "h.sqlite").obtener("a") == (True, "hola")


def test_consultar_llama_a_buscar_una_sola_vez_con_hilos(tmp_path):
    c = CacheHechos(tmp_path / "h.sqlite")
    llamadas = []

    def buscar():
        llamadas.append(1)
        time.sleep(0.2)
        return {"v": 1}

    resultados = []
    hilos = [threading.Thread(target=lambda: resultados.append(c.consultar("k", lambda v: 60, buscar)))
             for _ in range(8)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join()
    assert len(llamadas) == 1 and resultados == [{"v": 1}] * 8


def test_consultar_usa_la_vigencia_segun_el_valor(tmp_path):
    r = Reloj()
    c = CacheHechos(tmp_path / "h.sqlite", r)
    c.consultar("k", lambda v: 10 if v is None else 100, lambda: None)
    r.t += 11
    assert c.obtener("k") == (False, None)
    c.consultar("k", lambda v: 10 if v is None else 100, lambda: 7)
    r.t += 11
    assert c.obtener("k") == (True, 7)


def test_si_buscar_lanza_no_guarda(tmp_path):
    c = CacheHechos(tmp_path / "h.sqlite")
    with pytest.raises(RuntimeError):
        c.consultar("k", lambda v: 60, lambda: (_ for _ in ()).throw(RuntimeError("x")))
    assert c.obtener("k") == (False, None)


def test_base_corrupta_sigue_en_memoria_y_avisa_una_vez(tmp_path, caplog):
    archivo = tmp_path / "h.sqlite"
    archivo.write_bytes(b"esto no es una base de datos" * 100)
    with caplog.at_level("WARNING", logger="cassette_fm"):
        c = CacheHechos(archivo)
        c.guardar("a", 1, 60)
        c.guardar("b", 2, 60)
        assert c.obtener("a") == (True, 1)
    assert len([r for r in caplog.records if r.levelname == "WARNING"]) == 1


def test_directorio_no_escribible_sigue_en_memoria(tmp_path):
    solo_lectura = tmp_path / "ro"
    solo_lectura.mkdir()
    solo_lectura.chmod(0o500)
    try:
        c = CacheHechos(solo_lectura / "sub" / "h.sqlite")
        c.guardar("a", 1, 60)
        assert c.obtener("a") == (True, 1)
    finally:
        solo_lectura.chmod(0o700)


def test_archivo_none_es_memoria():
    c = CacheHechos(None)
    c.guardar("a", 1, 60)
    assert c.obtener("a") == (True, 1)


def test_las_vencidas_se_borran_de_la_base(tmp_path):
    r = Reloj()
    archivo = tmp_path / "h.sqlite"
    c = CacheHechos(archivo, r)
    c.guardar("a", 1, 10)
    r.t += 11
    c.obtener("a")
    assert sqlite3.connect(archivo).execute("select count(*) from hechos").fetchone()[0] == 0

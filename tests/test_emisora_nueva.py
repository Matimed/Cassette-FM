import json
import random

import pytest

from cassette_fm.config import ErrorConfig
from cassette_fm.emisora_nueva import (Eleccion, buscar, chequear_nombre, describir, elegir_voz, escribir, guardar,
                                       idioma_de_voz, leer_crudo, voces_disponibles, voces_en_uso)

ALIAS = {"puck": "am_puck", "sarah": "af_sarah", "dora": "ef_dora", "daniela": "piper:es_AR-daniela-high",
         "alex_santa": "em_alex+em_santa", "emma": "bf_emma", "siwis": "ff_siwis"}


@pytest.mark.parametrize("voz,idioma", [
    ("am_puck", "en"), ("af_sarah", "en"), ("bf_emma", "en-gb"), ("ef_dora", "es"), ("em_alex+em_santa", "es"),
    ("piper:es_AR-daniela-high", "es"), ("piper:en_GB-alba-medium", "en-gb"), ("piper:en_US-amy-low", "en"),
    ("ff_siwis", None), ("raro", None)])
def test_idioma_de_voz(voz, idioma):
    assert idioma_de_voz(voz) == idioma


def test_elige_un_alias_libre_al_azar():
    vistas = {elegir_voz(ALIAS, ["puck", "dora", "daniela", "alex_santa"], azar=random.Random(s)).voz
              for s in range(20)}
    assert vistas == {"sarah", "emma"}
    assert elegir_voz(ALIAS, ["puck"], azar=random.Random(1)).repetida is False


def test_filtra_por_idioma():
    e = elegir_voz(ALIAS, ["dora"], idioma="es", azar=random.Random(1))
    assert e.voz in {"daniela", "alex_santa"} and e.idioma == "es" and not e.repetida


def test_en_ingles_acepta_en_gb():
    assert elegir_voz(ALIAS, ["puck", "sarah"], idioma="en") == Eleccion("emma", "en-gb", False)


def test_todas_en_uso_repite_la_menos_usada():
    en_uso = ["puck", "puck", "emma", "emma", "sarah"]
    assert elegir_voz(ALIAS, en_uso, idioma="en") == Eleccion("sarah", "en", True)


def test_voz_elegida_da_su_idioma():
    assert elegir_voz(ALIAS, ["dora"], voz="dora") == Eleccion("dora", "es", False)


def test_voz_cruda_sin_alias():
    assert elegir_voz(ALIAS, [], voz="am_onyx") == Eleccion("am_onyx", "en", False)


def test_voz_que_no_coincide_con_el_idioma_es_error():
    with pytest.raises(ErrorConfig, match="dora"):
        elegir_voz(ALIAS, [], idioma="en", voz="dora")


@pytest.mark.parametrize("voz", ["siwis", "nadie"])
def test_voz_inexistente_o_de_otro_idioma_es_error(voz):
    with pytest.raises(ErrorConfig, match="sarah"):         # el error lista los alias que sirven
        elegir_voz(ALIAS, [], voz=voz)


def test_sin_alias_es_error():
    with pytest.raises(ErrorConfig, match=r"\[voces\]"):
        elegir_voz({}, [])


@pytest.mark.parametrize("contenido", ["{", "{}", None])
def test_leer_crudo_roto_o_inexistente_es_error(tmp_path, contenido):
    archivo = tmp_path / "estaciones.json"
    if contenido is not None:
        archivo.write_text(contenido)
    with pytest.raises(ErrorConfig, match="estaciones.json"):
        leer_crudo(archivo)


def test_chequear_nombre_repetido_sin_mayusculas_ni_espacios():
    emisoras = [{"nombre": "Happy Eighties"}]
    with pytest.raises(ErrorConfig, match="Happy Eighties"):
        chequear_nombre(emisoras, " happy eighties ")
    with pytest.raises(ErrorConfig):
        chequear_nombre(emisoras, "   ")
    assert chequear_nombre(emisoras, "  Nueva  ") == "Nueva"


def test_voces_en_uso():
    emisoras = [{"nombre": "A", "dj": {"voz": "puck"}}, {"nombre": "B"}, {"nombre": "C", "dj": {"idioma": "es"}}]
    assert voces_en_uso(emisoras) == ["puck"]


def test_voces_disponibles_con_idioma_y_emisoras_que_las_usan():
    emisoras = [{"nombre": " Sing ", "dj": {"voz": "dora"}}, {"nombre": "Otra", "dj": {"voz": "dora"}},
                {"nombre": "Sin DJ"}]
    assert voces_disponibles(ALIAS, emisoras) == [
        {"alias": "puck", "voz": "am_puck", "idioma": "en", "emisoras": []},
        {"alias": "sarah", "voz": "af_sarah", "idioma": "en", "emisoras": []},
        {"alias": "dora", "voz": "ef_dora", "idioma": "es", "emisoras": ["Sing", "Otra"]},
        {"alias": "daniela", "voz": "piper:es_AR-daniela-high", "idioma": "es", "emisoras": []},
        {"alias": "alex_santa", "voz": "em_alex+em_santa", "idioma": "es", "emisoras": []},
        {"alias": "emma", "voz": "bf_emma", "idioma": "en-gb", "emisoras": []}]     # siwis (francés) no sirve


def test_guardar_agrega_al_final_y_es_json_legible(tmp_path):
    archivo = tmp_path / "estaciones.json"
    viejas = [{"nombre": "Más Gasolina F.M.", "fuente": {"spotify": "x"}}]
    archivo.write_text(json.dumps(viejas))
    nueva = {"nombre": "Nueva", "fuente": {"spotify": "y"}, "dj": {"idioma": "es", "voz": "dora"}}
    guardar(archivo, leer_crudo(archivo), nueva)
    texto = archivo.read_text(encoding="utf-8")
    assert json.loads(texto) == viejas + [nueva] and "Más" in texto and texto.endswith("\n")
    assert not list(tmp_path.glob("*.tmp"))


def test_buscar_sin_mayusculas_ni_espacios():
    emisoras = [{"nombre": "Happy Eighties"}, {"nombre": " Más Gasolina F.M. "}]
    assert buscar(emisoras, "  más gasolina f.m.") == 1
    with pytest.raises(ErrorConfig, match="Happy Eighties"):
        buscar(emisoras, "Sing")


def test_describir():
    assert describir({"fuente": {"spotify": "x"}}) == "Spotify"
    assert describir({"fuente": {"carpeta": "/m/Rock"}}) == "carpeta /m/Rock"
    assert describir({}) == "fuente desconocida"


def test_escribir_la_lista_tal_cual(tmp_path):
    archivo = tmp_path / "estaciones.json"
    escribir(archivo, [{"nombre": "Más"}])
    assert json.loads(archivo.read_text(encoding="utf-8")) == [{"nombre": "Más"}] and "Más" in archivo.read_text()

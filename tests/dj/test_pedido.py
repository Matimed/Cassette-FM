import copy
from datetime import datetime, timedelta

import pytest

from cassette_fm.dj.pedido import IDIOMAS, Pedido, Tema, leer_pedido


def pedido_valido():
    return {
        "id": "abc-123_X",
        "estacion": "Lentos",
        "idioma": "es",
        "voz": "em_santa",
        "personalidad": "baladas de los 80",
        "momento": "2026-11-13T21:47:00-03:00",
        "anterior": {"artista": "Whitesnake", "titulo": "Is This Love", "album": "Slip of the Tongue", "isrc": "GBAAA8700001"},
        "siguiente": {"artista": "Foreigner", "titulo": "Waiting for a Girl Like You"},
        "recientes": ["hora", "cancion"],
        "duracion_maxima_segundos": 12,
    }


def test_pedido_completo():
    p = leer_pedido(pedido_valido())
    assert isinstance(p, Pedido)
    assert (p.id, p.estacion, p.idioma, p.voz, p.personalidad) == ("abc-123_X", "Lentos", "es", "em_santa", "baladas de los 80")
    assert p.momento == datetime.fromisoformat("2026-11-13T21:47:00-03:00")
    assert p.momento.utcoffset() == timedelta(hours=-3)
    assert p.anterior == Tema("Whitesnake", "Is This Love", "Slip of the Tongue", "GBAAA8700001")
    assert p.siguiente == Tema("Foreigner", "Waiting for a Girl Like You", None, None)
    assert p.recientes == ("hora", "cancion") and p.duracion_maxima_segundos == 12.0
    assert p.lang == "es"


def test_pedido_minimo():
    d = pedido_valido()
    for k in ("anterior", "recientes", "personalidad", "duracion_maxima_segundos"):
        d.pop(k)
    p = leer_pedido(d)
    assert p.anterior is None and p.recientes == () and p.personalidad == "" and p.duracion_maxima_segundos is None


def test_anterior_null_vale():
    d = pedido_valido()
    d["anterior"] = None
    assert leer_pedido(d).anterior is None


@pytest.mark.parametrize("idioma,lang", [("es", "es"), ("en", "en-us"), ("en-us", "en-us"), ("en-gb", "en-gb")])
def test_idiomas(idioma, lang):
    d = pedido_valido()
    d["idioma"] = idioma
    assert leer_pedido(d).lang == lang == IDIOMAS[idioma]


def test_los_textos_se_recortan_y_limitan():
    d = pedido_valido()
    d["estacion"] = "  Lentos  "
    d["siguiente"]["titulo"] = "x" * 500
    p = leer_pedido(d)
    assert p.estacion == "Lentos" and len(p.siguiente.titulo) == 300


def test_ignora_campos_desconocidos():
    d = pedido_valido()
    d["otra_cosa"] = {"x": 1}
    d["siguiente"]["tambien"] = 5
    leer_pedido(d)


@pytest.mark.parametrize("campo", ["id", "estacion", "idioma", "voz", "momento", "siguiente"])
def test_faltan_campos_obligatorios(campo):
    d = pedido_valido()
    d.pop(campo)
    with pytest.raises(ValueError) as exc:
        leer_pedido(d)
    assert campo in str(exc.value)


@pytest.mark.parametrize("campo", ["artista", "titulo"])
def test_el_tema_exige_artista_y_titulo(campo):
    d = pedido_valido()
    d["siguiente"].pop(campo)
    with pytest.raises(ValueError) as exc:
        leer_pedido(d)
    assert campo in str(exc.value)
    d = pedido_valido()
    d["siguiente"][campo] = "   "
    with pytest.raises(ValueError):
        leer_pedido(d)


@pytest.mark.parametrize("campo,valor", [
    ("estacion", 5), ("voz", ["x"]), ("recientes", ["ok", 3]), ("recientes", "hora"), ("siguiente", "texto"),
    ("anterior", 7), ("duracion_maxima_segundos", True), ("duracion_maxima_segundos", 0),
    ("duracion_maxima_segundos", -5), ("duracion_maxima_segundos", "10"), ("idioma", "fr"), ("idioma", 3),
    ("personalidad", 9),
])
def test_tipos_invalidos(campo, valor):
    d = pedido_valido()
    d[campo] = valor
    with pytest.raises(ValueError) as exc:
        leer_pedido(d)
    assert campo in str(exc.value)


@pytest.mark.parametrize("momento", ["2026-11-13T21:47:00", "ayer", "", 5, None])
def test_momento_sin_zona_o_invalido_falla(momento):
    d = pedido_valido()
    d["momento"] = momento
    with pytest.raises(ValueError) as exc:
        leer_pedido(d)
    assert "momento" in str(exc.value)


@pytest.mark.parametrize("id_", ["../x", "a/b", "", "a b", "x" * 65, "é", ".hidden", "a\\b", "x\n", "a.wav"])
def test_id_peligroso_falla(id_):
    d = pedido_valido()
    d["id"] = id_
    with pytest.raises(ValueError) as exc:
        leer_pedido(d)
    assert "id" in str(exc.value)


@pytest.mark.parametrize("voz", ["../voz", "a b", "", "x/y"])
def test_voz_invalida_falla(voz):
    d = pedido_valido()
    d["voz"] = voz
    with pytest.raises(ValueError) as exc:
        leer_pedido(d)
    assert "voz" in str(exc.value)


def test_voz_con_mezcla_vale():
    d = pedido_valido()
    d["voz"] = "em_santa+em_alex"
    assert leer_pedido(d).voz == "em_santa+em_alex"


@pytest.mark.parametrize("datos", [[], "texto", None, 5])
def test_no_es_un_objeto_falla(datos):
    with pytest.raises(ValueError):
        leer_pedido(datos)


def test_no_modifica_la_entrada():
    d = pedido_valido()
    copia = copy.deepcopy(d)
    leer_pedido(d)
    assert d == copia


@pytest.mark.parametrize("donde,campo", [("siguiente", "artista"), ("siguiente", "titulo"), ("anterior", "titulo")])
@pytest.mark.parametrize("basura", ['""', "{}", "“”", " {} \"\" "])
def test_un_nombre_que_queda_vacio_al_limpiarlo_se_rechaza_con_su_campo(donde, campo, basura):
    d = pedido_valido()
    d[donde][campo] = basura
    with pytest.raises(ValueError) as exc:
        leer_pedido(d)
    assert f"{donde}.{campo}" in str(exc.value)


def test_estacion_que_queda_vacia_al_limpiarla_se_rechaza():
    d = pedido_valido()
    d["estacion"] = "{}"
    with pytest.raises(ValueError) as exc:
        leer_pedido(d)
    assert "estacion" in str(exc.value)


def test_velocidad_opcional_y_validada():
    d = pedido_valido()
    assert leer_pedido(d).velocidad is None
    d["velocidad"] = 1.15
    assert leer_pedido(d).velocidad == 1.15
    for malo in (0.3, 2.5, "rápido", True, float("nan")):
        d["velocidad"] = malo
        with pytest.raises(ValueError, match="velocidad"):
            leer_pedido(d)

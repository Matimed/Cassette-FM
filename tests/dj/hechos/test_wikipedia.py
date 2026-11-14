import logging
import urllib.parse

import pytest

from cassette_fm.dj.config import ConfigServicioDJ
from cassette_fm.dj.hechos.cache import CacheHechos
from cassette_fm.dj.hechos.wikipedia import ClienteWikipedia, Resumen

EXTRACTO = ("A-ha es una banda noruega de pop rock, formada en Oslo el 14 de septiembre de 1982. "
            "El grupo está compuesto por Morten Harket como vocalista, Magne Furuholmen en los teclados y Paul "
            "Waaktaar-Savoy en la guitarra. El trío saltó a la fama mundial gracias a su álbum debut, lanzado en 1985. "
            "Han vendido alrededor de 100 millones de álbumes y singles en todo el mundo.")


class Reloj:
    def __init__(self):
        self.t = 1_000_000.0

    def __call__(self):
        return self.t


def sitelinks(**idiomas):
    return {"entities": {"Q156305": {"sitelinks": {f"{k}wiki": {"site": f"{k}wiki", "title": v}
                                                    for k, v in idiomas.items()}}}}


def resumen_json(extracto=EXTRACTO, tipo="standard", titulo="A-ha"):
    return {"type": tipo, "title": titulo, "extract": extracto,
            "content_urls": {"desktop": {"page": f"https://es.wikipedia.org/wiki/{titulo}"}}}


def montar(servidor, **cfg):
    cfg.setdefault("contacto", "dj@example.com")
    config = ConfigServicioDJ(wikidata_url=servidor.url + "/w", wikipedia_url=servidor.url + "/{idioma}",
                              timeout_hechos_segundos=1.0, **cfg)
    r = Reloj()
    return ClienteWikipedia(config, CacheHechos(None, r), "9.9"), r


def test_resumen_del_artista_en_el_idioma_pedido(servidor_http):
    servidor_http.responder("/w", sitelinks(es="A-ha", en="A-ha"))
    servidor_http.responder("/es/api/rest_v1/page/summary/A-ha", resumen_json())
    c, _ = montar(servidor_http)
    res = c.resumen("Q156305", ["es", "en"])
    assert isinstance(res, Resumen) and res.idioma == "es" and res.titulo == "A-ha"
    assert res.texto.startswith("A-ha es una banda noruega") and res.url == "https://es.wikipedia.org/wiki/A-ha"
    assert "sitefilter=eswiki%7Cenwiki" in servidor_http.pedidos[0][0] or "sitefilter=eswiki|enwiki" in servidor_http.pedidos[0][0]


def test_si_no_hay_articulo_en_el_primer_idioma_usa_el_ingles(servidor_http):
    servidor_http.responder("/w", sitelinks(en="Lil Uzi Vert"))
    servidor_http.responder("/en/api/rest_v1/page/summary/Lil%20Uzi%20Vert",
                            resumen_json("Lil Uzi Vert is an American rapper.", titulo="Lil Uzi Vert"))
    c, _ = montar(servidor_http)
    res = c.resumen("Q156305", ["es", "en"])
    assert res.idioma == "en" and res.texto == "Lil Uzi Vert is an American rapper."


def test_sin_articulo_en_ninguno_da_None(servidor_http):
    servidor_http.responder("/w", sitelinks())
    c, _ = montar(servidor_http)
    assert c.resumen("Q156305", ["es", "en"]) is None


@pytest.mark.parametrize("cuerpo", [resumen_json(tipo="disambiguation"), resumen_json(extracto=""),
                                    resumen_json(extracto="   "), resumen_json(tipo="no-extract"),
                                    {"type": "standard", "title": "X"}])
def test_una_pagina_que_no_sirve_no_da_resumen(servidor_http, cuerpo):
    servidor_http.responder("/w", sitelinks(es="A-ha"))
    servidor_http.responder("/es/api/rest_v1/page/summary/", cuerpo)
    c, _ = montar(servidor_http)
    assert c.resumen("Q156305", ["es"]) is None


def test_recorta_en_fin_de_oracion(servidor_http):
    servidor_http.responder("/w", sitelinks(es="A-ha"))
    servidor_http.responder("/es/api/rest_v1/page/summary/", resumen_json())
    c, _ = montar(servidor_http, wikipedia_palabras_maximas=40)
    texto = c.resumen("Q156305", ["es"]).texto
    assert texto.endswith(".") and len(texto.split()) <= 40 and texto.startswith("A-ha es una banda noruega")
    assert "vendido" not in texto and "Han vendido" not in texto


def test_primera_oracion_muy_larga_se_corta_en_palabras(servidor_http):
    larga = "Palabra " * 200 + "final."
    servidor_http.responder("/w", sitelinks(es="A-ha"))
    servidor_http.responder("/es/api/rest_v1/page/summary/", resumen_json(larga))
    c, _ = montar(servidor_http, wikipedia_palabras_maximas=30)
    texto = c.resumen("Q156305", ["es"]).texto
    assert len(texto.split()) == 30 and texto.endswith(".")


def test_titulo_con_espacios_barras_y_acentos_va_codificado(servidor_http):
    servidor_http.responder("/w", sitelinks(es="AC/DC (grupo) Ñandú"))
    servidor_http.responder("/es/api/rest_v1/page/summary/", resumen_json())
    c, _ = montar(servidor_http)
    c.resumen("Q156305", ["es"])
    ruta = servidor_http.pedidos[1][0]
    assert ruta == "/es/api/rest_v1/page/summary/" + urllib.parse.quote("AC/DC (grupo) Ñandú", safe="")


@pytest.mark.parametrize("q", ["", "156305", "Q", "Q1; drop", "../x", "q156305", None])
def test_qid_invalido_no_hace_pedidos(servidor_http, q):
    c, _ = montar(servidor_http)
    assert c.resumen(q, ["es"]) is None and servidor_http.pedidos == []


def test_sin_contacto_no_hace_pedidos(servidor_http):
    c, _ = montar(servidor_http, contacto="")
    assert c.resumen("Q156305", ["es"]) is None and servidor_http.pedidos == []


def test_cache(servidor_http):
    servidor_http.responder("/w", sitelinks(es="A-ha"))
    servidor_http.responder("/es/api/rest_v1/page/summary/", resumen_json())
    c, r = montar(servidor_http)
    assert c.resumen("Q156305", ["es"]) == c.resumen("Q156305", ["es"])
    assert len(servidor_http.pedidos) == 2
    servidor_http.reglas.clear()
    servidor_http.responder("/w", sitelinks())
    assert c.resumen("Q999", ["es"]) is None and c.resumen("Q999", ["es"]) is None   # "sin dato" cacheado
    assert len(servidor_http.pedidos) == 3


@pytest.mark.parametrize("codigo, cuerpo, tipo", [(404, "no", "text/plain"), (503, "no", "text/plain"),
                                                  (200, "<html>", "text/html"), (200, {"sin": "entities"}, "application/json"),
                                                  (200, {"entities": {"Q156305": {}}}, "application/json"),
                                                  (200, {"entities": {"Q156305": {"sitelinks": "mal"}}}, "application/json")])
def test_errores_y_basura_dan_None_con_un_solo_aviso(servidor_http, codigo, cuerpo, tipo, caplog):
    servidor_http.responder("/w", cuerpo, codigo=codigo, tipo=tipo)
    c, r = montar(servidor_http)
    with caplog.at_level(logging.WARNING, logger="cassette_fm"):
        assert c.resumen("Q156305", ["es"]) is None
        r.t += 11 * 60
        assert c.resumen("Q156305", ["es"]) is None
    assert len([x for x in caplog.records if x.levelno == logging.WARNING]) <= 1


def test_timeout_da_None(servidor_http):
    servidor_http.responder("/w", sitelinks(es="A-ha"), demora=1.5)
    c, _ = montar(servidor_http)
    assert c.resumen("Q156305", ["es"]) is None


def test_user_agent_con_el_contacto(servidor_http):
    servidor_http.responder("/w", sitelinks(es="A-ha"))
    servidor_http.responder("/es/api/rest_v1/page/summary/", resumen_json())
    c, _ = montar(servidor_http, contacto="yo@example.com")
    c.resumen("Q156305", ["es"])
    for _, headers in servidor_http.pedidos:
        assert headers["User-Agent"] == "cassette-dj/9.9 (yo@example.com)"


def test_si_la_pagina_es_de_otra_entidad_no_se_usa(servidor_http):
    servidor_http.responder("/w", sitelinks(es="A-ha", en="A-ha"))
    servidor_http.responder("/es/api/rest_v1/page/summary/", dict(resumen_json(), wikibase_item="Q999"))
    servidor_http.responder("/en/api/rest_v1/page/summary/", dict(resumen_json("A-ha is a band."), wikibase_item="Q156305"))
    c, _ = montar(servidor_http)
    res = c.resumen("Q156305", ["es", "en"])
    assert res.idioma == "en" and res.texto == "A-ha is a band."          # la de es apunta a otro Q: se descarta


def test_sin_wikibase_item_en_la_respuesta_se_acepta(servidor_http):
    servidor_http.responder("/w", sitelinks(es="A-ha"))
    servidor_http.responder("/es/api/rest_v1/page/summary/", resumen_json())
    c, _ = montar(servidor_http)
    assert c.resumen("Q156305", ["es"]) is not None

import json
import logging
import urllib.parse

import pytest

from cassette_fm.dj.config import ConfigServicioDJ
from cassette_fm.dj.hechos.cache import CacheHechos
from cassette_fm.dj.hechos.musicbrainz import ClienteMusicBrainz, DatosTema, normalizar

AHA = "7364dea6-0000-4000-8000-000000000001"
OTRO = "99999999-0000-4000-8000-000000000002"


class Reloj:
    def __init__(self):
        self.t = 1_000_000.0
        self.esperas = []

    def __call__(self):
        return self.t

    def dormir(self, s):
        self.esperas.append(s)
        self.t += s


def grabacion(titulo="Take On Me", artista="a-ha", id_=AHA, fecha=None, extra=None):
    r = {"id": "r-" + str(abs(hash((titulo, fecha, id_))) % 10 ** 6), "score": 100, "title": titulo,
         "artist-credit": [{"name": artista, "artist": {"id": id_, "name": artista}}], "releases": [{"title": "X"}]}
    if fecha is not None:
        r["first-release-date"] = fecha
    r.update(extra or {})
    return r


def artista_json(tipo="Group", pais="NO", inicio="1983"):
    return {"id": AHA, "name": "a‐ha", "type": tipo, "country": pais, "life-span": {"begin": inicio, "ended": False}}


def grupo(titulo="Take On Me", artista="a-ha", id_=AHA, fecha=None, tipo="Single"):
    g = {"id": "g-" + str(abs(hash((titulo, fecha, id_, tipo))) % 10 ** 6), "title": titulo, "primary-type": tipo,
         "artist-credit": [{"name": artista, "artist": {"id": id_, "name": artista}}]}
    if fecha is not None:
        g["first-release-date"] = fecha
    return g


def montar(servidor, tmp_path=None, grabaciones=None, artista=None, grupos=None, **cfg):
    cfg.setdefault("contacto", "dj@example.com")
    config = ConfigServicioDJ(musicbrainz_url=servidor.url + "/ws/2", timeout_hechos_segundos=1.0, **cfg)
    reloj = Reloj()
    cache = CacheHechos(None, reloj)
    if grabaciones is not None:
        servidor.responder("/ws/2/recording", {"count": len(grabaciones), "recordings": grabaciones})
    servidor.responder("/ws/2/release-group", {"count": len(grupos or []), "release-groups": grupos or []})
    servidor.responder(f"/ws/2/artist/{AHA}", artista if artista is not None else artista_json())
    return ClienteMusicBrainz(config, cache, reloj, reloj.dormir, version="9.9"), reloj


def test_take_on_me_da_1984_noruega_grupo_1983(servidor_http):
    c, _ = montar(servidor_http, grabaciones=[
        grabacion(fecha="2019"), grabacion("Take on Me", "a‐ha", fecha="2012-01-25"),
        grabacion(fecha="1984-10-19"), grabacion(fecha="2001"), grabacion(), grabacion(fecha="1985-05-23")])
    assert c.datos_del_tema("a-ha", "Take On Me") == DatosTema(
        1984, "NO", 1983, True, f"https://musicbrainz.org/artist/{AHA}")


def test_sin_contacto_no_consulta_y_avisa_una_vez(servidor_http, caplog):
    with caplog.at_level(logging.WARNING, logger="cassette_fm"):
        c, _ = montar(servidor_http, grabaciones=[grabacion(fecha="1984")], contacto="")
        assert c.datos_del_tema("a-ha", "Take On Me") is None
        assert c.datos_del_tema("a-ha", "Take On Me") is None
    assert servidor_http.pedidos == []
    assert len([r for r in caplog.records if r.levelno == logging.WARNING]) == 1


def test_el_user_agent_lleva_el_contacto(servidor_http):
    c, _ = montar(servidor_http, grabaciones=[grabacion(fecha="1984")], contacto="yo@example.com")
    c.datos_del_tema("a-ha", "Take On Me")
    for _, headers in servidor_http.pedidos:
        assert headers["User-Agent"] == "cassette-dj/9.9 (yo@example.com)"
        assert headers["Accept"] == "application/json"


def test_homonimo_de_otro_artista_no_se_usa(servidor_http):
    c, _ = montar(servidor_http, grabaciones=[grabacion("True", "Solange", OTRO, "2017")])
    assert c.datos_del_tema("Spandau Ballet", "True") is None


def test_dos_artistas_con_el_mismo_nombre_es_ambiguo(servidor_http):
    c, _ = montar(servidor_http, grabaciones=[grabacion(fecha="1984"), grabacion(id_=OTRO, fecha="1990")])
    assert c.datos_del_tema("a-ha", "Take On Me") is None


def test_titulo_con_remaster_y_feat_se_compara_limpio(servidor_http):
    c, _ = montar(servidor_http, grabaciones=[grabacion("Waiting for a Girl Like You", "a-ha", fecha="1985")])
    assert c.datos_del_tema("a-ha", "Waiting for a Girl Like You - 2008 Remaster").anio == 1985
    ruta = urllib.parse.unquote_plus(servidor_http.pedidos[0][0])
    assert 'recording:"Waiting for a Girl Like You"' in ruta and "Remaster" not in ruta
    servidor_http.reglas.clear()
    c2, _ = montar(servidor_http, grabaciones=[grabacion("Gasolina", "a-ha", fecha="2004")])
    assert c2.datos_del_tema("a-ha, Otro", "Gasolina (feat. Otro)").anio == 2004


def test_el_parentesis_que_es_parte_del_titulo_se_conserva(servidor_http):
    c, _ = montar(servidor_http, grabaciones=[grabacion("(I Can't Get No) Satisfaction", "a-ha", fecha="1990")])
    assert c.datos_del_tema("a-ha", "(I Can't Get No) Satisfaction").anio == 1990


def test_persona_no_usa_life_span_como_inicio(servidor_http):
    c, _ = montar(servidor_http, grabaciones=[grabacion(fecha="2004")], artista=artista_json("Person", "PR", "1977-02-03"))
    d = c.datos_del_tema("a-ha", "Take On Me")
    assert d.anio_inicio_artista is None and not d.es_grupo and d.pais == "PR" and d.anio == 2004


def test_anio_anterior_al_inicio_del_grupo_se_descarta(servidor_http):
    c, _ = montar(servidor_http, grabaciones=[grabacion(fecha="1950")])
    d = c.datos_del_tema("a-ha", "Take On Me")
    assert d.anio is None and d.anio_inicio_artista == 1983


def test_sin_ningun_dato_util_da_None(servidor_http):
    c, _ = montar(servidor_http, grabaciones=[grabacion()], artista={"id": AHA, "name": "x", "type": "Person"})
    assert c.datos_del_tema("a-ha", "Take On Me") is None


def test_pais_se_devuelve_como_codigo_y_se_ignora_si_es_raro(servidor_http):
    c, _ = montar(servidor_http, grabaciones=[grabacion(fecha="1984")], artista=artista_json(pais="XW"))
    assert c.datos_del_tema("a-ha", "Take On Me").pais == "XW"       # el filtro por tabla es del que redacta
    servidor_http.reglas.clear()
    c2, _ = montar(servidor_http, grabaciones=[grabacion(fecha="1984")], artista=artista_json(pais="noruega"))
    assert c2.datos_del_tema("a-ha", "Take On Me").pais is None


def test_isrc_tiene_prioridad_y_otra_clave_de_cache(servidor_http):
    servidor_http.responder("/ws/2/isrc/NOA018500001", {"recordings": [grabacion(fecha="1984-10-19")]})
    c, _ = montar(servidor_http, grabaciones=[grabacion(fecha="2019")])
    assert c.datos_del_tema("a-ha", "Take On Me", "NOA018500001").anio == 1984
    assert servidor_http.pedidos[0][0].startswith("/ws/2/isrc/NOA018500001")
    assert c.datos_del_tema("a-ha", "Take On Me").anio == 2019      # sin ISRC: búsqueda y clave distinta


def test_isrc_mal_formado_se_ignora(servidor_http):
    c, _ = montar(servidor_http, grabaciones=[grabacion(fecha="1984")])
    assert c.datos_del_tema("a-ha", "Take On Me", "../../x").anio == 1984
    assert all("/isrc/" not in r for r, _ in servidor_http.pedidos)


def test_cache_evita_repetir(servidor_http):
    c, _ = montar(servidor_http, grabaciones=[grabacion(fecha="1984")])
    a, b = c.datos_del_tema("a-ha", "Take On Me"), c.datos_del_tema("A‐HA", "take on me")
    assert a == b and len(servidor_http.pedidos) == 3        # grabaciones, release groups y artista, en total


def test_sin_resultados_se_cachea_como_sin_dato(servidor_http):
    c, r = montar(servidor_http, grabaciones=[])
    assert c.datos_del_tema("a-ha", "Nada") is None and c.datos_del_tema("a-ha", "Nada") is None
    assert len(servidor_http.pedidos) == 1
    r.t += 14 * 86400 + 1
    c.datos_del_tema("a-ha", "Nada")
    assert len(servidor_http.pedidos) == 2


def test_el_ritmo_es_de_un_pedido_por_segundo(servidor_http):
    c, r = montar(servidor_http, grabaciones=[grabacion(fecha="1984"), grabacion("Otro tema", fecha="1990")])
    c.datos_del_tema("a-ha", "Take On Me")                     # 3 pedidos: grabaciones, grupos y artista
    assert len(r.esperas) >= 1 and all(abs(e - 1.0) < 1e-6 for e in r.esperas)
    n = len(r.esperas)
    r.t += 5
    c.datos_del_tema("a-ha", "Otro tema")                      # pasaron 5 s: el primer pedido no espera
    assert r.esperas[n:] == [pytest.approx(1.0)] * 2           # la búsqueda no espera; los otros dos sí


@pytest.mark.parametrize("codigo, intentos", [(429, 3), (503, 3), (500, 1)])
def test_errores_http_dan_None_y_se_cachean_poco(servidor_http, codigo, intentos, caplog):
    servidor_http.responder("/ws/2/recording", "ocupado", codigo=codigo)
    c, r = montar(servidor_http)
    with caplog.at_level(logging.WARNING, logger="cassette_fm"):
        assert c.datos_del_tema("a-ha", "Take On Me") is None and c.datos_del_tema("a-ha", "Take On Me") is None
        assert len(servidor_http.pedidos) == intentos              # 429/503 son pasajeros: se reintentan
        r.t += 10 * 60 + 1
        assert c.datos_del_tema("a-ha", "Take On Me") is None
    assert len(servidor_http.pedidos) == 2 * intentos
    assert len([x for x in caplog.records if x.levelno == logging.WARNING]) == 1


@pytest.mark.parametrize("cuerpo, tipo", [("<html>x</html>", "text/html"), ({"sin": "recordings"}, "application/json"),
                                          ({"recordings": "no"}, "application/json"),
                                          ({"recordings": [{"title": "Take On Me"}]}, "application/json"),
                                          ("[]", "application/json")])
def test_respuestas_basura_no_lanzan(servidor_http, cuerpo, tipo):
    c, _ = montar(servidor_http)
    servidor_http.reglas.insert(0, ("/ws/2/recording", cuerpo, 200, tipo, 0))
    assert c.datos_del_tema("a-ha", "Take On Me") is None


def test_artista_con_respuesta_basura_da_None(servidor_http):
    c, _ = montar(servidor_http, grabaciones=[grabacion(fecha="1984")])
    servidor_http.reglas.insert(0, (f"/ws/2/artist/{AHA}", "<html>", 200, "text/html", 0))
    assert c.datos_del_tema("a-ha", "Take On Me") is None


def test_timeout_da_None(servidor_http):
    servidor_http.responder("/ws/2/recording", {"recordings": []}, demora=1.5)
    c, _ = montar(servidor_http)
    assert c.datos_del_tema("a-ha", "Take On Me") is None


def test_nombres_con_enie_acentos_y_comillas(servidor_http):
    c, _ = montar(servidor_http, grabaciones=[grabacion("Sensación del Bloque", 'Tito "El Bambino"', fecha="2005")])
    assert c.datos_del_tema('Tito "El Bambino"', "Sensación del Bloque").anio == 2005
    assert 'Tito' in urllib.parse.unquote_plus(servidor_http.pedidos[0][0])


def test_el_primer_artista_de_una_lista_con_feat(servidor_http):
    c, _ = montar(servidor_http, grabaciones=[grabacion("Rodeo", "Lil Nas X", fecha="2020")])
    assert c.datos_del_tema("Lil Nas X, Cardi B", "Rodeo").anio == 2020


@pytest.mark.parametrize("a, b", [("a‐ha", "A-HA"), ("Wisin & Yandel", "wisin and yandel"), ("Ñejo", "nejo"),
                                  ("Beyoncé", "beyonce"), ("  Doble   espacio ", "doble espacio")])
def test_normalizar(a, b):
    assert normalizar(a) == normalizar(b)


@pytest.mark.parametrize("fecha", ["2026-13-99", "mañana", "", "0000", "3000", None])
def test_una_fecha_rara_no_da_anio_pero_si_lo_demas(servidor_http, fecha):
    c, _ = montar(servidor_http, grabaciones=[grabacion(fecha=fecha)])
    d = c.datos_del_tema("a-ha", "Take On Me")
    assert d is not None and d.anio is None and d.pais == "NO"


def test_un_pedido_cacheado_no_rearma_el_aviso(servidor_http, caplog):
    servidor_http.responder("/ws/2/recording", "ocupado", codigo=503)
    c, r = montar(servidor_http)
    with caplog.at_level(logging.WARNING, logger="cassette_fm"):
        c.datos_del_tema("a-ha", "Take On Me")
        c.datos_del_tema("a-ha", "Take On Me")             # sale de la caché: no es "una recuperación"
        r.t += 11 * 60
        c.datos_del_tema("a-ha", "Take On Me")
    assert len([x for x in caplog.records if x.levelno == logging.WARNING]) == 1


# --- revisión final ---

def test_los_alfabetos_no_latinos_no_comparten_clave_ni_coinciden(servidor_http):
    c, _ = montar(servidor_http, grabaciones=[grabacion("Группа крови", "Кино", fecha="1988")])
    assert c.datos_del_tema("Кино", "Группа крови").anio == 1988
    servidor_http.reglas.clear()
    c2, _ = montar(servidor_http, grabaciones=[])
    c2._cache = c._cache                              # misma caché: no se puede contaminar
    assert c2.datos_del_tema("Ария", "Беспечный ангел") is None
    assert len(servidor_http.pedidos) >= 3            # se consultó de verdad, no salió de la caché del otro


@pytest.mark.parametrize("artista, titulo", [("!!!", "Me and Giuliani"), ("a-ha", "???"), ("", "x"), ("x", "   ")])
def test_un_nombre_vacio_al_normalizar_no_consulta(servidor_http, artista, titulo):
    c, _ = montar(servidor_http, grabaciones=[grabacion(fecha="1984")])
    assert c.datos_del_tema(artista, titulo) is None and servidor_http.pedidos == []


def test_normalizar_conserva_letras_no_latinas_y_distingue_mo_de_m():
    assert normalizar("Кино") != normalizar("Ария") and normalizar("Кино") != ""
    assert normalizar("宇多田ヒカル") != ""
    assert normalizar("MØ") != normalizar("-M-")


def test_un_isrc_desconocido_prueba_igual_la_busqueda(servidor_http, caplog):
    servidor_http.responder("/ws/2/isrc/", {"error": "Not Found"}, codigo=404)
    c, _ = montar(servidor_http, grabaciones=[grabacion(fecha="1984")])
    with caplog.at_level(logging.WARNING, logger="cassette_fm"):
        assert c.datos_del_tema("a-ha", "Take On Me", "NOA018500001").anio == 1984
    assert not [r for r in caplog.records if r.levelno == logging.WARNING]


def test_un_titulo_generico_sin_album_que_lo_confirme_no_da_datos(servidor_http):
    c, _ = montar(servidor_http, grabaciones=[grabacion("Intro", "a-ha", fecha="2018"),
                                              grabacion("Intro", "a-ha", fecha="2022")])
    assert c.datos_del_tema("a-ha", "Intro") is None


def test_el_album_desempata_y_da_el_anio_de_ese_disco(servidor_http):
    g1 = grabacion("Intro", "a-ha", fecha="2018", extra={"releases": [{"title": "Disco Viejo"}]})
    g2 = grabacion("Intro", "a-ha", fecha="2022", extra={"releases": [{"title": "Disco Nuevo (Deluxe)"}]})
    c, _ = montar(servidor_http, grabaciones=[g1, g2])
    assert c.datos_del_tema("a-ha", "Intro", album="Disco Nuevo").anio == 2022
    c2, _ = montar(servidor_http, grabaciones=[g1, g2])
    assert c2.datos_del_tema("a-ha", "Intro", album="Disco Viejo").anio == 2018


def test_un_album_que_no_aparece_no_estorba_en_un_titulo_normal(servidor_http):
    c, _ = montar(servidor_http, grabaciones=[grabacion(fecha="2019"), grabacion(fecha="1984")])
    assert c.datos_del_tema("a-ha", "Take On Me", album="Un disco de otro nombre").anio == 1984


@pytest.mark.parametrize("cuerpo", [{}, {"count": 0}])
def test_un_200_sin_recordings_es_un_fallo_y_se_cachea_poco(servidor_http, cuerpo):
    c, r = montar(servidor_http)
    servidor_http.reglas.insert(0, ("/ws/2/recording", cuerpo, 200, "application/json", 0))
    assert c.datos_del_tema("a-ha", "Take On Me") is None
    r.t += 10 * 60 + 1                      # vence el error (10 min), no hace falta esperar 14 días
    c.datos_del_tema("a-ha", "Take On Me")
    assert len(servidor_http.pedidos) == 2


def test_un_artista_vacio_es_un_fallo_y_se_cachea_poco(servidor_http):
    c, r = montar(servidor_http, grabaciones=[grabacion(fecha="1984")], artista={})
    assert c.datos_del_tema("a-ha", "Take On Me") is None
    r.t += 10 * 60 + 1
    c.datos_del_tema("a-ha", "Take On Me")
    assert len(servidor_http.pedidos) == 6          # 3 + 3: se reintentó


def test_la_consulta_escapa_la_barra_y_las_comillas(servidor_http):
    c, _ = montar(servidor_http, grabaciones=[])
    c.datos_del_tema("X", 'Back\\')
    consulta = urllib.parse.parse_qs(urllib.parse.urlparse(servidor_http.pedidos[0][0]).query)["query"][0]
    assert consulta == 'recording:"Back\\\\" AND artist:"X"'
    c.datos_del_tema('Tito "El Bambino"', "Algo")
    consulta = urllib.parse.parse_qs(urllib.parse.urlparse(servidor_http.pedidos[1][0]).query)["query"][0]
    assert 'artist:"Tito \\"El Bambino\\""' in consulta


# --- wikidata (parte 4) ---

def test_el_artista_se_pide_con_url_rels_y_devuelve_el_wikidata(servidor_http):
    rels = [{"type": "official homepage", "url": {"resource": "https://a-ha.com"}},
            {"type": "wikidata", "url": {"resource": "https://www.wikidata.org/wiki/Q156305"}}]
    c, _ = montar(servidor_http, grabaciones=[grabacion(fecha="1984")], artista=dict(artista_json(), relations=rels))
    assert c.datos_del_tema("a-ha", "Take On Me").wikidata == "Q156305"
    assert any("inc=url-rels" in ruta for ruta, _ in servidor_http.pedidos if "/artist/" in ruta)


@pytest.mark.parametrize("rels", [None, [], [{"type": "wikidata", "url": {"resource": "https://www.wikidata.org/wiki/Lexeme:L1"}}],
                                  [{"type": "wikidata", "url": {"resource": ""}}], [{"type": "wikidata"}],
                                  [{"type": "wikidata", "url": {"resource": "https://evil.example/wiki/Q1"}}], "no"])
def test_sin_relacion_wikidata_valida_es_None(servidor_http, rels):
    artista = artista_json() if rels is None else dict(artista_json(), relations=rels)
    c, _ = montar(servidor_http, grabaciones=[grabacion(fecha="1984")], artista=artista)
    assert c.datos_del_tema("a-ha", "Take On Me").wikidata is None


def test_las_entradas_viejas_de_cache_no_se_usan(servidor_http):
    c, _ = montar(servidor_http, grabaciones=[grabacion(fecha="1984")])
    c._cache.guardar("mb2:a ha|take on me|", {"anio": 2, "pais": "XX", "anio_inicio_artista": None,
                                               "es_grupo": False, "fuente": "viejo"}, 10_000)
    c._cache.guardar("mb:a ha|take on me|", {"anio": 1, "pais": "XX", "anio_inicio_artista": None, "es_grupo": False,
                                              "fuente": "viejo"}, 10_000)
    assert c.datos_del_tema("a-ha", "Take On Me").anio == 1984


def test_el_album_de_la_etiqueta_no_restringe_el_anio_de_un_titulo_normal(servidor_http):
    # Roxette - The Look con la etiqueta de un disco en vivo: el año es el del tema, no el de ese disco
    vivo = grabacion(fecha="1992", extra={"releases": [{"title": "Live in Zürich"}]})
    original = grabacion(fecha="1989", extra={"releases": [{"title": "Look Sharp!"}]})
    c, _ = montar(servidor_http, grabaciones=[vivo, original])
    assert c.datos_del_tema("a-ha", "Take On Me", album="Live in Zürich, Vol. 2").anio == 1989


def test_el_anio_sale_del_primer_release_group_del_tema(servidor_http):
    # como Soft Cell - Tainted Love: las 25 grabaciones de la búsqueda son reediciones; el single es más viejo
    c, _ = montar(servidor_http, grabaciones=[grabacion(fecha="2000"), grabacion(fecha="2004")], grupos=[
        grupo(fecha="2021-06-18", tipo="Album"), grupo(fecha="1985-07"), grupo(fecha="2023-12-14"),
        grupo(fecha="1984", id_=OTRO, artista="a-ha"),               # otro artista con el mismo nombre
        grupo("Take On Me Remixes", fecha="1984")])                   # otro título
    assert c.datos_del_tema("a-ha", "Take On Me").anio == 1985
    consulta = [r for r, _ in servidor_http.pedidos if r.startswith("/ws/2/release-group")]
    assert consulta and "releasegroup" in urllib.parse.unquote_plus(consulta[0])


def test_un_titulo_generico_no_usa_release_groups(servidor_http):
    g = grabacion("Intro", "a-ha", fecha="2022", extra={"releases": [{"title": "Disco Nuevo"}]})
    c, _ = montar(servidor_http, grabaciones=[g], grupos=[grupo("Intro", fecha="1990")])
    assert c.datos_del_tema("a-ha", "Intro", album="Disco Nuevo").anio == 2022
    assert not any(r.startswith("/ws/2/release-group") for r, _ in servidor_http.pedidos)


def test_un_fallo_en_los_release_groups_es_un_fallo_y_se_cachea_poco(servidor_http):
    c, r = montar(servidor_http, grabaciones=[grabacion(fecha="1984")])
    servidor_http.reglas.insert(0, ("/ws/2/release-group", {"error": "busy"}, 503, "application/json", 0.0))
    assert c.datos_del_tema("a-ha", "Take On Me") is None


def test_un_503_pasajero_se_reintenta_con_espera_y_da_el_dato(servidor_http):
    respuestas = [(503, "ocupado"), (503, "ocupado"), (200, {"recordings": [grabacion(fecha="1984")]})]
    c, r = montar(servidor_http)
    servidor_http.reglas.insert(0, ("/ws/2/recording", lambda ruta: respuestas.pop(0), 200, "application/json", 0))
    assert c.datos_del_tema("a-ha", "Take On Me").anio == 1984
    assert sum(1 for e in r.esperas if e >= 2) == 2                 # dos esperas largas antes de reintentar


def test_el_timeout_por_defecto_da_tiempo_a_un_musicbrainz_lento():
    assert ConfigServicioDJ().timeout_hechos_segundos >= 10

import threading
import time
from datetime import datetime, timezone

from cassette_fm.dj.hechos import FuenteHechos, Hechos
from cassette_fm.dj.hechos.clima import Clima
from cassette_fm.dj.hechos.musicbrainz import DatosTema
from cassette_fm.dj.pedido import Pedido, Tema

CLIMA = Clima(22, "nublado", True)
TEMA = DatosTema(1984, "NO", 1983, True, "https://musicbrainz.org/artist/x", "Q156305")


def pedido():
    return Pedido(id="x", estacion="E", idioma="es", voz="v", momento=datetime(2026, 1, 1, tzinfo=timezone.utc),
                  anterior=None, siguiente=Tema("a-ha", "Take On Me", None, "NOA018500001"))


class ClimaFalso:
    def __init__(self, valor=CLIMA, demora=0.0, error=None):
        self.valor, self.demora, self.error = valor, demora, error

    def actual(self):
        time.sleep(self.demora)
        if self.error:
            raise self.error
        return self.valor


class MBFalso:
    def __init__(self, valor=TEMA, demora=0.0, error=None):
        self.valor, self.demora, self.error = valor, demora, error
        self.llamadas = []

    def datos_del_tema(self, artista, titulo, isrc=None, album=None, hasta=None):
        self.llamadas.append((artista, titulo, isrc))
        self.plazos = getattr(self, "plazos", []) + [hasta]
        time.sleep(self.demora)
        if self.error:
            raise self.error
        return self.valor


def test_junta_clima_y_tema_en_paralelo():
    mb = MBFalso(demora=0.5)
    t0 = time.monotonic()
    hechos, fuentes = FuenteHechos(ClimaFalso(demora=0.5), mb, espera_segundos=3).reunir(pedido())
    assert time.monotonic() - t0 < 0.9
    assert hechos == Hechos(CLIMA, TEMA) and mb.llamadas == [("a-ha", "Take On Me", "NOA018500001")]


def test_un_cliente_que_falla_no_afecta_al_otro():
    hechos, fuentes = FuenteHechos(ClimaFalso(error=RuntimeError("boom")), MBFalso(), espera_segundos=2).reunir(pedido())
    assert hechos == Hechos(None, TEMA) and fuentes["clima"] is None and fuentes["musicbrainz"]
    hechos, fuentes = FuenteHechos(ClimaFalso(), MBFalso(error=ValueError("x")), espera_segundos=2).reunir(pedido())
    assert hechos == Hechos(CLIMA, None) and fuentes["musicbrainz"] is None


def test_clientes_none_dan_hechos_vacios():
    assert FuenteHechos(None, None).reunir(pedido()) == (Hechos(), {"clima": None, "musicbrainz": None, "wikipedia": None})


def test_si_un_cliente_se_cuelga_se_sigue_sin_su_dato():
    antes = threading.active_count()
    t0 = time.monotonic()
    hechos, _ = FuenteHechos(ClimaFalso(demora=5), MBFalso(), espera_segundos=0.3).reunir(pedido())
    assert time.monotonic() - t0 < 1.0 and hechos == Hechos(None, TEMA)


def test_fuentes_para_el_guion_incluye_la_url_de_musicbrainz():
    _, fuentes = FuenteHechos(ClimaFalso(), MBFalso(), espera_segundos=2).reunir(pedido())
    assert fuentes["musicbrainz"] == {"fuente": "https://musicbrainz.org/artist/x", "anio": 1984, "pais": "NO",
                                      "anio_inicio_artista": 1983, "es_grupo": True}
    assert fuentes["clima"] == {"temperatura": 22, "cielo": "nublado", "es_de_dia": True}


# --- Wikipedia (parte 4) ---

from cassette_fm.dj.hechos.wikipedia import Resumen  # noqa: E402

RESUMEN = Resumen("A-ha es una banda noruega.", "A-ha", "es", "https://es.wikipedia.org/wiki/A-ha")


class WikiFalsa:
    def __init__(self, valor=RESUMEN):
        self.valor = valor
        self.llamadas = []

    def resumen(self, wikidata, idiomas):
        self.llamadas.append((wikidata, list(idiomas)))
        return self.valor


def test_sin_con_wikipedia_no_se_pide_nada():
    w = WikiFalsa()
    hechos, fuentes = FuenteHechos(ClimaFalso(), MBFalso(), 2, wikipedia=w).reunir(pedido())
    assert w.llamadas == [] and hechos.wikipedia is None and fuentes["wikipedia"] is None


def test_con_wikipedia_se_pide_despues_de_musicbrainz_y_se_anota_en_las_fuentes():
    w = WikiFalsa()
    hechos, fuentes = FuenteHechos(ClimaFalso(), MBFalso(), 2, wikipedia=w).reunir(pedido(), con_wikipedia=True)
    assert w.llamadas == [("Q156305", ["es", "en"])] and hechos.wikipedia == RESUMEN
    assert fuentes["wikipedia"] == {"url": RESUMEN.url, "titulo": "A-ha", "idioma": "es"}


def test_sin_wikidata_no_hay_resumen():
    w = WikiFalsa()
    sin = DatosTema(1984, "NO", 1983, True, "u", None)
    hechos, fuentes = FuenteHechos(ClimaFalso(), MBFalso(sin), 2, wikipedia=w).reunir(pedido(), con_wikipedia=True)
    assert w.llamadas == [] and hechos.wikipedia is None and fuentes["wikipedia"] is None


def test_idiomas_del_pedido_y_ingles_sin_repetir():
    w = WikiFalsa()
    p = pedido()
    p = p.__class__(**{**p.__dict__, "idioma": "en"})
    FuenteHechos(None, MBFalso(), 2, wikipedia=w).reunir(p, con_wikipedia=True)
    assert w.llamadas == [("Q156305", ["en"])]


def test_un_cliente_de_wikipedia_roto_no_afecta():
    w = WikiFalsa()
    w.resumen = lambda *a: (_ for _ in ()).throw(RuntimeError("boom"))
    hechos, _ = FuenteHechos(ClimaFalso(), MBFalso(), 2, wikipedia=w).reunir(pedido(), con_wikipedia=True)
    assert hechos.wikipedia is None and hechos.tema == TEMA


def test_una_wikipedia_colgada_no_pasa_del_tope():
    import time as _t
    w = WikiFalsa()
    w.resumen = lambda *a: _t.sleep(5)
    t0 = _t.monotonic()
    hechos, _ = FuenteHechos(None, MBFalso(), 0.3, wikipedia=w).reunir(pedido(), con_wikipedia=True)
    assert _t.monotonic() - t0 < 1.0 and hechos.wikipedia is None


def test_con_plazo_espera_a_musicbrainz_hasta_el_plazo_y_se_lo_pasa():
    mb = MBFalso(demora=0.5)
    hasta = time.time() + 3
    hechos, _ = FuenteHechos(None, mb, espera_segundos=0.1).reunir(pedido(), hasta=hasta)
    assert hechos.tema == TEMA and mb.plazos == [hasta]


def test_un_plazo_ya_vencido_no_acorta_la_espera_normal():
    mb = MBFalso(demora=0.3)
    hechos, _ = FuenteHechos(None, mb, espera_segundos=2).reunir(pedido(), hasta=time.time() - 10)
    assert hechos.tema == TEMA

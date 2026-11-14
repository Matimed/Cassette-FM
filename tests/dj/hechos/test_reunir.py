import threading
import time
from datetime import datetime, timezone

from cassette_fm.dj.hechos import FuenteHechos, Hechos
from cassette_fm.dj.hechos.clima import Clima
from cassette_fm.dj.hechos.musicbrainz import DatosTema
from cassette_fm.dj.pedido import Pedido, Tema

CLIMA = Clima(22, "nublado", True)
TEMA = DatosTema(1984, "NO", 1983, True, "https://musicbrainz.org/artist/x")


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

    def datos_del_tema(self, artista, titulo, isrc=None):
        self.llamadas.append((artista, titulo, isrc))
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
    assert FuenteHechos(None, None).reunir(pedido()) == (Hechos(), {"clima": None, "musicbrainz": None})


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

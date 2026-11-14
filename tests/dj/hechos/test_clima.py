import logging

import pytest

from cassette_fm.dj.config import ConfigServicioDJ
from cassette_fm.dj.hechos.cache import CacheHechos
from cassette_fm.dj.hechos.clima import Clima, ClienteClima

REAL = {"latitude": -34.62, "longitude": -58.40, "timezone": "America/Argentina/Buenos_Aires",
        "current_units": {"temperature_2m": "°C"},
        "current": {"time": "2026-11-14T02:15", "interval": 900, "temperature_2m": 22.0, "weather_code": 51,
                    "is_day": 0}}


def actual(codigo=51, temp=22.0, dia=0):
    d = {"current": dict(REAL["current"], weather_code=codigo, temperature_2m=temp, is_day=dia)}
    return d


class Reloj:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def cliente(servidor, reloj=None, **cfg):
    config = ConfigServicioDJ(open_meteo_url=servidor.url + "/v1/forecast", timeout_hechos_segundos=1.0, **cfg)
    reloj = reloj or Reloj()
    return ClienteClima(config, CacheHechos(None, reloj), reloj)


def test_parsea_la_respuesta_real(servidor_http):
    servidor_http.responder("/v1/forecast", REAL)
    assert cliente(servidor_http).actual() == Clima(22, "lluvia", False)


@pytest.mark.parametrize("codigo, cielo", [(0, "despejado"), (1, "despejado"), (2, "nublado"), (3, "nublado"),
                                           (45, "niebla"), (48, "niebla"), (51, "lluvia"), (61, "lluvia"),
                                           (67, "lluvia"), (80, "lluvia"), (82, "lluvia"), (71, "nieve"),
                                           (77, "nieve"), (85, "nieve"), (86, "nieve"), (95, "tormenta"),
                                           (99, "tormenta")])
def test_cada_codigo_wmo(servidor_http, codigo, cielo):
    servidor_http.responder("/v1/forecast", actual(codigo))
    assert cliente(servidor_http).actual().cielo == cielo


@pytest.mark.parametrize("codigo", [4, 44, 68, 78, 90, 100, -1])
def test_codigo_desconocido_da_None(servidor_http, codigo):
    servidor_http.responder("/v1/forecast", actual(codigo))
    assert cliente(servidor_http).actual() is None


def test_redondea_la_temperatura_y_es_de_dia(servidor_http):
    servidor_http.responder("/v1/forecast", actual(0, 21.6, 1))
    assert cliente(servidor_http).actual() == Clima(22, "despejado", True)
    servidor_http.reglas.clear()
    servidor_http.responder("/v1/forecast", actual(0, -2.5, 1))
    assert cliente(servidor_http).actual().temperatura == -2        # redondeo de Python (a par)


def test_usa_cache(servidor_http):
    servidor_http.responder("/v1/forecast", REAL)
    c = cliente(servidor_http)
    c.actual()
    c.actual()
    assert len(servidor_http.pedidos) == 1


def test_la_cache_vence(servidor_http):
    servidor_http.responder("/v1/forecast", REAL)
    r = Reloj()
    c = cliente(servidor_http, r)
    c.actual()
    r.t += 15 * 60 + 1
    c.actual()
    assert len(servidor_http.pedidos) == 2


def test_servidor_caido_da_None_y_avisa_una_vez(caplog):
    config = ConfigServicioDJ(open_meteo_url="http://127.0.0.1:9/v1/forecast", timeout_hechos_segundos=0.5)
    r = Reloj()
    c = ClienteClima(config, CacheHechos(None, r), r)
    with caplog.at_level(logging.WARNING, logger="cassette_fm"):
        assert c.actual() is None
        r.t += 11 * 60                      # vence el "sin dato" por error y vuelve a intentar
        assert c.actual() is None
    assert len([x for x in caplog.records if x.levelno == logging.WARNING]) == 1


@pytest.mark.parametrize("cuerpo, tipo", [("<html>no</html>", "text/html"), ({"sin": "current"}, "application/json"),
                                          ({"current": {"temperature_2m": "frío", "weather_code": 0, "is_day": 1}}, "application/json"),
                                          ({"current": {"temperature_2m": None, "weather_code": 0, "is_day": 1}}, "application/json"),
                                          ({"current": {"temperature_2m": 20, "weather_code": "0", "is_day": 1}}, "application/json"),
                                          ({"current": {"temperature_2m": True, "weather_code": 0, "is_day": 1}}, "application/json"),
                                          ("[1, 2]", "application/json"), ("", "application/json")])
def test_respuestas_basura(servidor_http, cuerpo, tipo):
    servidor_http.responder("/v1/forecast", cuerpo, tipo=tipo)
    assert cliente(servidor_http).actual() is None


def test_error_http_da_None(servidor_http):
    servidor_http.responder("/v1/forecast", "boom", codigo=503)
    assert cliente(servidor_http).actual() is None


def test_timeout_da_None(servidor_http):
    servidor_http.responder("/v1/forecast", REAL, demora=1.5)
    assert cliente(servidor_http).actual() is None


def test_un_fallo_se_cachea_poco_y_despues_reintenta(servidor_http):
    r = Reloj()
    servidor_http.responder("/v1/forecast", "boom", codigo=503)
    c = cliente(servidor_http, r)
    assert c.actual() is None and c.actual() is None
    assert len(servidor_http.pedidos) == 1
    servidor_http.reglas.clear()
    servidor_http.responder("/v1/forecast", REAL)
    r.t += 10 * 60 + 1
    assert c.actual() == Clima(22, "lluvia", False)


def test_la_url_lleva_coordenadas_y_zona(servidor_http):
    servidor_http.responder("/v1/forecast", REAL)
    cliente(servidor_http, latitud=-31.4, longitud=-64.2).actual()
    ruta = servidor_http.pedidos[0][0]
    assert "latitude=-31.4" in ruta and "longitude=-64.2" in ruta
    assert "timezone=America%2FArgentina%2FBuenos_Aires" in ruta
    assert "current=temperature_2m,weather_code,is_day" in ruta or "current=temperature_2m%2Cweather_code%2Cis_day" in ruta

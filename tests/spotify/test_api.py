import pytest

from cassette_fm.config import ConfigSpotify
from cassette_fm.spotify.api import ClienteSpotify, ErrorSpotify
from cassette_fm.spotify.sesion import ErrorSesion


class SesionFalsa:
    def __init__(self, error=None):
        self.forzadas = 0
        self.error = error

    def token(self, forzar=False):
        if self.error:
            raise self.error
        if forzar:
            self.forzadas += 1
        return f"A{self.forzadas}"


def cliente(servidor_http, sesion=None, timeout=2.0):
    esperas = []
    c = ClienteSpotify(sesion or SesionFalsa(), ConfigSpotify(api_url=servidor_http.url + "/v1", timeout_segundos=timeout),
                       dormir=esperas.append)
    return c, esperas


def secuencia(*respuestas):
    """Cuerpo callable que contesta (código, cuerpo) en orden; la última se repite."""
    pendientes = list(respuestas)
    return lambda ruta: pendientes.pop(0) if len(pendientes) > 1 else pendientes[0]


def test_get_manda_el_token_y_los_parametros(servidor_http):
    servidor_http.responder("/v1/me", {"display_name": "Matimed"})
    c, _ = cliente(servidor_http)
    assert c.get("/me", {"fields": "a,b"}) == {"display_name": "Matimed"}
    ruta, headers = servidor_http.pedidos[0]
    assert ruta == "/v1/me?fields=a%2Cb" and headers["Authorization"] == "Bearer A0"


def test_401_refresca_y_reintenta_una_vez(servidor_http):
    servidor_http.responder("/v1/me", secuencia((401, {"error": {"status": 401, "message": "expired"}}), (200, {"ok": 1})))
    s = SesionFalsa()
    c, _ = cliente(servidor_http, s)
    assert c.get("/me") == {"ok": 1} and s.forzadas == 1
    assert servidor_http.pedidos[1][1]["Authorization"] == "Bearer A1"


def test_dos_401_seguidos_es_error(servidor_http):
    servidor_http.responder("/v1/me", {"error": {"status": 401, "message": "expired"}}, 401)
    c, _ = cliente(servidor_http)
    with pytest.raises(ErrorSpotify) as e:
        c.get("/me")
    assert e.value.codigo == 401


def test_429_corto_espera_y_reintenta(servidor_http):
    respuestas = secuencia((429, {"error": {"status": 429, "message": "rate"}}), (200, {"ok": 1}))
    servidor_http.responder("/v1/me", respuestas, encabezados={"Retry-After": "2"})
    c, esperas = cliente(servidor_http)
    assert c.get("/me") == {"ok": 1} and esperas == [2.0]


def test_429_largo_no_espera(servidor_http):
    servidor_http.responder("/v1/me", {"error": {"status": 429, "message": "rate"}}, 429, encabezados={"Retry-After": "60"})
    c, esperas = cliente(servidor_http)
    with pytest.raises(ErrorSpotify) as e:
        c.get("/me")
    assert e.value.codigo == 429 and esperas == []


def test_error_con_mensaje_de_spotify(servidor_http):
    servidor_http.responder("/v1/playlists/x/items", {"error": {"status": 403, "message": "Forbidden"}}, 403)
    c, _ = cliente(servidor_http)
    with pytest.raises(ErrorSpotify, match="Forbidden") as e:
        c.get("/playlists/x/items")
    assert e.value.codigo == 403


def test_timeout_es_error_spotify(servidor_http):
    servidor_http.responder("/v1/me", {"ok": 1}, demora=1.0)
    c, _ = cliente(servidor_http, timeout=0.3)
    with pytest.raises(ErrorSpotify) as e:
        c.get("/me")
    assert e.value.codigo is None


def test_respuesta_que_no_es_json_es_error(servidor_http):
    servidor_http.responder("/v1/me", "<html>", tipo="text/html")
    c, _ = cliente(servidor_http)
    with pytest.raises(ErrorSpotify):
        c.get("/me")


def test_paginas_sigue_next(servidor_http):
    base = servidor_http.url + "/v1"
    servidor_http.responder("/v1/playlists/p/items?offset=100", {"items": [3], "next": None})
    servidor_http.responder("/v1/playlists/p/items?offset=50", {"items": [2], "next": f"{base}/playlists/p/items?offset=100"})
    servidor_http.responder("/v1/playlists/p/items", {"items": [1], "next": f"{base}/playlists/p/items?offset=50"})
    c, _ = cliente(servidor_http)
    assert [p["items"] for p in c.paginas("/playlists/p/items", {"limit": 50})] == [[1], [2], [3]]


def test_sin_sesion_es_error_spotify_con_el_mensaje(servidor_http):
    c, _ = cliente(servidor_http, SesionFalsa(ErrorSesion("no hay sesión de Spotify: corré cassette spotify login")))
    with pytest.raises(ErrorSpotify, match="cassette spotify login"):
        c.get("/me")


def test_put_manda_cuerpo_json_y_acepta_204(servidor_http):
    import json as _json
    servidor_http.responder("/v1/me/player/play", "", 204)
    c, _ = cliente(servidor_http)
    assert c.put("/me/player/play", {"device_id": "D"}, {"uris": ["spotify:track:x"], "position_ms": 5}) is None
    ((ruta, cuerpo),) = servidor_http.cuerpos
    assert ruta == "/v1/me/player/play?device_id=D" and _json.loads(cuerpo) == {"uris": ["spotify:track:x"], "position_ms": 5}
    assert servidor_http.pedidos[0][1]["Authorization"] == "Bearer A0"


def test_put_con_error_es_error_spotify(servidor_http):
    servidor_http.responder("/v1/me/player/play", {"error": {"status": 404, "message": "Device not found"}}, 404)
    c, _ = cliente(servidor_http)
    with pytest.raises(ErrorSpotify, match="Device not found") as e:
        c.put("/me/player/play")
    assert e.value.codigo == 404

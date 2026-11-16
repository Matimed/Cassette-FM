import json

import pytest

from cassette_fm.config import ConfigSpotify
from cassette_fm.spotify.api import ClienteSpotify, ErrorSpotify
from cassette_fm.spotify.control import ControlSpotify

DISPOSITIVOS = {"devices": [{"id": "OTRO", "name": "Celular"}, {"id": "D1", "name": "cassette-fm"},
                            {"id": "D2", "name": "cassette-fm (viejo)"}]}


class SesionFalsa:
    def token(self, forzar=False):
        return "A"


def control(servidor_http, nombre="cassette-fm"):
    c = ClienteSpotify(SesionFalsa(), ConfigSpotify(api_url=servidor_http.url + "/v1", timeout_segundos=1.0),
                       dormir=lambda s: None)
    return ControlSpotify(c, nombre)


def test_dispositivo_por_nombre_exacto_y_cacheado(servidor_http):
    servidor_http.responder("/v1/me/player/devices", DISPOSITIVOS)
    c = control(servidor_http)
    assert c.dispositivo() == "D1" and c.dispositivo() == "D1"
    assert len(servidor_http.pedidos) == 1


def test_sin_el_dispositivo_dice_que_revisar(servidor_http):
    servidor_http.responder("/v1/me/player/devices", {"devices": [{"id": "OTRO", "name": "Celular"}]})
    with pytest.raises(ErrorSpotify, match="cassette spotify estado"):
        control(servidor_http).dispositivo()


def test_reproducir_apaga_shuffle_y_repeat_y_da_play(servidor_http):
    servidor_http.responder("/v1/me/player/devices", DISPOSITIVOS)
    servidor_http.responder("/v1/me/player/", "", 204)
    control(servidor_http).reproducir(["spotify:track:a", "spotify:track:b"], lambda: 30000)
    rutas = [r for r, _ in servidor_http.cuerpos]
    assert rutas == ["/v1/me/player/shuffle?state=false&device_id=D1", "/v1/me/player/repeat?state=off&device_id=D1",
                     "/v1/me/player/play?device_id=D1"]
    assert json.loads(servidor_http.cuerpos[2][1]) == {"uris": ["spotify:track:a", "spotify:track:b"], "position_ms": 30000}


def test_play_404_rebusca_el_dispositivo_y_reintenta(servidor_http):
    dispositivos = [DISPOSITIVOS, {"devices": [{"id": "D9", "name": "cassette-fm"}]}]
    servidor_http.responder("/v1/me/player/devices", lambda ruta: dispositivos.pop(0) if len(dispositivos) > 1 else dispositivos[0])
    plays = [(404, {"error": {"status": 404, "message": "Device not found"}}), (204, "")]
    servidor_http.responder("/v1/me/player/play", lambda ruta: plays.pop(0) if len(plays) > 1 else plays[0])
    servidor_http.responder("/v1/me/player/", "", 204)
    control(servidor_http).reproducir(["spotify:track:a"], lambda: 0)
    plays_hechos = [r for r, _ in servidor_http.cuerpos if r.split("?")[0].endswith("/play")]
    assert plays_hechos == ["/v1/me/player/play?device_id=D1", "/v1/me/player/play?device_id=D9"]


def test_la_posicion_se_calcula_justo_antes_del_play(servidor_http):
    servidor_http.responder("/v1/me/player/devices", DISPOSITIVOS)
    servidor_http.responder("/v1/me/player/", "", 204)
    hechos = []                                      # cuántos pedidos ya se habían hecho al calcularla
    control(servidor_http).reproducir(["spotify:track:a"], lambda: hechos.append(len(servidor_http.cuerpos)) or 1234)
    assert hechos == [2]                             # después de shuffle y repeat: lo que tardan no atrasa el tema
    assert json.loads(servidor_http.cuerpos[2][1])["position_ms"] == 1234

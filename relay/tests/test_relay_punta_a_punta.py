"""El puente real de la PC (`cassette_fm.puente_nube.PuenteNube`) contra el relay real, en 127.0.0.1."""
import http.client
import json

import pytest

from ayudas_relay import CASA, CLAVE, OYENTES, TOKEN, esperar
from cassette_fm.puente_nube import PuenteNube
from test_puente_nube import Codificadores, EsperaCorta, RadioFalsa

BEARER = {"Authorization": f"Bearer {CLAVE}"}


@pytest.fixture
def gst():
    return Codificadores()


@pytest.fixture
def registro(gst):
    return gst.registro()


@pytest.fixture
def armar_puente(relay, registro):
    creados = []

    def armar(radio=None):
        radio = radio or RadioFalsa()
        p = PuenteNube(radio, registro, relay.ws, lambda: TOKEN, espera=EsperaCorta())
        creados.append(p)
        p.iniciar()
        assert esperar(lambda: relay.en_loop(lambda: relay.app[CASA].radio()) is not None)
        return radio
    yield armar
    for p in creados:
        p.cerrar()


def test_estado_y_orden_de_punta_a_punta(relay, armar_puente):
    radio = armar_puente()
    e = json.loads(relay.pedir("GET", "/api/estado", headers=BEARER)[2])
    assert e["en_linea"] is True and e["radio"]["estacion"] == "A"
    status, _, cuerpo = relay.pedir("POST", "/api/sintonizar", {"estacion": "B"}, BEARER)
    assert (status, json.loads(cuerpo)) == (200, {"ok": True})
    assert radio.ordenes == [("sintonizar", "B", False)]
    assert esperar(lambda: json.loads(relay.pedir("GET", "/api/estado", headers=BEARER)[2])["radio"]["estacion"] == "B")
    status, _, cuerpo = relay.pedir("POST", "/api/sintonizar", {"estacion": "No existe"}, BEARER)
    assert (status, json.loads(cuerpo)) == (409, {"error": "esa emisora no existe"})


def test_audio_de_punta_a_punta(relay, armar_puente, gst, registro):
    armar_puente()
    conexion = http.client.HTTPConnection("127.0.0.1", relay.puerto, timeout=5)
    conexion.request("GET", "/api/escuchar?calidad=64", headers=BEARER)
    r = conexion.getresponse()
    assert r.status == 200
    assert esperar(lambda: gst.de(64))
    codificador = gst.de(64)[0]
    assert esperar(lambda: relay.en_loop(lambda: 64 in relay.app[CASA]._audios))
    trama = b"\xff\xfb" * 2000
    codificador.emitir(trama)
    assert r.read(len(trama)) == trama
    conexion.close()
    r.close()
    assert esperar(lambda: relay.en_loop(lambda: relay.app[OYENTES].cuantos(64)) == 0)

    def apagado():
        registro.revisar_fuente()          # lo que hace el servicio cada segundo
        return codificador.terminado
    assert esperar(apagado, timeout=5)


def test_logo_de_punta_a_punta(relay, armar_puente, tmp_path):
    logo = tmp_path / "a.png"
    logo.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x02" * 64)
    radio = RadioFalsa()
    radio.datos["iconos"] = {"A": str(logo)}
    armar_puente(radio)
    assert esperar(lambda: relay.pedir("GET", "/api/icono/A", headers=BEARER)[0] == 200)
    status, headers, datos = relay.pedir("GET", "/api/icono/A", headers=BEARER)
    assert datos == logo.read_bytes() and headers["Content-Type"] == "image/png"

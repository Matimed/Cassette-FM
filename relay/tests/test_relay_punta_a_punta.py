"""El puente real de la PC (`cassette_fm.puente_nube.PuenteNube`) contra el relay real, en 127.0.0.1."""
import http.client
import json

import pytest

from ayudas_relay import ACCESO, CASA, CLAVE, OYENTES, TOKEN, esperar
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
    armar.puentes = creados
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


# --- claves ---

from cassette_fm import claves  # noqa: E402


def _entrar(relay, clave):
    return relay.pedir("POST", "/api/entrar", {"clave": clave})


def _crear_y_mandar(relay, armar_puente, tmp_path, nombre="Mamá", permiso="escucha"):
    archivo = tmp_path / "claves.json"
    clave, registro = claves.crear(archivo, nombre, permiso)
    armar_puente.puentes[0].poner_claves(claves.para_relay(claves.leer(archivo)))
    assert esperar(lambda: _entrar(relay, clave)[0] == 204)
    return archivo, clave, registro


def test_claves_de_punta_a_punta(relay, armar_puente, tmp_path):
    radio = armar_puente()
    _, clave, registro = _crear_y_mandar(relay, armar_puente, tmp_path)
    cookie = _entrar(relay, clave)[1]["Set-Cookie"].split(";", 1)[0]
    e = json.loads(relay.pedir("GET", "/api/estado", headers={"Cookie": cookie})[2])
    assert e["permiso"] == "escucha" and e["radio"]["estacion"] == "A"
    status, _, cuerpo = relay.pedir("POST", "/api/sintonizar", {"estacion": "B"}, {"Cookie": cookie})
    assert status == 403 and radio.ordenes == []
    assert relay.pedir("POST", "/api/sintonizar", {"estacion": "B"}, BEARER)[0] == 200      # la maestra sí
    assert radio.ordenes == [("sintonizar", "B", False)]


def test_borrar_la_clave_corta_el_audio(relay, armar_puente, gst, tmp_path):
    armar_puente()
    archivo, clave, registro = _crear_y_mandar(relay, armar_puente, tmp_path)
    cookie = _entrar(relay, clave)[1]["Set-Cookie"].split(";", 1)[0]
    suya = http.client.HTTPConnection("127.0.0.1", relay.puerto, timeout=5)
    suya.request("GET", "/api/escuchar?calidad=64", headers={"Cookie": cookie})
    rs = suya.getresponse()
    maestra = http.client.HTTPConnection("127.0.0.1", relay.puerto, timeout=5)
    maestra.request("GET", "/api/escuchar?calidad=64", headers=BEARER)
    rm = maestra.getresponse()
    assert rs.status == 200 and rm.status == 200
    assert esperar(lambda: relay.en_loop(lambda: relay.app[OYENTES].cuantos(64)) == 2)
    claves.borrar(archivo, "Mamá")
    armar_puente.puentes[0].poner_claves(claves.para_relay(claves.leer(archivo)))
    assert esperar(lambda: relay.en_loop(lambda: relay.app[OYENTES].cuantos(64)) == 1)
    assert rs.read() == b""
    assert relay.pedir("GET", "/api/estado", headers={"Cookie": cookie})[0] == 401
    assert relay.pedir("POST", "/api/entrar", {"clave": clave})[0] == 401
    assert relay.pedir("GET", "/api/estado", headers=BEARER)[0] == 200
    suya.close()
    maestra.close()


def test_relay_reiniciado_recibe_la_lista_de_nuevo(relay, armar_puente, tmp_path):
    armar_puente()
    _, clave, _ = _crear_y_mandar(relay, armar_puente, tmp_path)
    relay.en_loop(lambda: relay.app[ACCESO].__init__(relay.ajustes.clave_maestra))     # como un relay recién despertado
    assert _entrar(relay, clave)[0] == 401
    armar_puente.puentes[0].reconectar()
    assert esperar(lambda: _entrar(relay, clave)[0] == 204)

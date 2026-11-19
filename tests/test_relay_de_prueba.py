import importlib.util
import json
import threading
import urllib.request
from pathlib import Path

import pytest

from cassette_fm.puente_nube import PuenteNube
from test_puente_nube import CLAVE, Codificadores, EsperaCorta, RadioFalsa, esperar

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "relay-de-prueba.py"


def _modulo():
    spec = importlib.util.spec_from_file_location("relay_de_prueba", _SCRIPT)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


@pytest.fixture
def armado(tmp_path):
    relay = _modulo().Relay("127.0.0.1", 0, CLAVE)
    gst, radio = Codificadores(), RadioFalsa()
    logo = tmp_path / "logo.png"
    logo.write_bytes(b"\x89PNG-logo")
    radio.datos["iconos"] = {"B": str(logo)}
    puente = PuenteNube(radio, gst.registro(), f"ws://127.0.0.1:{relay.puerto}", lambda: CLAVE, espera=EsperaCorta())
    puente.iniciar()
    assert esperar(relay.conectado)
    yield relay, puente, gst, radio
    puente.cerrar()
    relay.cerrar()


def _url(relay, ruta):
    return f"http://127.0.0.1:{relay.puerto}{ruta}"


def test_de_punta_a_punta(armado):
    relay, puente, gst, radio = armado
    recibido = bytearray()
    respuesta = urllib.request.urlopen(_url(relay, "/escuchar?calidad=64"), timeout=5)
    assert respuesta.headers["Content-Type"] == "audio/mpeg"
    lector = threading.Thread(target=lambda: recibido.extend(respuesta.read(9)), daemon=True)
    lector.start()
    assert esperar(lambda: gst.de(64) and puente.info()["subiendo"] == [64])
    gst.de(64)[0].emitir(b"mp3-datos")
    lector.join(5)
    assert bytes(recibido) == b"mp3-datos"

    pedido = urllib.request.Request(_url(relay, "/sintonizar/B"), data=b"", method="POST")
    assert json.loads(urllib.request.urlopen(pedido, timeout=5).read())["ok"] is True
    assert radio.ordenes == [("sintonizar", "B", False)]
    assert esperar(lambda: (relay.estado or {}).get("estacion") == "B")
    estado = json.loads(urllib.request.urlopen(_url(relay, "/estado"), timeout=5).read())
    assert estado["conectado"] is True and estado["estacion"] == "B"
    assert esperar(lambda: relay.icono("B") is not None)
    assert urllib.request.urlopen(_url(relay, "/icono/B"), timeout=5).read() == b"\x89PNG-logo"

    respuesta.close()
    gst.de(64)[0].emitir(b"x" * 4096)        # el relay se entera del oyente que se fue al escribirle
    assert esperar(lambda: puente.info()["subiendo"] == [], 5)


def test_clave_incorrecta_se_rechaza(tmp_path):
    relay = _modulo().Relay("127.0.0.1", 0, CLAVE)
    puente = PuenteNube(RadioFalsa(), None, f"ws://127.0.0.1:{relay.puerto}", lambda: "otra", espera=EsperaCorta())
    try:
        puente.iniciar()
        assert esperar(lambda: puente.info()["error"] is not None)
        assert not relay.conectado() and "clave" in puente.info()["error"]
    finally:
        puente.cerrar()
        relay.cerrar()


def test_la_pagina_lista_las_emisoras(armado):
    relay, *_ = armado
    pagina = urllib.request.urlopen(_url(relay, "/"), timeout=5).read().decode()
    assert "Más Gasolina F.M." in pagina and "/escuchar?calidad=" in pagina

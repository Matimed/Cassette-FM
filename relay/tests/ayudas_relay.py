import asyncio
import http.client
import json
import logging
import threading
import time

import pytest
from aiohttp import web
from websockets.sync.client import connect

from cassette_relay.app import CASA, OYENTES, crear_app  # noqa: F401  (OYENTES: lo usan los tests)
from cassette_relay.config import Ajustes

TOKEN = "token-de-la-casa-" + "x" * 30
CLAVE = "clave-de-oyentes"


def esperar(condicion, timeout=3.0):
    fin = time.monotonic() + timeout
    while time.monotonic() < fin:
        if condicion():
            return True
        time.sleep(0.02)
    return False


class RelayEnHilo:
    """El relay de verdad (`crear_app`) en 127.0.0.1, con su loop en un hilo aparte."""

    def __init__(self, web_dir=None, **ajustes):
        self.ajustes = Ajustes(ingest_token=TOKEN, clave_maestra=CLAVE, **ajustes)
        self.loop = asyncio.new_event_loop()
        listo = threading.Event()
        self._hilo = threading.Thread(target=self._correr, args=(listo, web_dir), daemon=True, name="relay-test")
        self._hilo.start()
        assert listo.wait(5), "el relay no arrancó"
        self.url = f"http://127.0.0.1:{self.puerto}"
        self.ws = f"ws://127.0.0.1:{self.puerto}"

    def _correr(self, listo, web_dir) -> None:
        asyncio.set_event_loop(self.loop)
        self.app = crear_app(self.ajustes, web_dir)
        self.runner = web.AppRunner(self.app, access_log=None, shutdown_timeout=1)
        self.loop.run_until_complete(self.runner.setup())
        sitio = web.TCPSite(self.runner, "127.0.0.1", 0)
        self.loop.run_until_complete(sitio.start())
        self.puerto = self.runner.addresses[0][1]
        listo.set()
        self.loop.run_forever()

    def en_loop(self, funcion, timeout=10):
        """Corre `funcion()` en el loop del relay (si devuelve una corrutina, la espera) y devuelve el resultado."""
        async def envoltura():
            r = funcion()
            if asyncio.iscoroutine(r):
                r = await r
            return r
        return asyncio.run_coroutine_threadsafe(envoltura(), self.loop).result(timeout)

    def pedir(self, metodo, ruta, cuerpo=None, headers=None, timeout=5):
        conexion = http.client.HTTPConnection("127.0.0.1", self.puerto, timeout=timeout)
        headers = dict(headers or {})
        if isinstance(cuerpo, (dict, list)):
            cuerpo = json.dumps(cuerpo).encode()
            headers.setdefault("Content-Type", "application/json")
        conexion.request(metodo, ruta, body=cuerpo, headers=headers)
        r = conexion.getresponse()
        datos = r.read()
        conexion.close()
        return r.status, r.headers, datos

    def cerrar(self) -> None:
        asyncio.run_coroutine_threadsafe(self.runner.cleanup(), self.loop).result(10)
        self.loop.call_soon_threadsafe(self.loop.stop)
        self._hilo.join(5)


AJUSTES_RAPIDOS = dict(gracia=0.2, espera_orden=1.0, vence_logo=0.5, trabado=0.5, sin_audio=1.0, ping=5.0)


@pytest.fixture
def relay(caplog):
    caplog.set_level(logging.DEBUG, logger="cassette_relay")
    r = RelayEnHilo(**AJUSTES_RAPIDOS)
    yield r
    r.cerrar()
    assert TOKEN not in caplog.text and CLAVE not in caplog.text


def casa(relay, ruta="/casa/control", token=TOKEN):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return connect(relay.ws + ruta, additional_headers=headers, open_timeout=3, compression=None, legacy=True)


def recibir_tipo(ws, tipo, timeout=3.0):
    fin = time.monotonic() + timeout
    while time.monotonic() < fin:
        try:
            crudo = ws.recv(timeout=max(0.01, fin - time.monotonic()))
        except TimeoutError:
            break
        m = json.loads(crudo)
        if m.get("tipo") == tipo:
            return m
    raise AssertionError(f"no llegó un {tipo!r}")


def estado(seq=1, estacion="A", iconos=None, estaciones=("A", "B", "Más Gasolina F.M.", "a/b?c")):
    return {"tipo": "estado", "seq": seq, "encendida": True, "estacion": estacion, "pista": "Artista - Tema",
            "fuente": "local", "segundo": 12.5, "estaciones": list(estaciones), "iconos": iconos or {}}


def pc_en_linea(relay, iconos=None):
    """Conecta el control como la PC: hola + un estado. Devuelve el WebSocket (ya consumida la primera demanda)."""
    ws = casa(relay)
    ws.send(json.dumps({"tipo": "hola", "protocolo": 1, "calidades": [64, 96, 160]}))
    recibir_tipo(ws, "demanda")
    ws.send(json.dumps(estado(iconos=iconos)))
    assert esperar(lambda: relay.en_loop(lambda: relay.app[CASA].radio()) is not None)
    return ws


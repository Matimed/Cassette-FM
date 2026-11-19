import base64
import hashlib
import json
import logging
import queue
import socket
import threading
import time
from types import SimpleNamespace

import pytest
from websockets.datastructures import Headers
from websockets.http11 import Response
from websockets.sync.server import serve

from cassette_fm.puente_nube import CALIDADES, PROTOCOLO, Espera, PuenteNube, mensaje_estado
from cassette_fm.radio import SinEstaciones

CLAVE = "clave-secreta-de-prueba"


def esperar(condicion, timeout=3.0):
    fin = time.monotonic() + timeout
    while time.monotonic() < fin:
        if condicion():
            return True
        time.sleep(0.02)
    return False


class RelayFalso:
    """El lado relay del protocolo, en 127.0.0.1: guarda lo que llega por cada conexión y puede mandar, cortar y
    rechazar con 401."""

    def __init__(self):
        self.rechazar = False
        self.intentos = 0
        self.conexiones: list[SimpleNamespace] = []
        self._servidor = serve(self._atender, "127.0.0.1", 0, process_request=self._pedido, compression=None)
        self.puerto = self._servidor.socket.getsockname()[1]
        self.url = f"ws://127.0.0.1:{self.puerto}"
        threading.Thread(target=self._servidor.serve_forever, daemon=True).start()

    def _pedido(self, conexion, pedido):
        self.intentos += 1
        if self.rechazar:
            return conexion.respond(401, "no autorizado\n")
        return None

    def _atender(self, ws):
        c = SimpleNamespace(ws=ws, ruta=ws.request.path, headers=ws.request.headers, mensajes=queue.Queue(),
                            binarios=queue.Queue(), abierta=True)
        self.conexiones.append(c)
        try:
            for m in ws:
                (c.binarios if isinstance(m, bytes) else c.mensajes).put(m)
        except Exception:
            pass
        c.abierta = False

    def control(self, n=-1):
        assert esperar(lambda: any(c.ruta == "/casa/control" for c in self.conexiones))
        return [c for c in self.conexiones if c.ruta == "/casa/control"][n]

    def recibir(self, c, timeout=3.0):
        return json.loads(c.mensajes.get(timeout=timeout))

    def recibir_tipo(self, c, tipo, timeout=3.0):
        fin = time.monotonic() + timeout
        while time.monotonic() < fin:
            try:
                m = self.recibir(c, max(0.01, fin - time.monotonic()))
            except queue.Empty:
                break
            if m["tipo"] == tipo:
                return m
        raise AssertionError(f"no llegó un {tipo!r}")

    def mandar(self, c, mensaje):
        c.ws.send(mensaje if isinstance(mensaje, (str, bytes)) else json.dumps(mensaje))

    def cerrar(self):
        self._servidor.shutdown()


class RadioFalsa:
    def __init__(self, estaciones=("A", "B", "Más Gasolina F.M.", "a/b?c")):
        self._estaciones = list(estaciones)
        self.encendida = True
        self.datos = {"encendida": True, "estacion": "A", "pista": "Tema 1", "volumen": 40, "monitor_local": False,
                      "estaciones": list(estaciones), "fuente": "spotify", "segundo": 3.0, "iconos": {}}
        self.ordenes = []
        self._interesados = []
        self.falla = None

    def estado(self):
        return dict(self.datos)

    def estaciones(self):
        return [SimpleNamespace(nombre=n) for n in self._estaciones]

    def escuchar_cambios(self, funcion):
        self._interesados.append(funcion)

    def cambiar(self, **campos):
        self.datos.update(campos)
        for f in self._interesados:
            f()

    def sintonizar(self, nombre, oir_aca=True):
        if self.falla:
            raise self.falla
        self.ordenes.append(("sintonizar", nombre, oir_aca))
        self.cambiar(estacion=nombre)

    def siguiente(self, oir_aca=True):
        self.ordenes.append(("siguiente", oir_aca))

    def anterior(self, oir_aca=True):
        self.ordenes.append(("anterior", oir_aca))


class EsperaCorta(Espera):
    def __init__(self):
        super().__init__(minimo=0.05, maximo=0.05, azar=lambda: 1.0)


@pytest.fixture
def relay():
    r = RelayFalso()
    yield r
    r.cerrar()


@pytest.fixture
def armar(relay, caplog):
    caplog.set_level(logging.DEBUG, logger="cassette_fm")
    creados = []

    def crear(radio=None, **kw):
        kw.setdefault("espera", EsperaCorta())
        p = PuenteNube(radio or RadioFalsa(), kw.pop("difusores", None), kw.pop("url", relay.url),
                       kw.pop("token", lambda: CLAVE), **kw)
        creados.append(p)
        p.iniciar()
        return p

    yield crear
    for p in creados:
        p.cerrar()
    assert CLAVE not in caplog.text


def test_al_conectar_manda_hola_y_estado(relay, armar):
    armar()
    c = relay.control()
    assert c.headers["Authorization"] == f"Bearer {CLAVE}"
    hola = relay.recibir(c)
    assert hola == {"tipo": "hola", "protocolo": PROTOCOLO, "calidades": list(CALIDADES)} and PROTOCOLO == 1
    estado = relay.recibir(c)
    assert estado["tipo"] == "estado" and estado["seq"] == 1 and estado["estacion"] == "A"


def test_estado_sin_volumen_ni_rutas(relay, armar, tmp_path):
    logo = tmp_path / "logo.png"
    logo.write_bytes(b"\x89PNG...")
    radio = RadioFalsa()
    radio.datos["iconos"] = {"A": str(logo), "B": str(tmp_path / "no-existe.png")}
    armar(radio)
    estado = relay.recibir_tipo(relay.control(), "estado")
    assert "volumen" not in estado and "monitor_local" not in estado
    assert set(estado["iconos"]) == {"A"} and str(tmp_path) not in json.dumps(estado)


def test_mensaje_estado_tiene_los_campos_del_status_de_la_lan():
    m = mensaje_estado(RadioFalsa().estado(), 7)
    assert set(m) == {"tipo", "seq", "encendida", "estacion", "pista", "estaciones", "fuente", "segundo", "iconos"}
    assert m["seq"] == 7


def test_rafaga_de_cambios_manda_el_ultimo_sin_inundar(relay, armar):
    radio = RadioFalsa()
    armar(radio)
    c = relay.control()
    relay.recibir_tipo(c, "estado")
    time.sleep(0.6)
    for i in range(2, 5):
        radio.cambiar(pista=f"Tema {i}")
        time.sleep(0.03)
    recibidos = []
    while True:
        try:
            recibidos.append(relay.recibir(c, 1.2))
        except queue.Empty:
            break
    assert 1 <= len(recibidos) <= 2 and recibidos[-1]["pista"] == "Tema 4"
    assert [m["seq"] for m in recibidos] == list(range(2, 2 + len(recibidos)))


def test_sintonizar_desde_la_nube(relay, armar):
    radio = RadioFalsa()
    armar(radio)
    c = relay.control()
    relay.mandar(c, {"tipo": "sintonizar", "id": "o1", "estacion": "B"})
    assert relay.recibir_tipo(c, "resultado") == {"tipo": "resultado", "id": "o1", "ok": True}
    assert radio.ordenes == [("sintonizar", "B", False)]
    assert relay.recibir_tipo(c, "estado")["estacion"] == "B"


@pytest.mark.parametrize("nombre", ["Más Gasolina F.M.", "a/b?c"])
def test_nombre_con_acentos_y_barra(relay, armar, nombre):
    radio = RadioFalsa()
    armar(radio)
    c = relay.control()
    relay.mandar(c, {"tipo": "sintonizar", "id": 5, "estacion": nombre})
    assert relay.recibir_tipo(c, "resultado")["ok"] is True and radio.ordenes == [("sintonizar", nombre, False)]


def test_emisora_inexistente_devuelve_error(relay, armar):
    radio = RadioFalsa()
    armar(radio)
    c = relay.control()
    relay.mandar(c, {"tipo": "sintonizar", "id": "x", "estacion": "Z"})
    assert relay.recibir_tipo(c, "resultado") == {"tipo": "resultado", "id": "x", "ok": False,
                                                  "error": "esa emisora no existe"}
    assert radio.ordenes == []


def test_sin_estaciones_devuelve_error(relay, armar):
    radio = RadioFalsa()
    radio.falla = SinEstaciones("no hay")
    armar(radio)
    c = relay.control()
    relay.mandar(c, {"tipo": "sintonizar", "id": "x", "estacion": "A"})
    assert relay.recibir_tipo(c, "resultado")["error"] == "no hay estaciones"


def test_siguiente_y_anterior(relay, armar):
    radio = RadioFalsa()
    armar(radio)
    c = relay.control()
    relay.mandar(c, {"tipo": "siguiente", "id": 1})
    relay.mandar(c, {"tipo": "anterior", "id": 2})
    assert relay.recibir_tipo(c, "resultado")["id"] == 1 and relay.recibir_tipo(c, "resultado")["id"] == 2
    assert radio.ordenes == [("siguiente", False), ("anterior", False)]


def test_tipo_desconocido_y_json_roto_no_cortan(relay, armar, caplog):
    radio = RadioFalsa()
    armar(radio)
    c = relay.control()
    relay.mandar(c, {"tipo": "bailar"})
    relay.mandar(c, "{no es json")
    relay.mandar(c, b"\x00\x01")
    relay.mandar(c, {"tipo": "siguiente", "id": 9})
    assert relay.recibir_tipo(c, "resultado")["id"] == 9
    assert len([x for x in relay.conexiones if x.ruta == "/casa/control"]) == 1
    assert "bailar" in caplog.text


def test_reconecta_si_el_relay_corta(relay, armar):
    p = armar()
    primera = relay.control()
    relay.recibir_tipo(primera, "estado")
    primera.ws.close()
    assert esperar(lambda: len([x for x in relay.conexiones if x.ruta == "/casa/control"]) == 2)
    segunda = relay.control()
    assert relay.recibir(segunda)["tipo"] == "hola" and relay.recibir(segunda)["seq"] == 1
    assert esperar(lambda: p.info()["conectado"])


class RelayMudo:
    """Acepta el WebSocket y después no contesta nada (ni los pings): un TCP medio abierto."""

    def __init__(self):
        self.conexiones = 0
        self._s = socket.socket()
        self._s.bind(("127.0.0.1", 0))
        self._s.listen()
        self.url = f"ws://127.0.0.1:{self._s.getsockname()[1]}"
        self._abiertos = []
        threading.Thread(target=self._aceptar, daemon=True).start()

    def _aceptar(self):
        while True:
            try:
                s, _ = self._s.accept()
            except OSError:
                return
            pedido = b""
            while b"\r\n\r\n" not in pedido:
                pedido += s.recv(4096)
            clave = [l.split(b":", 1)[1].strip() for l in pedido.split(b"\r\n") if l.lower().startswith(b"sec-websocket-key")][0]
            acepta = base64.b64encode(hashlib.sha1(clave + b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11").digest())
            s.sendall(b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                      b"Sec-WebSocket-Accept: " + acepta + b"\r\n\r\n")
            self._abiertos.append(s)
            self.conexiones += 1

    def cerrar(self):
        self._s.close()
        for s in self._abiertos:
            s.close()


def test_ping_sin_respuesta_reconecta(armar):
    mudo = RelayMudo()
    try:
        armar(url=mudo.url, ping_segundos=0.2)
        assert esperar(lambda: mudo.conexiones >= 2, 4)
    finally:
        mudo.cerrar()


def test_401_no_reintenta_en_bucle(relay, armar, caplog):
    relay.rechazar = True
    p = armar(espera_401=60)
    assert esperar(lambda: p.info()["error"] is not None)
    time.sleep(0.5)
    assert relay.intentos == 1 and "clave" in p.info()["error"] and not p.info()["conectado"]
    assert "clave" in caplog.text


def test_reconectar_usa_la_clave_nueva(relay, armar):
    claves = [CLAVE]
    p = armar(token=lambda: claves[-1])
    relay.recibir_tipo(relay.control(), "estado")
    claves.append("otra-clave")
    p.reconectar()
    assert esperar(lambda: len([x for x in relay.conexiones if x.ruta == "/casa/control"]) == 2)
    assert relay.control().headers["Authorization"] == "Bearer otra-clave"


def test_cerrar_termina_los_hilos(relay):
    antes = set(threading.enumerate())
    p = PuenteNube(RadioFalsa(), None, relay.url, lambda: CLAVE, espera=EsperaCorta())
    p.iniciar()
    relay.recibir_tipo(relay.control(), "estado")
    p.cerrar()
    assert esperar(lambda: not [t for t in set(threading.enumerate()) - antes if t.name.startswith("nube")])
    assert esperar(lambda: not relay.control().abierta)


def test_espera_crece_hasta_el_maximo_y_se_reinicia():
    e = Espera(minimo=1.0, maximo=30.0, azar=lambda: 1.0)
    assert [e.siguiente() for _ in range(7)] == [1, 2, 4, 8, 16, 30, 30]
    e.reiniciar()
    assert e.siguiente() == 1
    con_azar = Espera(minimo=1.0, maximo=30.0, azar=lambda: 0.0)
    assert 0.5 <= con_azar.siguiente() < 1.0

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

    def __init__(self, buffer_recepcion: int | None = None):
        self.rechazar = False
        self.audio_mudo = False            # acepta el audio y no lo lee nunca (relay colgado)
        self._fin = threading.Event()
        self.intentos = 0
        self.conexiones: list[SimpleNamespace] = []
        escucha = socket.socket()
        if buffer_recepcion:                # chico: un relay que no lee traba de verdad el envío de la PC
            escucha.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, buffer_recepcion)
        escucha.bind(("127.0.0.1", 0))
        escucha.listen()
        self._servidor = serve(self._atender, sock=escucha, process_request=self._pedido, compression=None,
                               close_timeout=1)
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
        if self.audio_mudo and c.ruta.startswith("/casa/audio"):
            self._fin.wait()
            return
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
        self._fin.set()
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


# --- audio bajo demanda ---

from cassette_fm.lan_stream import FUENTE_MONITOR, Difusor, Difusores  # noqa: E402
from test_lan_stream import ProcesoFalso  # noqa: E402


class Codificadores:
    """Los `gst-launch` falsos que lanzan los `Difusor`."""

    def __init__(self):
        self.procesos: list[ProcesoFalso] = []

    def lanzar(self, comando):
        p = ProcesoFalso(comando)
        self.procesos.append(p)
        return p

    def de(self, kbps):
        return [p for p in self.procesos if f"bitrate={kbps}" in p.comando]

    def registro(self, **kw):
        kw.setdefault("gracia_segundos", 0.1)
        return Difusores(lambda: FUENTE_MONITOR, crear=lambda f, **o: Difusor(
            f, lanzar=self.lanzar, arranque_segundos=0.0, **{**o, **kw}))


def _audios(relay, kbps=None):
    return [c for c in relay.conexiones if c.ruta.startswith("/casa/audio")
            and (kbps is None or c.ruta == f"/casa/audio?calidad={kbps}")]


@pytest.fixture
def gst():
    return Codificadores()


def _pedir(relay, calidades, n=-1):
    c = relay.control(n)
    relay.recibir_tipo(c, "estado")
    relay.mandar(c, {"tipo": "demanda", "calidades": calidades})
    return c


def test_demanda_abre_audio_en_esa_calidad(relay, armar, gst):
    p = armar(difusores=gst.registro())
    _pedir(relay, [96])
    assert esperar(lambda: _audios(relay, 96) and gst.de(96))
    audio = _audios(relay, 96)[0]
    assert audio.headers["Authorization"] == f"Bearer {CLAVE}"
    gst.de(96)[0].emitir(b"frame-1")
    assert audio.binarios.get(timeout=2) == b"frame-1"
    gst.de(96)[0].emitir(b"frame-2")
    assert audio.binarios.get(timeout=2) == b"frame-2"
    assert esperar(lambda: p.info()["subiendo"] == [96])


def test_demanda_vacia_cierra_y_el_codificador_se_apaga(relay, armar, gst):
    registro = gst.registro()
    p = armar(difusores=registro)
    c = _pedir(relay, [64])
    assert esperar(lambda: _audios(relay, 64) and gst.de(64))
    relay.mandar(c, {"tipo": "demanda", "calidades": []})
    assert esperar(lambda: not _audios(relay, 64)[0].abierta)
    assert esperar(lambda: p.info()["subiendo"] == [])

    def apagado():
        registro.revisar_fuente()          # lo que hace el servicio cada segundo
        return gst.de(64)[0].terminado

    assert esperar(apagado)


def test_dos_calidades_a_la_vez(relay, armar, gst):
    p = armar(difusores=gst.registro())
    _pedir(relay, [64, 160])
    assert esperar(lambda: _audios(relay, 64) and _audios(relay, 160))
    assert esperar(lambda: p.info()["subiendo"] == [64, 160])


def test_calidad_desconocida_se_ignora(relay, armar, gst, caplog):
    armar(difusores=gst.registro())
    c = _pedir(relay, [128, "x", 96])
    assert esperar(lambda: _audios(relay, 96))
    time.sleep(0.2)
    assert len(_audios(relay)) == 1 and "128" in caplog.text


def test_si_el_difusor_corta_la_conexion_se_reabre_en_vivo(relay, armar, gst):
    registro = gst.registro()
    armar(difusores=registro)
    _pedir(relay, [96])
    assert esperar(lambda: _audios(relay, 96))
    registro.de(96).cortar_oyentes()       # lo que hace con un oyente que se atrasó demasiado
    assert esperar(lambda: len(_audios(relay, 96)) == 2)
    assert not _audios(relay, 96)[0].abierta or esperar(lambda: not _audios(relay, 96)[0].abierta)


def test_control_caido_mantiene_el_audio_y_despues_de_la_gracia_lo_cierra(relay, armar, gst):
    armar(difusores=gst.registro(), gracia_control=0.5, espera_401=60)
    c = _pedir(relay, [96])
    assert esperar(lambda: _audios(relay, 96))
    relay.rechazar = True                  # el control no puede volver
    c.ws.close()
    time.sleep(0.25)
    assert _audios(relay, 96)[0].abierta
    assert esperar(lambda: not _audios(relay, 96)[0].abierta, 2)
    assert len(_audios(relay, 96)) == 1


def test_demanda_al_reconectar_corrige(relay, armar, gst):
    armar(difusores=gst.registro())
    c = _pedir(relay, [96])
    assert esperar(lambda: _audios(relay, 96))
    c.ws.close()
    assert esperar(lambda: len([x for x in relay.conexiones if x.ruta == "/casa/control"]) == 2)
    assert _audios(relay, 96)[0].abierta
    _pedir(relay, [])
    assert esperar(lambda: not _audios(relay, 96)[0].abierta)


def test_reconectar_corta_y_reabre_audio_con_la_clave_nueva(relay, armar, gst):
    claves = [CLAVE]
    p = armar(difusores=gst.registro(), token=lambda: claves[-1])
    _pedir(relay, [96])
    assert esperar(lambda: _audios(relay, 96))
    claves.append("otra")
    p.reconectar()
    assert esperar(lambda: len(_audios(relay, 96)) == 2)
    assert _audios(relay, 96)[-1].headers["Authorization"] == "Bearer otra"


def test_nube_160_y_lan_comparten_codificador(relay, armar, gst):
    registro = gst.registro()
    oyente_lan = registro.de(160).suscribir()
    armar(difusores=registro)
    _pedir(relay, [160])
    assert esperar(lambda: _audios(relay, 160))
    gst.de(160)[0].emitir(b"compartido")
    assert _audios(relay, 160)[0].binarios.get(timeout=2) == b"compartido"
    assert oyente_lan.get(timeout=2) == b"compartido"
    assert len(gst.de(160)) == 1
    registro.de(160).desuscribir(oyente_lan)


# --- logos ---

from cassette_fm.puente_nube import url_icono  # noqa: E402


def test_url_icono():
    assert url_icono("wss://relay.x.com", "Más Gasolina F.M.", "abc") == \
        "https://relay.x.com/casa/icono/M%C3%A1s%20Gasolina%20F.M.?v=abc"
    assert url_icono("ws://127.0.0.1:9000", "a/b?c", "v1") == "http://127.0.0.1:9000/casa/icono/a%2Fb%3Fc?v=v1"


class Subidor:
    def __init__(self, falla=None):
        self.subidas = []
        self.falla = falla

    def __call__(self, url, token, datos, tipo):
        if self.falla:
            raise self.falla
        self.subidas.append((url, token, datos, tipo))


def _radio_con_logo(tmp_path):
    logo = tmp_path / "logo.png"
    logo.write_bytes(b"\x89PNG-datos")
    radio = RadioFalsa()
    radio.datos["iconos"] = {"Más Gasolina F.M.": str(logo)}
    return radio


def test_pedir_icono_sube_el_logo(relay, armar, tmp_path):
    subidor = Subidor()
    armar(_radio_con_logo(tmp_path), subir=subidor)
    c = relay.control()
    version = relay.recibir_tipo(c, "estado")["iconos"]["Más Gasolina F.M."]
    relay.mandar(c, {"tipo": "pedir_icono", "estacion": "Más Gasolina F.M."})
    assert esperar(lambda: subidor.subidas)
    assert subidor.subidas == [(url_icono(relay.url, "Más Gasolina F.M.", version), CLAVE, b"\x89PNG-datos",
                                "image/png")]


def test_pedir_icono_de_emisora_sin_logo_no_sube(relay, armar, tmp_path):
    subidor = Subidor()
    armar(_radio_con_logo(tmp_path), subir=subidor)
    c = relay.control()
    relay.mandar(c, {"tipo": "pedir_icono", "estacion": "A"})
    relay.mandar(c, {"tipo": "siguiente", "id": 1})
    assert relay.recibir_tipo(c, "resultado")["id"] == 1 and subidor.subidas == []


def test_logo_que_falla_al_subir_no_corta_el_control(relay, armar, tmp_path, caplog):
    armar(_radio_con_logo(tmp_path), subir=Subidor(falla=OSError("sin red")))
    c = relay.control()
    relay.mandar(c, {"tipo": "pedir_icono", "estacion": "Más Gasolina F.M."})
    relay.mandar(c, {"tipo": "siguiente", "id": 2})
    assert relay.recibir_tipo(c, "resultado")["id"] == 2
    assert esperar(lambda: "sin red" in caplog.text)
    assert len([x for x in relay.conexiones if x.ruta == "/casa/control"]) == 1


def test_subir_icono_hace_un_put_con_la_clave(tmp_path):
    from http.server import BaseHTTPRequestHandler, HTTPServer
    from cassette_fm.puente_nube import subir_icono
    recibido = {}

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a): pass

        def do_PUT(self):
            recibido.update(ruta=self.path, auth=self.headers["Authorization"], tipo=self.headers["Content-Type"],
                            datos=self.rfile.read(int(self.headers["Content-Length"])))
            self.send_response(204)
            self.end_headers()

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.handle_request, daemon=True).start()
    subir_icono(f"http://127.0.0.1:{srv.server_port}/casa/icono/A?v=1", CLAVE, b"img", "image/png")
    srv.server_close()
    assert recibido == {"ruta": "/casa/icono/A?v=1", "auth": f"Bearer {CLAVE}", "tipo": "image/png", "datos": b"img"}


# --- revisión final: subida trabada, logos aparte, error visible, hilos que no mueren ---

def _inundar(proceso, parar):
    def correr():
        while not parar.is_set():
            try:
                proceso.emitir(b"\x00" * 4096)
            except OSError:
                return
            time.sleep(0.02)                   # ~200 KB/s: llena los buffers sin desbordar la cola del Difusor
    threading.Thread(target=correr, daemon=True).start()


@pytest.fixture
def relay_mudo():
    r = RelayFalso(buffer_recepcion=4096)
    r.audio_mudo = True
    yield r
    r.cerrar()


def _trabada(p):
    """True si el hilo de audio está metido en un envío al socket."""
    import sys
    import traceback
    for hilo in threading.enumerate():
        if hilo.name.startswith("nube-audio") and hilo.ident in sys._current_frames():
            if any("sendall" in linea for linea in traceback.format_stack(sys._current_frames()[hilo.ident])):
                return True
    return False


def test_subida_trabada_no_traba_las_ordenes_ni_el_cierre(relay_mudo, gst, caplog):
    relay = relay_mudo
    p = PuenteNube(RadioFalsa(), gst.registro(), relay.url, lambda: CLAVE, espera=EsperaCorta(),
                   timeout_envio_audio=30)
    p.iniciar()
    c = _pedir(relay, [96])
    assert esperar(lambda: _audios(relay, 96) and gst.de(96))
    parar = threading.Event()
    _inundar(gst.de(96)[0], parar)
    try:
        assert esperar(lambda: _trabada(p), 5)
        relay.mandar(c, {"tipo": "demanda", "calidades": []})
        relay.mandar(c, {"tipo": "siguiente", "id": "rapida"})
        assert relay.recibir_tipo(c, "resultado", timeout=2)["id"] == "rapida"
        inicio = time.monotonic()
        p.cerrar()
        assert time.monotonic() - inicio < 3
    finally:
        parar.set()
        p.cerrar()


def test_subida_trabada_se_detecta_y_se_reabre(relay_mudo, gst):
    relay = relay_mudo
    p = PuenteNube(RadioFalsa(), gst.registro(), relay.url, lambda: CLAVE, espera=EsperaCorta(),
                   timeout_envio_audio=0.5)
    p.iniciar()
    _pedir(relay, [96])
    assert esperar(lambda: _audios(relay, 96) and gst.de(96))
    parar = threading.Event()
    _inundar(gst.de(96)[0], parar)
    try:
        assert esperar(lambda: _trabada(p), 5)
        assert esperar(lambda: len(_audios(relay, 96)) >= 2, 6)
    finally:
        parar.set()
        p.cerrar()


def test_los_logos_no_demoran_las_ordenes(relay, armar, tmp_path):
    lento = threading.Event()

    def subidor(*a):
        lento.wait(5)

    armar(_radio_con_logo(tmp_path), subir=subidor)
    c = relay.control()
    relay.mandar(c, {"tipo": "pedir_icono", "estacion": "Más Gasolina F.M."})
    relay.mandar(c, {"tipo": "siguiente", "id": "ya"})
    try:
        assert relay.recibir_tipo(c, "resultado", timeout=1)["id"] == "ya"
    finally:
        lento.set()


def test_info_trae_el_error_y_cuanto_hace_que_esta_conectado(relay, armar):
    relay.rechazar = True
    p = armar(espera_401=0.2)
    assert esperar(lambda: p.info()["error"] is not None)
    assert p.info()["conectado_hace"] is None and "clave" in p.info()["error"]
    relay.rechazar = False
    assert esperar(lambda: p.info()["conectado"])
    assert p.info()["error"] is None and p.info()["conectado_hace"] >= 0


def test_un_error_inesperado_no_mata_el_control(relay, armar, caplog):
    radio = RadioFalsa()
    original, fallas = radio.estado, []

    def estado():
        if not fallas:
            fallas.append(1)
            raise RuntimeError("se rompió algo")
        return original()

    radio.estado = estado
    armar(radio)
    assert esperar(lambda: len([x for x in relay.conexiones if x.ruta == "/casa/control"]) >= 2)
    assert relay.recibir_tipo(relay.control(), "estado")["seq"] == 1
    assert "se rompió algo" in caplog.text


def test_un_error_inesperado_no_mata_el_audio(relay, armar, gst):
    registro = gst.registro()
    real, fallas = registro.de, []

    def de(kbps):
        if not fallas:
            fallas.append(1)
            raise RuntimeError("registro roto")
        return real(kbps)

    registro.de = de
    armar(difusores=registro)
    _pedir(relay, [96])
    assert esperar(lambda: gst.de(96), 6)


def test_latido_si_no_hay_nada_que_mandar(relay, armar):
    armar(latido_segundos=0.3)
    c = relay.control()
    relay.recibir_tipo(c, "estado")
    assert relay.recibir_tipo(c, "latido", timeout=1.5) == {"tipo": "latido"}


def test_sin_latido_mientras_hay_otros_mensajes(relay, armar):
    radio = RadioFalsa()
    armar(radio, latido_segundos=0.5, intervalo_estado=0.05)
    c = relay.control()
    relay.recibir_tipo(c, "estado")
    fin = time.monotonic() + 1.2
    tipos = []
    while time.monotonic() < fin:
        radio.cambiar(segundo=time.monotonic())
        time.sleep(0.1)
        while not c.mensajes.empty():
            tipos.append(json.loads(c.mensajes.get())["tipo"])
    assert "estado" in tipos and "latido" not in tipos

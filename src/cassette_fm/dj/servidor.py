import json
import logging
import re
import signal
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from cassette_fm import __version__
from cassette_fm.dj.cola import Cola
from cassette_fm.dj.config import ConfigServicioDJ, RutasDJ
from cassette_fm.dj.guiones import RegistroGuiones
from cassette_fm.dj.hechos import FuenteHechos
from cassette_fm.dj.hechos.cache import CacheHechos
from cassette_fm.dj.hechos.clima import ClienteClima
from cassette_fm.dj.hechos.musicbrainz import ClienteMusicBrainz
from cassette_fm.dj.lexico import Lexico
from cassette_fm.dj.pedido import leer_pedido
from cassette_fm.dj.produccion import Productor
from cassette_fm.dj.sintetizador import ErrorModelos, Sintetizador, faltan_modelos, fonemizador

_log = logging.getLogger("cassette_fm")
_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")
_INTERVENCION = re.compile(r"/intervenciones/([^/]+)(/audio)?")
MAX_CUERPO = 64 * 1024
MAX_DRENAR = 1024 * 1024
_MANTENIMIENTO_SEGUNDOS = 30.0


def crear_servidor(cola: Cola, sintetizador, host: str, puerto: int, modelos_dir: Path,
                   timeout: float = 10.0) -> ThreadingHTTPServer:
    if host not in ("127.0.0.1", "localhost", "::1"):
        _log.warning("el servicio DJ escucha en %s sin autenticación: usalo solo en una red de confianza", host)

    class Manejador(BaseHTTPRequestHandler):
        # tiempo máximo de espera por lectura: una conexión que no manda lo prometido no retiene el hilo
        timeout = None

        def log_message(self, *args):
            pass

        def _enviar(self, codigo: int, cuerpo: bytes, tipo: str) -> None:
            self.send_response(codigo)
            self.send_header("Content-Type", tipo)
            self.send_header("Content-Length", str(len(cuerpo)))
            self.end_headers()
            self.wfile.write(cuerpo)

        def _json(self, codigo: int, datos) -> None:
            self._enviar(codigo, json.dumps(datos, ensure_ascii=False).encode("utf-8"),
                         "application/json; charset=utf-8")

        def _error(self, codigo: int, mensaje: str) -> None:
            self._json(codigo, {"error": mensaje})

        def _protegido(self, accion) -> None:
            try:
                accion(self.path.split("?", 1)[0])
            except TimeoutError:
                self.close_connection = True
                self._error(408, "el pedido no llegó completo a tiempo")
            except Exception:
                _log.exception("error inesperado en %s %s", self.command, self.path)
                self._error(500, "error interno (mirá el log del servicio)")

        def do_GET(self):
            self._protegido(self._get)

        def do_POST(self):
            self._protegido(self._post)

        def do_DELETE(self):
            self._protegido(self._delete)

        def _id_de(self, ruta: str):
            m = _INTERVENCION.fullmatch(ruta)
            if not m or not _ID.fullmatch(m.group(1)):
                return None, False
            return m.group(1), bool(m.group(2))

        def _get(self, ruta: str) -> None:
            if ruta == "/salud":
                self._json(200, {"ok": True, "modelo_cargado": sintetizador.cargado,
                                 "faltan_modelos": [p.name for p in faltan_modelos(modelos_dir)],
                                 "trabajos": cola.contadores()})
            elif ruta == "/voces":
                try:
                    self._json(200, {"voces": sintetizador.voces()})
                except ErrorModelos as e:
                    self._error(503, str(e))
            else:
                id_, audio = self._id_de(ruta)
                if id_ is None:
                    return self._error(404, f"ruta desconocida: {ruta}")
                estado = cola.estado(id_)
                if estado is None:
                    return self._error(404, f"no existe la intervención {id_}")
                if not audio:
                    return self._json(200, estado)
                if estado["estado"] != "listo":
                    return self._error(409, "todavía no está listo")
                archivo = cola.audio(id_)
                if archivo is None:
                    return self._error(404, "el audio ya no está disponible")
                self._enviar(200, archivo.read_bytes(), "audio/wav")

        def _post(self, ruta: str) -> None:
            if ruta != "/intervenciones":
                return self._error(404, f"ruta desconocida: {ruta}")
            crudo = (self.headers.get("Content-Length") or "0").strip()
            if not (crudo.isascii() and crudo.isdigit()):
                return self._error(400, "Content-Length inválido")
            largo = int(crudo)
            if largo > MAX_CUERPO:
                restante = largo if largo <= MAX_DRENAR else 0
                while restante > 0:                       # se lee y descarta para poder contestar
                    restante -= len(self.rfile.read(min(restante, 65536)) or b"\0" * restante)
                return self._error(413, f"el pedido es demasiado grande (máximo {MAX_CUERPO} bytes)")
            cuerpo = self.rfile.read(largo)
            if len(cuerpo) < largo:
                return self._error(400, "el cuerpo está incompleto")
            try:
                datos = json.loads(cuerpo.decode("utf-8"))
            except (ValueError, UnicodeDecodeError, RecursionError):
                return self._error(400, "el cuerpo no es JSON válido")
            try:
                pedido = leer_pedido(datos)
            except ValueError as e:
                return self._error(400, str(e))
            try:
                self._json(202, {"id": cola.enviar(pedido)})
            except RuntimeError as e:
                self._error(503, str(e))

        def _delete(self, ruta: str) -> None:
            id_, audio = self._id_de(ruta)
            if id_ is None or audio:
                return self._error(404, f"ruta desconocida: {ruta}")
            if cola.estado(id_) is None:
                return self._error(404, f"no existe la intervención {id_}")
            self._json(200, {"cancelado": cola.cancelar(id_)})

    Manejador.timeout = timeout
    servidor = ThreadingHTTPServer((host, puerto), Manejador)
    servidor.daemon_threads = True
    return servidor


def servir(config: ConfigServicioDJ, rutas: RutasDJ, parar: threading.Event | None = None,
           fabrica_sintetizador=None) -> None:
    """Arma el servicio y lo corre hasta SIGTERM/SIGINT o hasta que se setee `parar`."""
    parar = parar or threading.Event()
    if threading.current_thread() is threading.main_thread():
        for senal in (signal.SIGTERM, signal.SIGINT):
            signal.signal(senal, lambda *_: parar.set())
    sintetizador = Sintetizador(config, fabrica=fabrica_sintetizador)
    cache = CacheHechos(rutas.hechos)
    hechos = FuenteHechos(ClienteClima(config, cache), ClienteMusicBrainz(config, cache, version=__version__),
                          espera_segundos=config.timeout_hechos_segundos + 1)
    productor = Productor(config, rutas, sintetizador, fonemizador(), Lexico.cargar(rutas.lexico),
                          RegistroGuiones(rutas.guiones), hechos=hechos)
    cola = Cola(productor, trabajadores=config.trabajadores, retencion_segundos=config.retencion_minutos * 60)
    servidor = crear_servidor(cola, sintetizador, config.host, config.puerto, config.modelos_dir)
    threading.Thread(target=lambda: servidor.serve_forever(poll_interval=0.05), daemon=True,
                     name="dj-http").start()
    faltan = faltan_modelos(config.modelos_dir)
    if faltan:
        _log.warning("faltan los modelos de Kokoro (%s) en %s: los pedidos van a fallar hasta que corras "
                     "`cassette-dj modelos`", ", ".join(p.name for p in faltan), config.modelos_dir)
    _log.info("servicio DJ escuchando en %s:%d", config.host, servidor.server_address[1])

    def mantener():
        while not parar.wait(_MANTENIMIENTO_SEGUNDOS):
            if sintetizador.descargar_si_ocioso():
                _log.info("Kokoro descargado de la memoria por inactividad")

    threading.Thread(target=mantener, daemon=True, name="dj-memoria").start()
    try:
        parar.wait()
    finally:
        for paso in (servidor.shutdown, servidor.server_close, cola.detener):
            try:
                paso()
            except Exception:
                _log.exception("error al apagar (%s)", getattr(paso, "__qualname__", paso))

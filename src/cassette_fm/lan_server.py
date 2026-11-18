"""El servidor de la radio por la red: el audio del bus, el estado y el cambio de emisora, y nada más.

Es un servidor aparte de la API de dueño (que sigue en loopback): expone solo `/status`, `/station/{id}`, `/stream` e
`/icon/{id}`, todas con la clave de oyente (`Authorization: Bearer <clave>`)."""
import hmac
import json
import logging
import queue
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from cassette_fm.lan_stream import CodificadorNoDisponible, SinCapacidad
from cassette_fm.radio import SinEstaciones

_log = logging.getLogger("cassette_fm")

_CAMPOS = ("encendida", "estacion", "pista", "estaciones", "fuente", "segundo")


def estado_publico(estado: dict, iconos: dict[str, str] | None = None) -> dict:
    """Lo único del estado de la radio que ve un oyente (sin volumen ni nada de esta PC)."""
    publico = {campo: estado.get(campo) for campo in _CAMPOS}
    publico["estaciones"] = list(publico["estaciones"] or [])
    publico["iconos"] = dict(iconos or {})
    return publico


def crear_servidor_lan(radio, difusor, token: str, host: str, puerto: int) -> ThreadingHTTPServer:
    esperado = f"Bearer {token}".encode()

    class Manejador(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.0"        # el stream termina al cerrar la conexión

        def log_message(self, formato, *args):
            _log.debug("lan %s", formato % args)

        def _autorizado(self) -> bool:
            recibido = (self.headers.get("Authorization") or "").encode("utf-8", "replace")
            return hmac.compare_digest(recibido, esperado)

        def _responder(self, codigo: int, cuerpo: dict | None = None, extra: dict | None = None) -> None:
            datos = json.dumps(cuerpo if cuerpo is not None else {}, ensure_ascii=False).encode("utf-8")
            self.send_response(codigo)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(datos)))
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(datos)

        def _error(self, codigo: int, mensaje: str) -> None:
            self._responder(codigo, {"error": mensaje})

        def _no_permitido(self) -> None:
            self._responder(405, {"error": "método no permitido"}, {"Allow": "GET, POST"})

        do_PUT = do_DELETE = do_PATCH = do_OPTIONS = do_HEAD = _no_permitido

        def _ruta(self) -> str:
            return urllib.parse.urlsplit(self.path).path

        def do_GET(self):
            ruta = self._ruta()
            if ruta == "/status":
                accion = self._status
            elif ruta == "/stream":
                accion = self._stream
            elif ruta.startswith("/icon/"):
                accion = self._icono
            else:
                return self._error(404, "ruta desconocida")
            if not self._autorizado():
                return self._error(401, "no autorizado")
            accion()

        def do_POST(self):
            if not self._ruta().startswith("/station/"):
                return self._error(404, "ruta desconocida")
            if not self._autorizado():
                return self._error(401, "no autorizado")
            self._estacion()

        def _status(self) -> None:
            self._responder(200, estado_publico(radio.estado()))

        def _estacion(self) -> None:
            largo = int(self.headers.get("Content-Length") or 0)
            if largo:
                self.rfile.read(min(largo, 65536))
            nombre = urllib.parse.unquote(self._ruta()[len("/station/"):])
            if nombre not in [e.nombre for e in radio.estaciones()]:
                return self._error(404, "esa emisora no existe")
            try:
                radio.sintonizar(nombre, oir_aca=False)
            except SinEstaciones:
                return self._error(409, "no hay estaciones")
            except Exception:
                _log.exception("error al sintonizar %r desde la red", nombre)
                return self._error(500, "error interno")
            self._responder(200, estado_publico(radio.estado()))

        def _icono(self) -> None:
            self._error(404, "esa emisora no tiene logo")

        def _stream(self) -> None:
            try:
                cola = difusor.suscribir()
            except (SinCapacidad, CodificadorNoDisponible) as e:
                return self._error(503, str(e))
            try:
                self.send_response(200)
                self.send_header("Content-Type", "audio/mpeg")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                while True:
                    try:
                        bloque = cola.get(timeout=30)
                    except queue.Empty:
                        continue
                    if bloque is None:
                        break
                    self.wfile.write(bloque)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass
            finally:
                difusor.desuscribir(cola)

    servidor = ThreadingHTTPServer((host, puerto), Manejador)
    servidor.daemon_threads = True
    return servidor

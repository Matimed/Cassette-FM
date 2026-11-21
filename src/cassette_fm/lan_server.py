"""El servidor de la radio por la red: el audio del bus, el estado y el cambio de emisora, y nada más.

Es un servidor aparte de la API de dueño (que sigue en loopback): expone solo `/status`, `/station/{id}`, `/stream` e
`/icon/{id}`, todas con la clave de oyente (`Authorization: Bearer <clave>`)."""
import hashlib
import hmac
import socket
import json
import logging
import queue
import urllib.parse
from collections.abc import Mapping
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from cassette_fm.lan_stream import CodificadorNoDisponible, SinCapacidad
from cassette_fm.radio import SinEstaciones

_log = logging.getLogger("cassette_fm")

_CAMPOS = ("encendida", "estacion", "pista", "estaciones", "fuente", "segundo", "oyentes")
TIPOS_IMAGEN = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp",
                 ".gif": "image/gif"}
_MAX_LOGO_BYTES = 4 * 1024 * 1024
_BUFFER_ENVIO_BYTES = 8192      # ~0,4 s de audio (el kernel lo duplica): con uno grande el atraso de un oyente se esconde ahí


def version_logo(ruta: Path) -> str | None:
    """Cambia cuando cambia el archivo (tamaño y fecha); None si no es una imagen servible."""
    try:
        if ruta.suffix.lower() not in TIPOS_IMAGEN or not ruta.is_file():
            return None
        info = ruta.stat()
    except OSError:
        return None
    if info.st_size > _MAX_LOGO_BYTES:
        return None
    return hashlib.sha1(f"{info.st_size}:{info.st_mtime_ns}".encode()).hexdigest()[:12]


def iconos_publicos(rutas: Mapping[str, str]) -> dict[str, str]:
    """{emisora: "/icon/<id>?v=<versión>"} solo de los logos que existen; nunca rutas de esta PC."""
    publicos = {}
    for nombre, ruta in rutas.items():
        version = version_logo(Path(ruta))
        if version:
            publicos[nombre] = f"/icon/{urllib.parse.quote(nombre, safe='')}?v={version}"
    return publicos


def estado_publico(estado: dict, iconos: dict[str, str] | None = None) -> dict:
    """Lo único del estado de la radio que ve un oyente (sin volumen ni nada de esta PC)."""
    publico = {campo: estado.get(campo) for campo in _CAMPOS}
    publico["estaciones"] = list(publico["estaciones"] or [])
    publico["iconos"] = dict(iconos or {})
    return publico


def crear_servidor_lan(radio, difusor, token, host: str, puerto: int) -> ThreadingHTTPServer:
    """`token`: la clave (texto) o una función que la devuelve (así `cassette lan regenerar` rige sin reiniciar)."""
    leer_token = token if callable(token) else (lambda: token)

    class Manejador(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.0"        # el stream termina al cerrar la conexión

        def setup(self):
            super().setup()
            self.request.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, _BUFFER_ENVIO_BYTES)

        def log_message(self, formato, *args):
            _log.debug("lan %s", formato % args)

        def _autorizado(self) -> bool:
            clave = leer_token()
            recibido = (self.headers.get("Authorization") or "").encode("utf-8", "replace")
            return bool(clave) and hmac.compare_digest(recibido, f"Bearer {clave}".encode())

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
            estado = radio.estado()
            self._responder(200, estado_publico(estado, iconos_publicos(estado.get("iconos") or {})))

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
            estado = radio.estado()
            self._responder(200, estado_publico(estado, iconos_publicos(estado.get("iconos") or {})))

        def _icono(self) -> None:
            # el logo sale del mapa que tiene la propia radio, por nombre: el cliente nunca elige una ruta
            nombre = urllib.parse.unquote(self._ruta()[len("/icon/"):])
            ruta = (radio.estado().get("iconos") or {}).get(nombre)
            version = version_logo(Path(ruta)) if ruta else None
            if version is None:
                return self._error(404, "esa emisora no tiene logo")
            ruta = Path(ruta)
            etag = f'"{version}"'
            if self.headers.get("If-None-Match") == etag:
                self.send_response(304)
                self.send_header("ETag", etag)
                self.send_header("Content-Length", "0")
                return self.end_headers()
            try:
                datos = ruta.read_bytes()
            except OSError:
                return self._error(404, "esa emisora no tiene logo")
            self.send_response(200)
            self.send_header("Content-Type", TIPOS_IMAGEN[ruta.suffix.lower()])
            self.send_header("Content-Length", str(len(datos)))
            self.send_header("ETag", etag)
            self.send_header("Cache-Control", "private, max-age=3600")
            self.end_headers()
            self.wfile.write(datos)

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

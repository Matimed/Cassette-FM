import json
import logging
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from cassette_fm.audio_router import AudioRouterError
from cassette_fm.config import ErrorConfig
from cassette_fm.mpv import ErrorMpv
from cassette_fm.radio import BusInactivo, DJInactivo, EstacionInexistente, RadioApagada, SinEstaciones

_log = logging.getLogger("cassette_fm")

ACCIONES = ("siguiente", "anterior", "encender", "apagar", "alternar", "silenciar", "rescan")


_MENSAJE_DJ_INACTIVO = ("El DJ está apagado: poné `activo = true` (y, para pedirle intervenciones al servicio DJ, la "
                        "`url` del servicio) en la sección [dj] de config.toml y reiniciá el servicio")


class _SolicitudInvalida(Exception):
    pass


def crear_servidor(radio, host: str = "127.0.0.1", puerto: int = 7710,
                   emisoras: Path | None = None,
                   extra_estado: Callable[[], dict] | None = None) -> ThreadingHTTPServer:
    """`extra_estado`: campos que se suman a `/estado` (p. ej. el puente a la nube)."""
    class Manejador(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _responder(self, codigo: int, datos) -> None:
            cuerpo = json.dumps(datos, ensure_ascii=False).encode("utf-8")
            self.send_response(codigo)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(cuerpo)))
            self.end_headers()
            self.wfile.write(cuerpo)

        def _error(self, codigo: int, mensaje: str) -> None:
            self._responder(codigo, {"error": mensaje})

        def _leer_json(self) -> dict:
            largo = int(self.headers.get("Content-Length") or 0)
            if largo == 0:
                return {}
            try:
                datos = json.loads(self.rfile.read(largo).decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                raise _SolicitudInvalida("el cuerpo no es JSON válido")
            if not isinstance(datos, dict):
                raise _SolicitudInvalida("el cuerpo tiene que ser un objeto JSON")
            return datos

        def do_GET(self):
            try:
                self._get()
            except Exception:
                _log.exception("error inesperado en GET %s", self.path)
                self._error(500, "error interno (mirá el log del servicio)")

        def _get(self):
            if self.path == "/estado":
                self._responder(200, radio.estado() | (extra_estado() if extra_estado is not None else {}))
            elif self.path == "/dj":
                self._responder(200, radio.dj_estado())
            elif self.path == "/dj/modo":
                try:
                    self._responder(200, radio.dj_modo())
                except DJInactivo:
                    self._error(409, _MENSAJE_DJ_INACTIVO)
                except ValueError as e:
                    self._error(400, str(e))
            elif self.path == "/estaciones":
                self._responder(200, [{"nombre": e.nombre, "pistas": len(e.pistas)}
                                      for e in radio.estaciones()])
            else:
                self._error(404, f"ruta desconocida: {self.path}")

        def do_POST(self):
            ruta = self.path.lstrip("/")
            if ruta not in ACCIONES + ("sintonizar", "volumen", "monitor", "dj/probar", "dj/pedir", "dj/modo"):
                self._error(404, f"ruta desconocida: {self.path}")
                return
            respuesta = None
            try:
                datos = self._leer_json()
                if ruta == "dj/probar":
                    respuesta = self._dj_probar(datos)
                elif ruta == "dj/pedir":
                    respuesta = self._dj_pedir(datos)
                elif ruta == "dj/modo":
                    respuesta = self._dj_modo(datos)
                elif ruta == "sintonizar":
                    if not isinstance(datos.get("estacion"), str):
                        raise _SolicitudInvalida("falta el campo 'estacion'")
                    radio.sintonizar(datos["estacion"])
                elif ruta == "monitor":
                    if not isinstance(datos.get("activo"), bool):
                        raise _SolicitudInvalida("falta 'activo' (true o false)")
                    radio.monitor(datos["activo"])
                elif ruta == "volumen":
                    valor, delta = datos.get("valor"), datos.get("delta")
                    if valor is None and delta is None:
                        raise _SolicitudInvalida("falta 'valor' o 'delta' (enteros)")
                    for campo in (valor, delta):
                        if campo is not None and (isinstance(campo, bool) or not isinstance(campo, int)):
                            raise _SolicitudInvalida("'valor' y 'delta' tienen que ser enteros")
                    radio.volumen(valor=datos.get("valor"), delta=datos.get("delta"))
                else:
                    getattr(radio, ruta)()
            except _SolicitudInvalida as e:
                self._error(400, str(e))
            except EstacionInexistente as e:
                self._error(404, str(e))
            except ErrorMpv as e:
                self._error(503, f"mpv: {e}")
            except DJInactivo:
                self._error(409, _MENSAJE_DJ_INACTIVO)
            except BusInactivo as e:
                self._error(409, str(e))
            except AudioRouterError as e:
                self._error(503, f"audio: {e}")
            except RadioApagada:
                self._error(409, "No hay una estación sintonizada: encendé la radio primero")
            except SinEstaciones:
                donde = f": revisá {emisoras}" if emisoras else ""
                self._error(409, f"No hay estaciones{donde}")
            except ErrorConfig as e:
                self._error(400, str(e))
            except Exception:
                _log.exception("error inesperado en POST %s", self.path)
                self._error(500, "error interno (mirá el log del servicio)")
            else:
                self._responder(200, respuesta if respuesta is not None else radio.estado())

        def _dj_modo(self, datos: dict) -> dict:
            modo = datos.get("modo")
            if modo not in ("plantillas", "llm", "apagado"):
                raise _SolicitudInvalida("'modo' tiene que ser \"plantillas\", \"llm\" o \"apagado\"")
            try:
                return radio.dj_modo(modo)
            except ValueError as e:
                raise _SolicitudInvalida(str(e))

        def _dj_pedir(self, datos: dict) -> dict:
            en = datos.get("en_segundos", 20.0)
            if isinstance(en, bool) or not isinstance(en, (int, float)) or en < 0:
                raise _SolicitudInvalida("'en_segundos' tiene que ser un número, 0 o más")
            try:
                return radio.dj_pedir(en_segundos=float(en))
            except ValueError as e:
                raise _SolicitudInvalida(str(e))

        def _dj_probar(self, datos: dict) -> dict:
            audio, en = datos.get("audio"), datos.get("en_segundos", 20.0)
            if audio is not None and not isinstance(audio, str):
                raise _SolicitudInvalida("'audio' tiene que ser una ruta (texto)")
            if isinstance(en, bool) or not isinstance(en, (int, float)):
                raise _SolicitudInvalida("'en_segundos' tiene que ser un número")
            try:
                return radio.dj_probar(audio=Path(audio) if audio else None, en_segundos=float(en))
            except ValueError as e:
                raise _SolicitudInvalida(str(e))

    servidor = ThreadingHTTPServer((host, puerto), Manejador)
    servidor.daemon_threads = True
    return servidor

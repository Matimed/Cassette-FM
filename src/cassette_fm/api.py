import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from cassette_fm.radio import EstacionInexistente, SinEstaciones

ACCIONES = ("siguiente", "anterior", "encender", "apagar", "alternar", "rescan")


class _SolicitudInvalida(Exception):
    pass


def crear_servidor(radio, host: str = "127.0.0.1", puerto: int = 7710,
                   raiz: Path | None = None) -> ThreadingHTTPServer:
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
            if self.path == "/estado":
                self._responder(200, radio.estado())
            elif self.path == "/estaciones":
                self._responder(200, [{"nombre": e.nombre, "pistas": len(e.pistas)}
                                      for e in radio.estaciones()])
            else:
                self._error(404, f"ruta desconocida: {self.path}")

        def do_POST(self):
            ruta = self.path.lstrip("/")
            if ruta not in ACCIONES + ("sintonizar", "volumen"):
                self._error(404, f"ruta desconocida: {self.path}")
                return
            try:
                datos = self._leer_json()
                if ruta == "sintonizar":
                    if not isinstance(datos.get("estacion"), str):
                        raise _SolicitudInvalida("falta el campo 'estacion'")
                    radio.sintonizar(datos["estacion"])
                elif ruta == "volumen":
                    if not isinstance(datos.get("valor"), int) and not isinstance(datos.get("delta"), int):
                        raise _SolicitudInvalida("falta 'valor' o 'delta' (enteros)")
                    radio.volumen(valor=datos.get("valor"), delta=datos.get("delta"))
                else:
                    getattr(radio, ruta)()
            except _SolicitudInvalida as e:
                self._error(400, str(e))
            except EstacionInexistente as e:
                self._error(404, str(e))
            except SinEstaciones:
                donde = f" en {raiz}" if raiz else ""
                self._error(409, f"No hay estaciones{donde}: cada subcarpeta con música es una estación")
            else:
                self._responder(200, radio.estado())

    servidor = ThreadingHTTPServer((host, puerto), Manejador)
    servidor.daemon_threads = True
    return servidor

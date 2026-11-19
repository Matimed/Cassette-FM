#!/usr/bin/env python3
"""Relay de prueba para el puente a la nube: el lado relay del protocolo, para probar en casa sin el relay real.

    .venv/bin/python scripts/relay-de-prueba.py [--host 127.0.0.1] [--puerto 9000]
                                                [--clave-archivo ~/.config/cassette-fm/nube.token]

Con `[nube] url = "ws://127.0.0.1:9000"` en config.toml, el puente de cassette-fm se conecta acá. Los oyentes (sin
clave: es solo para la red de casa) tienen:

    GET  /                          una página mínima para el navegador (emisoras, calidad y reproductor)
    GET  /escuchar?calidad=96       el MP3 en vivo (64, 96 o 160)
    GET  /estado                    el último estado que mandó la PC
    POST /sintonizar/<emisora>      también /siguiente y /anterior
    GET  /icono/<emisora>           el logo (se le pide a la PC la primera vez)

No es el relay de verdad: sin TLS, todo en memoria y sin endurecer. Sirve también de referencia ejecutable del
protocolo (docs/superpowers/specs/2026-11-19-puente-nube-design.md)."""
import argparse
import hmac
import html
import itertools
import json
import queue
import select
import socket
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from websockets.exceptions import ConnectionClosed
from websockets.sync.server import serve

CALIDADES = (64, 96, 160)
_COLA_OYENTE = 64          # pedazos de audio por oyente antes de descartarlo por lento


class Relay:
    def __init__(self, host: str, puerto: int, clave):
        self._clave = clave if callable(clave) else (lambda: clave)
        self._lock = threading.Lock()
        self._control = None
        self._envio = threading.Lock()
        self.estado: dict | None = None
        self._iconos: dict[str, tuple[str, str, bytes]] = {}      # emisora → (versión, tipo, datos)
        self._oyentes: dict[int, list[queue.Queue]] = {k: [] for k in CALIDADES}
        self._esperando: dict[str, queue.Queue] = {}               # id de orden → su resultado
        self._ids = itertools.count(1)
        self._socket = socket.create_server((host, puerto), reuse_port=False)
        self.puerto = self._socket.getsockname()[1]
        self._ws = serve(self._atender_ws, sock=socket.socket(), process_request=self._autorizar_ws, compression=None)
        relay = self

        class Manejador(_Http):
            pass
        Manejador.relay = relay
        self._http = ThreadingHTTPServer((host, 0), Manejador, bind_and_activate=False)
        self._parar = threading.Event()
        threading.Thread(target=self._aceptar, daemon=True, name="relay-aceptar").start()

    # --- conexiones entrantes: WebSocket de la PC o HTTP de los oyentes, en el mismo puerto ---

    def _aceptar(self) -> None:
        while not self._parar.is_set():
            try:
                sock, direccion = self._socket.accept()
            except OSError:
                return
            threading.Thread(target=self._despachar, args=(sock, direccion), daemon=True).start()

    def _despachar(self, sock, direccion) -> None:
        try:
            sock.settimeout(10)
            inicio = sock.recv(4096, socket.MSG_PEEK)
            sock.settimeout(None)
        except OSError:
            sock.close()
            return
        if b"upgrade: websocket" in inicio.lower():
            self._ws.handler(sock, direccion)
        else:
            try:
                self._http.finish_request(sock, direccion)
            except Exception:
                pass
            finally:
                self._http.shutdown_request(sock)

    def autorizado(self, encabezado: str | None) -> bool:
        clave = self._clave()
        return bool(clave) and hmac.compare_digest((encabezado or "").encode(), f"Bearer {clave}".encode())

    def _autorizar_ws(self, conexion, pedido):
        if not self.autorizado(pedido.headers.get("Authorization")):
            return conexion.respond(401, "clave incorrecta\n")
        return None

    def _atender_ws(self, ws) -> None:
        ruta = urllib.parse.urlsplit(ws.request.path)
        if ruta.path == "/casa/control":
            self._atender_control(ws)
        elif ruta.path == "/casa/audio":
            kbps = int((urllib.parse.parse_qs(ruta.query).get("calidad") or ["0"])[0] or 0)
            self._atender_audio(ws, kbps)
        else:
            ws.close(1008, "ruta desconocida")

    # --- control ---

    def _atender_control(self, ws) -> None:
        with self._lock:
            viejo, self._control = self._control, ws
        if viejo is not None:
            viejo.close()
        print("PC conectada")
        try:
            for crudo in ws:
                if isinstance(crudo, str):
                    self._mensaje(ws, json.loads(crudo))
        except ConnectionClosed:
            pass
        finally:
            with self._lock:
                if self._control is ws:
                    self._control = None
            print("PC desconectada")

    def _mensaje(self, ws, mensaje: dict) -> None:
        tipo = mensaje.get("tipo")
        if tipo == "hola":
            self._mandar_demanda()
        elif tipo == "estado":
            with self._lock:
                self.estado = mensaje
                faltan = [n for n, v in (mensaje.get("iconos") or {}).items()
                          if self._iconos.get(n, ("",))[0] != v]
            print(f"estado #{mensaje.get('seq')}: {mensaje.get('estacion')} — {mensaje.get('pista')}")
            for nombre in faltan:
                self._mandar({"tipo": "pedir_icono", "estacion": nombre})
        elif tipo == "resultado":
            espera = self._esperando.pop(str(mensaje.get("id")), None)
            if espera is not None:
                espera.put(mensaje)

    def _mandar(self, mensaje: dict) -> bool:
        with self._lock:
            ws = self._control
        if ws is None:
            return False
        try:
            with self._envio:
                ws.send(json.dumps(mensaje, ensure_ascii=False))
            return True
        except ConnectionClosed:
            return False

    def _mandar_demanda(self) -> None:
        with self._lock:
            calidades = [k for k, oyentes in self._oyentes.items() if oyentes]
        self._mandar({"tipo": "demanda", "calidades": calidades})

    def orden(self, tipo: str, **campos) -> dict:
        ident = str(next(self._ids))
        espera = self._esperando[ident] = queue.Queue()
        if not self._mandar({"tipo": tipo, "id": ident, **campos}):
            self._esperando.pop(ident, None)
            return {"ok": False, "error": "la PC no está conectada"}
        try:
            return espera.get(timeout=10)
        except queue.Empty:
            self._esperando.pop(ident, None)
            return {"ok": False, "error": "la PC no contestó"}

    # --- audio ---

    def _atender_audio(self, ws, kbps: int) -> None:
        print(f"audio de {kbps} kbps: abierto")
        try:
            for datos in ws:
                if isinstance(datos, bytes):
                    with self._lock:
                        oyentes = list(self._oyentes.get(kbps, []))
                    for cola in oyentes:
                        try:
                            cola.put_nowait(datos)
                        except queue.Full:
                            self.quitar_oyente(kbps, cola)
                            cola.put(None)
        except ConnectionClosed:
            pass
        print(f"audio de {kbps} kbps: cerrado")

    def agregar_oyente(self, kbps: int) -> queue.Queue:
        cola = queue.Queue(maxsize=_COLA_OYENTE)
        with self._lock:
            primero = not self._oyentes[kbps]
            self._oyentes[kbps].append(cola)
        if primero:
            self._mandar_demanda()
        return cola

    def quitar_oyente(self, kbps: int, cola: queue.Queue) -> None:
        with self._lock:
            if cola not in self._oyentes[kbps]:
                return
            self._oyentes[kbps].remove(cola)
            ultimo = not self._oyentes[kbps]
        if ultimo:
            self._mandar_demanda()

    # --- logos ---

    def guardar_icono(self, nombre: str, version: str, tipo: str, datos: bytes) -> None:
        with self._lock:
            self._iconos[nombre] = (version, tipo, datos)

    def icono(self, nombre: str):
        with self._lock:
            return self._iconos.get(nombre)

    def conectado(self) -> bool:
        with self._lock:
            return self._control is not None

    def cerrar(self) -> None:
        self._parar.set()
        self._socket.close()
        with self._lock:
            control = self._control
        if control is not None:
            control.close()


class _Http(BaseHTTPRequestHandler):
    relay: Relay
    protocol_version = "HTTP/1.0"

    def log_message(self, *args):
        pass

    def _json(self, codigo: int, cuerpo) -> None:
        datos = json.dumps(cuerpo, ensure_ascii=False).encode()
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(datos)))
        self.end_headers()
        self.wfile.write(datos)

    def _ruta(self):
        return urllib.parse.urlsplit(self.path)

    def do_GET(self):
        ruta = self._ruta()
        if ruta.path == "/":
            return self._pagina()
        if ruta.path == "/estado":
            return self._json(200, {"conectado": self.relay.conectado(), **(self.relay.estado or {})})
        if ruta.path == "/escuchar":
            return self._escuchar(urllib.parse.parse_qs(ruta.query))
        if ruta.path.startswith("/icono/"):
            logo = self.relay.icono(urllib.parse.unquote(ruta.path[len("/icono/"):]))
            if logo is None:
                return self._json(404, {"error": "sin logo"})
            self.send_response(200)
            self.send_header("Content-Type", logo[1])
            self.send_header("Content-Length", str(len(logo[2])))
            self.end_headers()
            return self.wfile.write(logo[2])
        self._json(404, {"error": "ruta desconocida"})

    def _escuchar(self, consulta) -> None:
        try:
            kbps = int((consulta.get("calidad") or ["96"])[0])
        except ValueError:
            kbps = 0
        if kbps not in CALIDADES:
            return self._json(400, {"error": f"calidad: una de {list(CALIDADES)}"})
        cola = self.relay.agregar_oyente(kbps)
        try:
            self.send_response(200)
            self.send_header("Content-Type", "audio/mpeg")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            sin_datos = 0.0
            while not self._se_fue():
                try:
                    datos = cola.get(timeout=0.5)
                except queue.Empty:
                    sin_datos += 0.5
                    if sin_datos >= 15:
                        return                  # la PC no manda nada: el reproductor reconecta
                    continue
                if datos is None:
                    return
                sin_datos = 0.0
                self.wfile.write(datos)
        except OSError:
            pass
        finally:
            self.relay.quitar_oyente(kbps, cola)

    def _se_fue(self) -> bool:
        """El oyente cerró la conexión (se lee un EOF): no hace falta esperar a que falle una escritura."""
        try:
            legible, _, _ = select.select([self.connection], [], [], 0)
            return bool(legible) and self.connection.recv(1, socket.MSG_PEEK) == b""
        except OSError:
            return True

    def do_POST(self):
        ruta = self._ruta().path
        if ruta.startswith("/sintonizar/"):
            resultado = self.relay.orden("sintonizar", estacion=urllib.parse.unquote(ruta[len("/sintonizar/"):]))
        elif ruta in ("/siguiente", "/anterior"):
            resultado = self.relay.orden(ruta[1:])
        else:
            return self._json(404, {"error": "ruta desconocida"})
        self._json(200 if resultado.get("ok") else 409, resultado)

    def do_PUT(self):
        ruta = self._ruta()
        if not ruta.path.startswith("/casa/icono/"):
            return self._json(404, {"error": "ruta desconocida"})
        if not self.relay.autorizado(self.headers.get("Authorization")):
            return self._json(401, {"error": "clave incorrecta"})
        largo = int(self.headers.get("Content-Length") or 0)
        if not 0 < largo <= 4 * 1024 * 1024:
            return self._json(413, {"error": "logo vacío o demasiado grande"})
        version = (urllib.parse.parse_qs(ruta.query).get("v") or [""])[0]
        self.relay.guardar_icono(urllib.parse.unquote(ruta.path[len("/casa/icono/"):]), version,
                                 self.headers.get("Content-Type") or "application/octet-stream", self.rfile.read(largo))
        self._json(200, {"ok": True})

    def _pagina(self) -> None:
        estado = self.relay.estado or {}
        botones = "".join(
            f'<button onclick="sintonizar({html.escape(json.dumps(n))})">'
            f'<img src="/icono/{urllib.parse.quote(n, safe="")}" onerror="this.remove()"><br>{html.escape(n)}</button>'
            for n in estado.get("estaciones") or [])
        pagina = f"""<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>cassette-fm (relay de prueba)</title>
<style>body{{font-family:sans-serif;margin:16px}}button{{margin:4px;padding:8px}}img{{width:64px;height:64px}}</style>
<h1>cassette-fm</h1><p id="ahora">{html.escape(str(estado.get('estacion')))} — {html.escape(str(estado.get('pista')))}</p>
<select id="calidad"><option>64</option><option selected>96</option><option>160</option></select>
<button onclick="escuchar()">▶ Escuchar</button> <audio id="audio" controls></audio>
<div>{botones}</div>
<script>
function escuchar(){{const a=document.getElementById('audio');a.src='/escuchar?calidad='+calidad.value+'&t='+Date.now();a.play();}}
async function sintonizar(n){{await fetch('/sintonizar/'+encodeURIComponent(n),{{method:'POST'}});
  if(!audio.paused) escuchar();}}
setInterval(async()=>{{const e=await (await fetch('/estado')).json();
  document.getElementById('ahora').textContent=(e.estacion||'')+' — '+(e.pista||'');}},3000);
</script>"""
        datos = pagina.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(datos)))
        self.end_headers()
        self.wfile.write(datos)


def main() -> int:
    a = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    a.add_argument("--host", default="127.0.0.1")
    a.add_argument("--puerto", type=int, default=9000)
    a.add_argument("--clave-archivo", type=Path, default=Path.home() / ".config/cassette-fm/nube.token")
    args = a.parse_args()
    relay = Relay(args.host, args.puerto, lambda: args.clave_archivo.read_text().strip())
    print(f"relay de prueba en http://{args.host}:{relay.puerto}/ (Ctrl+C para cortar)")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        relay.cerrar()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

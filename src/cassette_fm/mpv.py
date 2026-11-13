import itertools
import json
import logging
import queue
import socket as socket_mod
import subprocess
import threading
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

_log = logging.getLogger("cassette_fm")

TIMEOUT_RESPUESTA = 5.0
TIMEOUT_SOCKET = 5.0


class ErrorMpv(Exception):
    pass


class _Conexion:
    """Un socket con su hilo lector y su hilo despachador de eventos."""

    def __init__(self, sock: socket_mod.socket, al_evento: Callable[[], Callable | None],
                 al_perder: Callable[[], Callable | None] = lambda: None,
                 vigente: Callable[["_Conexion"], bool] = lambda c: True):
        self.sock = sock
        self.viva = True
        self.cerrada = False
        self._al_perder = al_perder
        self._vigente = vigente
        self.pendientes: dict[int, tuple[threading.Event, list]] = {}
        self.eventos: queue.Queue = queue.Queue()
        self._al_evento = al_evento
        self._lock_pendientes = threading.Lock()
        threading.Thread(target=self._leer, daemon=True, name="mpv-lector").start()
        threading.Thread(target=self._despachar, daemon=True, name="mpv-eventos").start()

    def registrar(self, request_id: int) -> tuple[threading.Event, list]:
        espera = (threading.Event(), [])
        with self._lock_pendientes:
            self.pendientes[request_id] = espera
        return espera

    def olvidar(self, request_id: int) -> None:
        with self._lock_pendientes:
            self.pendientes.pop(request_id, None)

    def _leer(self) -> None:
        try:
            archivo = self.sock.makefile("rb")
            for linea in archivo:
                try:
                    msg = json.loads(linea)
                except ValueError:
                    continue
                if "request_id" in msg:
                    with self._lock_pendientes:
                        espera = self.pendientes.get(msg["request_id"])
                    if espera:
                        espera[1].append(msg)
                        espera[0].set()
                elif "event" in msg:
                    self.eventos.put(msg)
        except OSError:
            pass
        finally:
            self.viva = False
            with self._lock_pendientes:
                esperas = list(self.pendientes.values())
            for evento, _ in esperas:
                evento.set()
            self.eventos.put(None)
            if not self.cerrada:
                callback = self._al_perder()
                if callback is not None:
                    try:
                        callback()
                    except Exception:
                        _log.exception("error al reaccionar a la caída de mpv")

    def _despachar(self) -> None:
        while True:
            msg = self.eventos.get()
            if msg is None:
                return
            if not self._vigente(self):
                continue  # evento de un mpv que ya fue reemplazado: sus ids no valen
            callback = self._al_evento()
            if callback is not None:
                try:
                    callback(msg)
                except Exception:
                    _log.exception("error en el manejador de eventos de mpv")

    def cerrar(self) -> None:
        self.cerrada = True
        self.viva = False
        try:
            self.sock.shutdown(socket_mod.SHUT_RDWR)
        except OSError:
            pass
        self.sock.close()


class ClienteMpv:
    al_evento: Callable[[dict], None] | None = None
    al_perder: Callable[[], None] | None = None   # mpv murió sin que lo cerráramos
    generacion: int = 0                           # sube cada vez que se (re)lanza mpv

    def __init__(self, socket: Path, extra_args: Sequence[str] = (), ejecutable: str = "mpv"):
        self._socket = Path(socket)
        self._extra_args = list(extra_args)
        self._ejecutable = ejecutable
        self._proceso: subprocess.Popen | None = None
        self._conexion: _Conexion | None = None
        self._ids = itertools.count(1)
        self._lock_envio = threading.Lock()
        self._lock_vida = threading.RLock()

    def iniciar(self) -> None:
        with self._lock_vida:
            self._terminar()
            self._socket.parent.mkdir(parents=True, exist_ok=True)
            self._socket.unlink(missing_ok=True)
            self._proceso = subprocess.Popen(
                [self._ejecutable, "--no-config", "--idle=yes", "--no-video", "--no-terminal",
                 f"--input-ipc-server={self._socket}", *self._extra_args],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            sock = self._conectar()
            conexion = _Conexion(sock, lambda: self.al_evento, lambda: self.al_perder,
                                 lambda c: c is self._conexion)
            self._conexion = conexion
            self.generacion += 1
            _log.info("mpv iniciado (pid %s)", self._proceso.pid)

    def _conectar(self) -> socket_mod.socket:
        fin = time.monotonic() + TIMEOUT_SOCKET
        while time.monotonic() < fin:
            if self._proceso.poll() is not None:
                raise ErrorMpv("mpv terminó al arrancar")
            if self._socket.exists():
                sock = socket_mod.socket(socket_mod.AF_UNIX)
                try:
                    sock.connect(str(self._socket))
                    return sock
                except OSError:
                    sock.close()
            time.sleep(0.02)
        raise ErrorMpv("mpv no abrió el socket IPC a tiempo")

    def _terminar(self) -> None:
        if self._conexion is not None:
            self._conexion.cerrar()
            self._conexion = None
        if self._proceso is not None:
            if self._proceso.poll() is None:
                self._proceso.terminate()
                try:
                    self._proceso.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self._proceso.kill()
                    self._proceso.wait()
            self._proceso = None

    def _vivo(self) -> bool:
        return (self._proceso is not None and self._proceso.poll() is None
                and self._conexion is not None and self._conexion.viva)

    def vivo(self) -> bool:
        return self._vivo()

    def asegurar(self) -> None:
        with self._lock_vida:
            if not self._vivo():
                self.iniciar()

    def comando(self, *args: Any, **nombrados: Any) -> Any:
        for intento in range(2):
            with self._lock_vida:
                if not self._vivo():
                    self.iniciar()
                conexion = self._conexion
            try:
                return self._enviar(conexion, args, nombrados)
            except _ConexionPerdida:
                if intento == 1:
                    raise ErrorMpv("se perdió la conexión con mpv")
        raise ErrorMpv("se perdió la conexión con mpv")

    def _enviar(self, conexion: _Conexion, args: tuple, nombrados: dict) -> Any:
        request_id = next(self._ids)
        comando = {"name": args[0], **nombrados} if nombrados else list(args)
        espera, respuesta = conexion.registrar(request_id)
        try:
            datos = json.dumps({"command": comando, "request_id": request_id}).encode() + b"\n"
            try:
                with self._lock_envio:
                    conexion.sock.sendall(datos)
            except OSError:
                raise _ConexionPerdida()
            if not espera.wait(TIMEOUT_RESPUESTA):
                raise ErrorMpv(f"mpv no respondió a {args[0]!r}")
            if not respuesta:
                raise _ConexionPerdida()
        finally:
            conexion.olvidar(request_id)
        msg = respuesta[0]
        if msg.get("error") != "success":
            raise ErrorMpv(f"{args[0]}: {msg.get('error')}")
        return msg.get("data")

    def cerrar(self) -> None:
        with self._lock_vida:
            self._terminar()


class _ConexionPerdida(Exception):
    pass

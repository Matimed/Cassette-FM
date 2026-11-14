"""Cliente del WebSocket local de Spotify Soloist: eventos (tema, posición, dispositivo) y comandos (volumen, pausa).

El WebSocket no tiene autenticación: solo se usa en 127.0.0.1."""
import json
import logging
import threading
from collections.abc import Callable

from websockets.exceptions import ConnectionClosed, WebSocketException
from websockets.sync.client import connect

from cassette_fm.spotify.api import ErrorSpotify

_log = logging.getLogger("cassette_fm")


class ClienteSoloist:
    def __init__(self, url: str, al_evento: Callable[[dict], None],
                 al_desconectar: Callable[[], None] | None = None, reintento_segundos: float = 2.0,
                 al_reconectar: Callable[[], None] | None = None):
        self._url = url
        self._al_evento = al_evento
        self._al_desconectar = al_desconectar
        self._al_reconectar = al_reconectar
        self._reintento = reintento_segundos
        self._ws = None
        self._lock = threading.Lock()
        self._cerrado = threading.Event()
        self._primera = threading.Event()        # la primera conexión ya se abrió
        self._ultimo_error: Exception | None = None
        self._hilo: threading.Thread | None = None

    @property
    def conectado(self) -> bool:
        return self._ws is not None

    def conectar(self, timeout: float) -> None:
        """Conecta ya (ErrorSpotify si Soloist no responde en `timeout`) y deja escuchando en un hilo."""
        self._arrancar_hilo()
        if not self._primera.wait(timeout) or self._ws is None:
            error = self._ultimo_error
            self.cerrar()
            raise ErrorSpotify(f"Soloist no responde en {self._url}: {error or 'sin respuesta'}")

    def iniciar(self) -> None:
        """Conecta en segundo plano, reintentando hasta que Soloist aparezca (no frena el arranque)."""
        self._arrancar_hilo()

    def comando(self, nombre: str, **campos) -> None:
        ws = self._ws
        if ws is None:
            raise ErrorSpotify(f"Soloist no está conectado ({self._url})")
        try:
            with self._lock:
                ws.send(json.dumps({"type": "command", "command": nombre, **campos}))
        except (ConnectionClosed, OSError) as e:
            raise ErrorSpotify(f"se perdió la conexión con Soloist ({e})") from None

    def cerrar(self) -> None:
        self._cerrado.set()
        ws = self._ws
        if ws is not None:
            try:
                ws.close()
            except Exception:
                pass
        if self._hilo is not None and self._hilo is not threading.current_thread():
            self._hilo.join(2)
        self._ws = None

    def _arrancar_hilo(self) -> None:
        if self._hilo is None or not self._hilo.is_alive():
            self._hilo = threading.Thread(target=self._escuchar, daemon=True, name="soloist-ws")
            self._hilo.start()

    def _escuchar(self) -> None:
        primera = True
        while not self._cerrado.is_set():
            try:
                with connect(self._url, open_timeout=max(self._reintento, 1.0), close_timeout=1) as ws:
                    self._ws = ws
                    self._primera.set()
                    if not primera:
                        with self._lock:
                            ws.send(json.dumps({"type": "command", "command": "get_state"}))
                        if self._al_reconectar is not None:
                            try:
                                self._al_reconectar()
                            except Exception:
                                _log.exception("error al avisar que volvió Soloist")
                    primera = False
                    for crudo in ws:
                        self._entregar(crudo)
            except (OSError, WebSocketException, TimeoutError) as e:
                self._ultimo_error = e
            conectado_antes, self._ws = self._ws is not None, None
            if self._cerrado.is_set():
                return
            if conectado_antes:
                _log.warning("se cortó la conexión con Soloist; reintento cada %g s", self._reintento)
                if self._al_desconectar is not None:
                    try:
                        self._al_desconectar()
                    except Exception:
                        _log.exception("error al avisar que se cortó Soloist")
            self._cerrado.wait(self._reintento)

    def _entregar(self, crudo) -> None:
        try:
            evento = json.loads(crudo)
        except ValueError:
            return
        if isinstance(evento, dict):
            try:
                self._al_evento(evento)
            except Exception:
                _log.exception("error al procesar un evento de Soloist")

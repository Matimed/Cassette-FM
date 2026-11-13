import logging
import threading
import time
from collections import deque
from collections.abc import Callable

from cassette_fm.agenda import secuencia
from cassette_fm.biblioteca import Estacion, Pista
from cassette_fm.mpv import ErrorMpv

_log = logging.getLogger("cassette_fm")


class Reproductor:
    """Alimenta a mpv con la secuencia de la agenda: pista actual + `cola` siguientes."""

    MAX_FALLOS = 10   # errores de carga seguidos antes de darse por vencido

    pista_actual: Pista | None = None
    al_cambiar_pista: Callable[[Pista, Estacion], None] | None = None
    al_fallar: Callable[[], None] | None = None   # no hay forma de seguir sonando

    def __init__(self, mpv, reloj: Callable[[], float] = time.time, cola: int = 2):
        self._mpv = mpv
        self._reloj = reloj
        self._cola = cola
        self._lock = threading.Lock()
        self._secuencia = None
        self._pistas: dict[int, Pista] = {}
        self._ids: deque[int] = deque()
        self._primero: int | None = None
        self._avisada = True
        self._estacion: Estacion | None = None
        self._volumen: int | None = None
        self._fallos = 0
        self._generacion = mpv.generacion
        self._mpv.al_evento = self.manejar_evento
        self._mpv.al_perder = self._al_perder_mpv

    def asegurar(self) -> None:
        """Si mpv se relanzó, reaplica el volumen y vuelve a sintonizar la estación."""
        with self._lock:
            self._asegurar()

    def sintonizar(self, estacion: Estacion) -> None:
        with self._lock:
            self._asegurar(restaurar_estacion=False)
            self._estacion = estacion
            self._sintonizar(estacion)

    def _sintonizar(self, estacion: Estacion) -> None:
        self._fallos = 0
        self._secuencia = secuencia(estacion, self._reloj())
        self._pistas = {}
        self._ids = deque()
        self.pista_actual = None
        pista, desde = next(self._secuencia)
        resp = self._mpv.comando("loadfile", url=str(pista.ruta), flags="replace",
                                 options={"start": f"{desde:.3f}"})
        self._primero = resp["playlist_entry_id"]
        self._registrar(self._primero, pista)
        for _ in range(self._cola):
            self._encolar()

    def detener(self) -> None:
        with self._lock:
            self._detener()

    def _detener(self) -> None:
        self._estacion = None
        self._secuencia = None
        self._pistas = {}
        self._ids = deque()
        self._primero = None
        self.pista_actual = None
        self._mpv.comando("stop")

    def posicion(self) -> float | None:
        """Segundo de la pista que suena; no relanza mpv si está caído."""
        if self.pista_actual is None or not self._mpv.vivo():
            return None
        try:
            return self._mpv.comando("get_property", "time-pos")
        except ErrorMpv:
            return None

    def volumen(self, valor: int) -> int:
        valor = max(0, min(100, int(valor)))
        with self._lock:
            self._asegurar()
            self._volumen = valor
            self._mpv.comando("set_property", "volume", valor)
        return valor

    def manejar_evento(self, evento: dict) -> None:
        avisar = None
        fallo = False
        with self._lock:
            tipo = evento.get("event")
            if tipo == "start-file":
                id_ = evento.get("playlist_entry_id")
                if id_ not in self._pistas:
                    return
                self.pista_actual = self._pistas[id_]
                self._avisada = False
                if self._primero is not None and id_ == self._primero:
                    self._primero = None
                else:
                    self._mpv.comando("playlist-remove", 0)
                    self._pistas.pop(self._ids.popleft(), None)
                    self._encolar()
            elif tipo == "file-loaded":
                self._fallos = 0
                if self.pista_actual and not self._avisada:
                    self._avisada = True
                    avisar = (self.pista_actual, self._estacion)
            elif tipo == "idle" and self._estacion is not None:
                # mpv se quedó sin playlist: si todos los temas encolados fallan, recorre la lista
                # más rápido de lo que la rotamos. Se confirma con mpv para no confundirlo con el
                # `idle` del arranque de un mpv recién relanzado.
                try:
                    ocioso = self._mpv.comando("get_property", "idle-active")
                except ErrorMpv:
                    ocioso = False
                if ocioso:
                    _log.error("mpv se quedó sin temas que reproducir en %r: se detiene",
                               self._estacion.nombre)
                    self._detener()
                    fallo = True
            elif (tipo == "end-file" and evento.get("reason") == "error"
                  and evento.get("playlist_entry_id") in self._pistas):
                self._fallos += 1
                if self._fallos >= self.MAX_FALLOS:
                    _log.error("%d errores de carga seguidos en %r: se detiene la reproducción",
                               self._fallos, self._estacion.nombre if self._estacion else None)
                    self._detener()
                    fallo = True
        if avisar is not None and self.al_cambiar_pista is not None:
            self.al_cambiar_pista(*avisar)
        if fallo and self.al_fallar is not None:
            self.al_fallar()

    def _asegurar(self, restaurar_estacion: bool = True) -> None:
        self._mpv.asegurar()
        if self._mpv.generacion == self._generacion:
            return
        self._generacion = self._mpv.generacion
        if self._volumen is not None:
            self._mpv.comando("set_property", "volume", self._volumen)
        if restaurar_estacion and self._estacion is not None:
            self._sintonizar(self._estacion)

    def _al_perder_mpv(self) -> None:
        threading.Thread(target=self.asegurar, daemon=True, name="mpv-restaurar").start()

    def _registrar(self, id_: int, pista: Pista) -> None:
        self._pistas[id_] = pista
        self._ids.append(id_)

    def _encolar(self) -> None:
        pista, _ = next(self._secuencia)
        resp = self._mpv.comando("loadfile", url=str(pista.ruta), flags="append")
        self._registrar(resp["playlist_entry_id"], pista)

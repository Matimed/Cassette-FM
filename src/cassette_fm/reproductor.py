import threading
import time
from collections import deque
from collections.abc import Callable

from cassette_fm.agenda import secuencia
from cassette_fm.biblioteca import Estacion, Pista


class Reproductor:
    """Alimenta a mpv con la secuencia de la agenda: pista actual + `cola` siguientes."""

    pista_actual: Pista | None = None
    al_cambiar_pista: Callable[[Pista], None] | None = None

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
        self._mpv.al_evento = self.manejar_evento

    def sintonizar(self, estacion: Estacion) -> None:
        with self._lock:
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
            self._secuencia = None
            self._pistas = {}
            self._ids = deque()
            self._primero = None
            self.pista_actual = None
            self._mpv.comando("stop")

    def volumen(self, valor: int) -> int:
        valor = max(0, min(100, int(valor)))
        self._mpv.comando("set_property", "volume", valor)
        return valor

    def manejar_evento(self, evento: dict) -> None:
        avisar = None
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
            elif tipo == "file-loaded" and self.pista_actual and not self._avisada:
                self._avisada = True
                avisar = self.pista_actual
        if avisar is not None and self.al_cambiar_pista is not None:
            self.al_cambiar_pista(avisar)

    def _registrar(self, id_: int, pista: Pista) -> None:
        self._pistas[id_] = pista
        self._ids.append(id_)

    def _encolar(self) -> None:
        pista, _ = next(self._secuencia)
        resp = self._mpv.comando("loadfile", url=str(pista.ruta), flags="append")
        self._registrar(resp["playlist_entry_id"], pista)

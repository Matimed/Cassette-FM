"""El audio del bus por la red: un solo codificador MP3 (GStreamer) repartido a todos los oyentes.

Arranca con el primer oyente y se detiene unos segundos después del último, así que sin nadie escuchando no gasta CPU.
La fuente es el monitor del bus mientras la radio está prendida y ruido de estática cuando está apagada."""
import logging
import queue
import subprocess
import threading
import time
from collections.abc import Callable

_log = logging.getLogger("cassette_fm")

FUENTE_MONITOR = "monitor"
FUENTE_ESTATICA = "estatica"
_BLOQUE = 4096


class SinCapacidad(Exception):
    """Ya hay el máximo de oyentes."""


class CodificadorNoDisponible(Exception):
    """No se pudo arrancar el codificador (falta GStreamer o no arranca)."""


def comando_gst(fuente: str, dispositivo: str = "radio_virtual.monitor", kbps: int = 160) -> list[str]:
    origen = (["audiotestsrc", "wave=white-noise", "volume=0.05", "is-live=true"] if fuente == FUENTE_ESTATICA
              else ["pulsesrc", f"device={dispositivo}"])
    return ["gst-launch-1.0", "-q", *origen, "!", "audioconvert", "!", "audioresample", "!",
            "audio/x-raw,rate=44100,channels=2", "!", "lamemp3enc", "target=bitrate", "cbr=true",
            f"bitrate={kbps}", "!", "fdsink", "fd=1"]


def lanzar_gst(comando: list[str]) -> subprocess.Popen:
    try:
        return subprocess.Popen(comando, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL)
    except OSError as e:
        raise CodificadorNoDisponible(f"no se pudo lanzar {comando[0]} (paquete gstreamer1.0-tools): {e}")


def _cerrar_cola(cola: queue.Queue) -> None:
    """Le avisa a un oyente que terminó (None), aunque tenga la cola llena."""
    while True:
        try:
            cola.get_nowait()
        except queue.Empty:
            break
    cola.put_nowait(None)


class Difusor:
    def __init__(self, fuente_actual: Callable[[], str], lanzar: Callable[[list[str]], subprocess.Popen] = lanzar_gst,
                 max_oyentes: int = 4, gracia_segundos: float = 5.0, cola_max: int = 64,
                 estabilidad_segundos: float = 2.0, reloj: Callable[[], float] = time.monotonic):
        self._fuente_actual = fuente_actual
        self._lanzar = lanzar
        self._max = max_oyentes
        self._gracia = gracia_segundos
        self._cola_max = cola_max
        self._estabilidad = estabilidad_segundos
        self._reloj = reloj
        self._lock = threading.RLock()
        self._oyentes: list[queue.Queue] = []
        self._proceso = None
        self._fuente_en_uso: str | None = None
        self._sin_oyentes_desde: float | None = None
        self._candidata: str | None = None
        self._candidata_desde = 0.0

    # --- oyentes ---

    def suscribir(self) -> queue.Queue:
        with self._lock:
            if len(self._oyentes) >= self._max:
                raise SinCapacidad(f"ya hay {self._max} oyentes")
            if self._proceso is None:
                self._arrancar()
            cola = queue.Queue(maxsize=self._cola_max)
            self._oyentes.append(cola)
            self._sin_oyentes_desde = None
            return cola

    def desuscribir(self, cola: queue.Queue) -> None:
        with self._lock:
            if cola in self._oyentes:
                self._oyentes.remove(cola)
            if not self._oyentes:
                self._sin_oyentes_desde = self._reloj()

    def cortar_oyentes(self) -> None:
        """Se recreó el bus: los oyentes se cortan (el reproductor reconecta) y el codificador se apaga."""
        with self._lock:
            self._cortar()
            self._detener()

    def cerrar(self) -> None:
        self.cortar_oyentes()

    # --- codificador ---

    def revisar_fuente(self) -> None:
        """Lo llama el servicio cada segundo: apaga el codificador sin oyentes y lo reinicia si la fuente cambió y se
        mantuvo `estabilidad_segundos` (así una radio que oscila entre prendida y apagada no lo reinicia sin parar)."""
        with self._lock:
            if self._proceso is None:
                return
            ahora = self._reloj()
            if not self._oyentes:
                if self._sin_oyentes_desde is not None and ahora - self._sin_oyentes_desde >= self._gracia:
                    self._detener()
                return
            fuente = self._fuente_actual()
            if fuente == self._fuente_en_uso:
                self._candidata = None
            elif fuente != self._candidata:
                self._candidata, self._candidata_desde = fuente, ahora
            elif ahora - self._candidata_desde >= self._estabilidad:
                _log.info("el stream de la LAN pasa a %s", fuente)
                self._detener()
                self._arrancar()

    def _arrancar(self) -> None:
        fuente = self._fuente_actual()
        proceso = self._lanzar(comando_gst(fuente))
        self._proceso, self._fuente_en_uso, self._candidata = proceso, fuente, None
        threading.Thread(target=self._leer, args=(proceso,), daemon=True, name="lan-codificador").start()

    def _detener(self) -> None:
        proceso, self._proceso, self._fuente_en_uso = self._proceso, None, None
        if proceso is None:
            return
        try:
            proceso.terminate()
            try:
                proceso.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proceso.kill()
        except OSError:
            pass

    def _cortar(self) -> None:
        for cola in self._oyentes:
            _cerrar_cola(cola)
        self._oyentes = []
        self._sin_oyentes_desde = self._reloj()

    def _leer(self, proceso) -> None:
        leer = getattr(proceso.stdout, "read1", proceso.stdout.read)
        while True:
            try:
                datos = leer(_BLOQUE)
            except (OSError, ValueError):
                datos = b""
            if not datos:
                break
            self._repartir(proceso, datos)
        with self._lock:
            if self._proceso is proceso:        # murió solo (no lo paramos nosotros): se corta a los oyentes
                _log.warning("el codificador del stream de la LAN terminó")
                self._cortar()
                self._proceso = self._fuente_en_uso = None

    def _repartir(self, proceso, datos: bytes) -> None:
        with self._lock:
            if self._proceso is not proceso:
                return
            for cola in list(self._oyentes):
                try:
                    cola.put_nowait(datos)
                except queue.Full:                # no consume: se lo descarta sin frenar a los demás
                    self._oyentes.remove(cola)
                    _cerrar_cola(cola)
            if not self._oyentes and self._sin_oyentes_desde is None:
                self._sin_oyentes_desde = self._reloj()

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
# A 160 kbps un bloque son ~0,2 s, así que la cola por oyente (25 bloques) tolera ~5 s de bache sin cortar el audio. Un
# oyente que se atrasa no recupera ese atraso solo (el reproductor consume a tiempo real): lo recupera el cliente
# reconectándose al cambiar de emisora (`lan_receiver.py resync`); uno trabado por más de ~5 s se descarta.


class SinCapacidad(Exception):
    """Ya hay el máximo de oyentes."""


class CodificadorNoDisponible(Exception):
    """No se pudo arrancar el codificador (falta GStreamer o no arranca)."""


# La calidad de ahorro de datos (32 kbps) va en mono a 22,05 kHz: con estéreo de 44,1 kHz, LAME tiene que bajar el muestreo a
# 16 kHz para entrar en el bitrate y suena mucho peor; en mono a 22,05 kHz conserva el del formato (MPEG-2 capa III).
AHORRO_KBPS = 32


def comando_gst(fuente: str, dispositivo: str = "radio_virtual.monitor", kbps: int = 160) -> list[str]:
    formato = ("audio/x-raw,rate=22050,channels=1" if kbps <= AHORRO_KBPS else "audio/x-raw,rate=44100,channels=2")
    origen = (["audiotestsrc", "wave=white-noise", "volume=0.05", "is-live=true"] if fuente == FUENTE_ESTATICA
              else ["pulsesrc", f"device={dispositivo}"])
    return ["gst-launch-1.0", "-q", *origen, "!", "audioconvert", "!", "audioresample", "!",
            formato, "!", "lamemp3enc", "target=bitrate", "cbr=true",
            f"bitrate={kbps}", "!", "fdsink", "fd=1"]


def lanzar_gst(comando: list[str]) -> subprocess.Popen:
    try:
        return subprocess.Popen(comando, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE)
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
                 max_oyentes: int = 4, gracia_segundos: float = 5.0, cola_max: int = 25,
                 estabilidad_segundos: float = 2.0, reloj: Callable[[], float] = time.monotonic,
                 arranque_segundos: float = 1.0, kbps: int = 160,
                 al_conectarse: Callable[[], None] | None = None):
        self.kbps = kbps
        self._al_conectarse = al_conectarse     # aviso de cada conexión nueva (despierta a la radio)
        self._fuente_actual = fuente_actual
        self._lanzar = lanzar
        self._max = max_oyentes
        self._gracia = gracia_segundos
        self._cola_max = cola_max
        self._estabilidad = estabilidad_segundos
        self._reloj = reloj
        self._arranque = arranque_segundos
        self._listo = threading.Event()               # el codificador dio su primer dato o murió
        self._fallo: tuple | None = None             # (proceso, motivo) si murió antes de dar nada
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
                self._esperar_arranque()
            cola = queue.Queue(maxsize=self._cola_max)
            self._oyentes.append(cola)
            self._sin_oyentes_desde = None
        self._avisar_conexion()          # fuera del lock: la radio toma el suyo y consulta el conteo
        return cola

    def _avisar_conexion(self) -> None:
        if self._al_conectarse is None:
            return
        try:
            self._al_conectarse()
        except Exception:
            _log.exception("error al avisar una conexión nueva al stream")

    def cantidad_oyentes(self) -> int:
        with self._lock:
            return len(self._oyentes)

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
        proceso = self._lanzar(comando_gst(fuente, kbps=self.kbps))
        self._proceso, self._fuente_en_uso, self._candidata = proceso, fuente, None
        self._listo, self._fallo = threading.Event(), None
        threading.Thread(target=self._leer, args=(proceso, self._listo), daemon=True, name="lan-codificador").start()

    def _esperar_arranque(self) -> None:
        """Un codificador que muere al arrancar (no hay bus, falta un plugin) se avisa con su motivo en vez de
        entregar un stream vacío; uno lento pero vivo no es un error."""
        if self._arranque > 0:
            self._listo.wait(self._arranque)
        if self._fallo is not None and self._fallo[0] is self._proceso:
            motivo = self._fallo[1]
            self._detener()
            raise CodificadorNoDisponible(motivo)

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

    @staticmethod
    def _motivo_de_muerte(proceso) -> str:
        try:
            texto = proceso.stderr.read(2000).decode("utf-8", "replace")
            lineas = [l.strip() for l in texto.splitlines() if l.strip()]
            if lineas:
                return f"el codificador terminó al arrancar: {lineas[-1][:200]}"
        except (AttributeError, OSError, ValueError):
            pass
        return "el codificador terminó al arrancar (¿está el bus radio_virtual?)"

    def _leer(self, proceso, listo: threading.Event) -> None:
        leer = getattr(proceso.stdout, "read1", proceso.stdout.read)
        con_datos = False
        while True:
            try:
                datos = leer(_BLOQUE)
            except (OSError, ValueError):
                datos = b""
            if not datos:
                break
            if not con_datos:
                con_datos = True
                listo.set()
            self._repartir(proceso, datos)
        if not con_datos:
            self._fallo = (proceso, self._motivo_de_muerte(proceso))
            listo.set()
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


_COLA_A_160 = 25    # bloques por oyente a 160 kbps (~5 s); a otras calidades, los que duren lo mismo


class Difusores:
    """Un `Difusor` por calidad, creado la primera vez que se lo pide: la LAN y la nube comparten el mismo
    codificador cuando piden la misma calidad."""

    def __init__(self, fuente_actual: Callable[[], str], crear: Callable[..., Difusor] = Difusor, **opciones):
        self._fuente_actual = fuente_actual
        self._crear = crear
        self._opciones = opciones
        self._lock = threading.Lock()
        self._difusores: dict[int, Difusor] = {}

    def de(self, kbps: int) -> Difusor:
        with self._lock:
            if kbps not in self._difusores:
                self._difusores[kbps] = self._crear(
                    self._fuente_actual, kbps=kbps, cola_max=max(2, round(_COLA_A_160 * kbps / 160)), **self._opciones)
            return self._difusores[kbps]

    def _todos(self) -> list[Difusor]:
        with self._lock:
            return list(self._difusores.values())

    def total_oyentes(self) -> int:
        return sum(difusor.cantidad_oyentes() for difusor in self._todos())

    def revisar_fuente(self) -> None:
        for difusor in self._todos():
            difusor.revisar_fuente()

    def cortar_oyentes(self) -> None:
        for difusor in self._todos():
            difusor.cortar_oyentes()

    def cerrar(self) -> None:
        for difusor in self._todos():
            difusor.cerrar()

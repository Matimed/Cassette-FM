"""El vigilante de oyentes: duerme la radio cuando nadie la escucha.

Cada segundo mira cuántos oyentes tiene la radio (`Radio.oyentes`). Con cero durante `segundos_hasta_dormir` la duerme
(`Radio.dormir`); si alguien elige emisora en ese lapso la cuenta se reinicia, para que quien lo hizo desde la red tenga tiempo
de abrir su stream. Lo que despierta a la radio no es cosa de este módulo: es abrir el stream o elegir una emisora."""
import logging
import threading
import time
from collections.abc import Callable

_log = logging.getLogger("cassette_fm")


class Vigilante:
    def __init__(self, radio, gracia_segundos: float, reloj: Callable[[], float] = time.time):
        self._radio = radio
        self._gracia = gracia_segundos
        self._reloj = reloj
        self._sin_oyentes_desde: float | None = None
        self._parar = threading.Event()
        self._hilo: threading.Thread | None = None

    def revisar(self) -> None:
        if not self._radio.encendida or self._radio.oyentes() > 0:
            self._sin_oyentes_desde = None
            return
        ahora = self._reloj()
        if self._sin_oyentes_desde is None:
            self._sin_oyentes_desde = ahora
        desde = max(self._sin_oyentes_desde, self._radio.ultima_sintonia)
        if ahora - desde >= self._gracia:
            self._sin_oyentes_desde = None
            self._radio.dormir()

    def iniciar(self, intervalo: float = 1.0) -> None:
        def bucle():
            while not self._parar.wait(intervalo):
                try:
                    self.revisar()
                except Exception:
                    _log.exception("error en el vigilante de oyentes")

        self._hilo = threading.Thread(target=bucle, daemon=True, name="vigilante-oyentes")
        self._hilo.start()

    def cerrar(self) -> None:
        self._parar.set()
        if self._hilo is not None:
            self._hilo.join(timeout=2)

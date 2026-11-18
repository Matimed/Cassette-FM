"""Bus de audio virtual de la radio.

Todo lo que suena (música y voz del DJ) se manda a un sink virtual, `radio_virtual`. Desde ahí:

- la escucha local es un `module-loopback` de `radio_virtual.monitor` a la salida predeterminada, que se prende y
  se apaga sin tocar el bus y tiene su propio volumen (el del stream del loopback);
- una retransmisión por red puede leer el mismo `radio_virtual.monitor` y recibe siempre la señal completa.

Se maneja con `pactl`, así que anda igual sobre PulseAudio y sobre PipeWire (pipewire-pulse).
"""
import json
import logging
import os
import subprocess
import threading
import time
from collections.abc import Callable, Mapping

_log = logging.getLogger("cassette_fm")

SINK = "radio_virtual"
_LATENCIA_MS = 20


class AudioRouterError(Exception):
    pass


def _pactl(*args: str) -> str:
    try:
        salida = subprocess.run(["pactl", *args], capture_output=True, text=True, timeout=5)
    except FileNotFoundError:
        raise AudioRouterError("no se encontró `pactl` (paquete pulseaudio-utils)")
    except subprocess.TimeoutExpired:
        raise AudioRouterError(f"pactl {args[0]} no respondió")
    if salida.returncode != 0:
        raise AudioRouterError(salida.stderr.strip() or f"pactl {args[0]} falló ({salida.returncode})")
    return salida.stdout


class AudioRouter:
    def __init__(self, pactl: Callable[..., str] = _pactl, sink: str = SINK, latencia_ms: int = _LATENCIA_MS,
                 reintentos_sink_input: int = 20, espera_sink_input: float = 0.05):
        self._pactl = pactl
        self._sink = sink
        self._latencia_ms = latencia_ms
        self._reintentos = reintentos_sink_input
        self._espera = espera_sink_input
        self._lock = threading.RLock()
        self._modulo_bus: int | None = None
        self._modulo_loopback: int | None = None
        self._activo = False                # el loopback está cargado Y se oye (no silenciado)
        self._volumen_local = 100

    @property
    def sink(self) -> str:
        return self._sink

    @property
    def local_monitor_enabled(self) -> bool:
        return self._modulo_loopback is not None and self._activo

    @property
    def local_volume(self) -> int:
        return self._volumen_local

    def __enter__(self) -> "AudioRouter":
        self.create_bus()
        return self

    def __exit__(self, *_) -> None:
        self.close()

    # --- bus ---------------------------------------------------------------------------------------------------

    def create_bus(self) -> None:
        """Carga el null-sink. Si quedó uno de una corrida anterior que murió sin limpiar, lo adopta."""
        with self._lock:
            if self._modulo_bus is not None:
                return
            existente = self._buscar_modulo("module-null-sink", f"sink_name={self._sink}")
            if existente is not None:
                _log.warning("el bus %s ya existía (módulo %d): se reutiliza", self._sink, existente)
                self._modulo_bus = existente
                return
            self._modulo_bus = self._cargar("module-null-sink", f"sink_name={self._sink}",
                                            "sink_properties=device.description=Radio")
            _log.info("bus de audio %s creado (módulo %d)", self._sink, self._modulo_bus)

    def env(self, base: Mapping[str, str] | None = None) -> dict[str, str]:
        """El entorno para los procesos de audio de la app (`subprocess.Popen(..., env=router.env())`).

        Ojo: solo lo respetan los clientes de PulseAudio. mpv, en PipeWire, usa por defecto `--ao=pipewire`, que lo
        ignora: hay que pasarle `--ao=pulse`."""
        env = dict(os.environ if base is None else base)
        env["PULSE_SINK"] = self._sink
        return env

    def close(self) -> None:
        """Descarga el loopback y después el bus. Es idempotente y no levanta si algo ya no estaba."""
        with self._lock:
            self._descargar_loopback()
            if self._modulo_bus is not None:
                self._descargar(self._modulo_bus)
                self._modulo_bus = None

    # --- monitor local -----------------------------------------------------------------------------------------

    def enable_local_monitor(self) -> None:
        """Pasa lo que suena en el bus a la salida predeterminada, con el último volumen local elegido.

        El loopback se carga una sola vez y queda cargado: cada carga de un `module-loopback` mete un chasquido a escala
        completa a los ~30 ms (medido: ~1 de cada 5 cargas, con música o sin ella), que se oía como un golpe en los
        parlantes al desmutear. Silenciar/activar es solo el mute de su stream."""
        with self._lock:
            self.create_bus()
            if self._salida_predeterminada() == self._sink:
                raise AudioRouterError(f"la salida predeterminada es {self._sink}: el monitor local "
                                       "generaría una realimentación; elegí los parlantes como salida")
            fuente = f"source={self._sink}.monitor"
            if self._modulo_loopback is not None and self._buscar_modulo("module-loopback", fuente) != self._modulo_loopback:
                self._modulo_loopback = None            # lo descargaron por afuera (p. ej. se reinició PipeWire)
            if self._modulo_loopback is None:
                self._modulo_loopback = (self._buscar_modulo("module-loopback", fuente)
                                         or self._cargar("module-loopback", fuente, f"latency_msec={self._latencia_ms}"))
            try:
                # un stream nuevo nace al volumen que le dé PipeWire (a veces 100 %): se lo silencia antes de fijarle
                # el volumen elegido, y recién entonces suena
                indice = self._sink_input_del_loopback()
                self._pactl("set-sink-input-mute", str(indice), "1")
                self._pactl("set-sink-input-volume", str(indice), f"{self._volumen_local}%")
                self._pactl("set-sink-input-mute", str(indice), "0")
            except AudioRouterError:
                self._descargar_loopback()              # mejor sin monitor que a un volumen que no se eligió
                raise
            self._activo = True

    def disable_local_monitor(self) -> None:
        """Silencia el monitor (mute del stream del loopback); no lo descarga, ver `enable_local_monitor`."""
        with self._lock:
            self._activo = False
            if self._modulo_loopback is None:
                return
            try:
                self._pactl("set-sink-input-mute", str(self._sink_input_del_loopback()), "1")
            except AudioRouterError as e:
                _log.warning("no se pudo silenciar el monitor local, se descarga: %s", e)
                self._descargar_loopback()

    def set_local_volume(self, percent: int) -> None:
        """Volumen de lo que sale por los parlantes (0 = mudo). El nivel dentro del bus no cambia.

        Se recuerda aunque el monitor esté apagado y se aplica al prenderlo."""
        if isinstance(percent, bool) or not isinstance(percent, int) or not 0 <= percent <= 100:
            raise ValueError("el volumen local tiene que ser un entero de 0 a 100")
        with self._lock:
            self._volumen_local = percent
            if self._modulo_loopback is not None:
                self._aplicar_volumen()

    # --- internos ----------------------------------------------------------------------------------------------

    def _aplicar_volumen(self) -> None:
        indice = self._sink_input_del_loopback()
        self._pactl("set-sink-input-volume", str(indice), f"{self._volumen_local}%")

    def _sink_input_del_loopback(self) -> int:
        """El stream de reproducción que creó nuestro loopback (`owner_module`); aparece un instante después de cargarlo."""
        for intento in range(self._reintentos):
            for si in json.loads(self._pactl("--format=json", "list", "sink-inputs")):
                if str(si.get("owner_module")) == str(self._modulo_loopback):   # PipeWire lo da como texto
                    return si["index"]
            if intento + 1 < self._reintentos:
                time.sleep(self._espera)
        raise AudioRouterError(f"no apareció el sink-input del loopback (módulo {self._modulo_loopback})")

    def _salida_predeterminada(self) -> str:
        return self._pactl("get-default-sink").strip()

    def _cargar(self, modulo: str, *argumentos: str) -> int:
        salida = self._pactl("load-module", modulo, *argumentos).strip()
        if not salida.isdigit():
            raise AudioRouterError(f"pactl load-module {modulo} devolvió {salida!r}")
        return int(salida)

    def _buscar_modulo(self, modulo: str, argumento: str) -> int | None:
        for linea in self._pactl("list", "short", "modules").splitlines():
            partes = linea.split("\t")
            if len(partes) >= 3 and partes[1] == modulo and argumento in partes[2].split():
                return int(partes[0])
        return None

    def _descargar(self, id_: int) -> None:
        try:
            self._pactl("unload-module", str(id_))
        except AudioRouterError as e:
            _log.warning("no se pudo descargar el módulo %d: %s", id_, e)

    def _descargar_loopback(self) -> None:
        self._activo = False
        if self._modulo_loopback is not None:
            self._descargar(self._modulo_loopback)
            self._modulo_loopback = None

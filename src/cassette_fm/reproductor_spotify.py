"""Reproductor de las emisoras de Spotify: la agenda de la radio sonando en Spotify Soloist.

Misma interfaz que el `Reproductor` de mpv. La orden de reproducir (lista `uris` + posición) va por la Web API, en
segundo plano: mientras tanto la radio pone la estática y la saca con `al_sonar`. Los eventos del WebSocket de Soloist
(`manejar_evento`) dicen qué suena; los de una sintonía vieja se ignoran."""
import logging
import threading
import time
from collections.abc import Callable
from itertools import islice

from cassette_fm.agenda import secuencia
from cassette_fm.biblioteca import Estacion, Pista
from cassette_fm.spotify.api import ErrorSpotify

_log = logging.getLogger("cassette_fm")


def _temporizar(segundos: float, funcion: Callable[[], None]) -> threading.Timer:
    t = threading.Timer(segundos, funcion)
    t.daemon = True
    t.start()
    return t


def _en_hilo(funcion: Callable[[], None]) -> None:
    threading.Thread(target=funcion, daemon=True, name="spotify-sintonia").start()


class ReproductorSpotify:
    PASO_RAMPA = 0.05

    pista_actual: Pista | None = None
    al_cambiar_pista: Callable[[Pista, Estacion], None] | None = None
    al_fallar: Callable[..., None] | None = None      # (estacion, motivo)
    al_sonar: Callable[[], None] | None = None        # empezó a sonar lo pedido: la radio saca la estática

    def __init__(self, control, soloist, reloj: Callable[[], float] = time.time, uris_por_pedido: int = 100,
                 espera_sonido_segundos: float = 10.0, temporizador=_temporizar,
                 en_segundo_plano: Callable[[Callable[[], None]], None] = _en_hilo):
        self._control = control
        self._soloist = soloist
        self._reloj = reloj
        self._uris_por_pedido = uris_por_pedido
        self._espera = espera_sonido_segundos
        self._temporizador = temporizador
        self._en_segundo_plano = en_segundo_plano
        self._lock = threading.RLock()
        self._sintonia = 0
        self._estacion: Estacion | None = None
        self._por_clave: dict[str, Pista] = {}
        self._esperado: str | None = None        # uri del primer tema de la sintonía en curso
        self._visto_esperado = False
        self._esperando_sonido = False
        self._espera_timer = None
        self._posicion: tuple[float, float, float] | None = None   # (position_ms, timestamp_ms, speed)
        self._volumen: int | None = None
        self._factor = 1.0

    # --- sintonía ---

    def sintonizar(self, estacion: Estacion) -> None:
        with self._lock:
            self._sintonia += 1
            n = self._sintonia
            self._estacion = estacion
            self._por_clave = {p.clave: p for p in estacion.pistas}
            self.pista_actual = None
            self._posicion = None
            lista = list(islice(secuencia(estacion, self._reloj()), self._uris_por_pedido))
            uris = [p.uri for p, _ in lista]
            posicion_ms = int(lista[0][1] * 1000)
            self._esperado, self._visto_esperado, self._esperando_sonido = uris[0], False, True
            self._cancelar_espera()
            self._espera_timer = self._temporizador(self._espera, lambda: self._no_sono(n))
        self._en_segundo_plano(lambda: self._reproducir(n, estacion, uris, posicion_ms))

    def _reproducir(self, n: int, estacion: Estacion, uris: list[str], posicion_ms: int) -> None:
        if not self._soloist.conectado:
            self._fallar(n, estacion, "Soloist no responde: ¿está corriendo? "
                                      "(systemctl --user status cassette-soloist)")
            return
        try:
            self._aplicar_volumen()
            self._control.reproducir(uris, posicion_ms)
        except ErrorSpotify as e:
            self._fallar(n, estacion, str(e))

    def _no_sono(self, n: int) -> None:
        with self._lock:
            if n != self._sintonia or not self._esperando_sonido:
                return
            estacion = self._estacion
        self._fallar(n, estacion, f"Spotify no empezó a sonar en {self._espera:g} s")

    def _fallar(self, n: int, estacion: Estacion | None, motivo: str) -> None:
        with self._lock:
            if n != self._sintonia or estacion is None:
                return
            self._cancelar_espera()
            self._esperando_sonido = False
        _log.warning("la emisora %r no puede sonar: %s", estacion.nombre, motivo)
        if self.al_fallar is not None:
            self.al_fallar(estacion, motivo)

    def _cancelar_espera(self) -> None:
        if self._espera_timer is not None:
            self._espera_timer.cancel()
            self._espera_timer = None

    def detener(self) -> None:
        with self._lock:
            self._sintonia += 1
            self._estacion = None
            self.pista_actual = None
            self._posicion = None
            self._esperando_sonido = False
            self._cancelar_espera()
        try:
            self._soloist.comando("pause")
        except ErrorSpotify:
            pass

    def asegurar(self) -> None:
        """El WebSocket se reconecta solo: no hay nada que relanzar."""

    # --- eventos de Soloist ---

    def manejar_evento(self, evento: dict) -> None:
        tipo = evento.get("type")
        avisar = sonar = None
        with self._lock:
            estacion = self._estacion
            if estacion is None:
                return
            if tipo == "track_changed":
                pista = self._pista_del_item(evento.get("item"))
                if pista is None:
                    return
                if pista.clave == self._esperado:
                    self._visto_esperado = True
                self.pista_actual = pista
                self._posicion = None
                avisar = (pista, estacion)
            elif tipo in ("playback_changed", "playback_state"):
                item = evento.get("item")
                if isinstance(item, dict) and item.get("uri") == self._esperado:
                    self._visto_esperado = True
                if evento.get("status") == "playing" and self._esperando_sonido and self._visto_esperado:
                    self._esperando_sonido = False
                    self._cancelar_espera()
                    sonar = True
            elif tipo == "position_sync":
                p = evento.get("position") or {}
                try:
                    self._posicion = (float(p["position_ms"]), float(p["timestamp_ms"]), float(p.get("speed", 1)))
                except (KeyError, TypeError, ValueError):
                    pass
        if sonar and self.al_sonar is not None:
            self.al_sonar()
        if avisar is not None and self.al_cambiar_pista is not None:
            self.al_cambiar_pista(*avisar)

    def _pista_del_item(self, item) -> Pista | None:
        if not isinstance(item, dict) or not isinstance(item.get("uri"), str):
            return None
        uri = item["uri"]
        if uri in self._por_clave:
            return self._por_clave[uri]
        deco = item.get("decorations") or {}
        nombre = (deco.get("identity") or {}).get("name") or uri
        ms = (deco.get("playback") or {}).get("duration_ms") or 0
        return Pista(ruta=None, duracion=float(ms) / 1000, titulo=nombre, fuente="spotify", cancion=nombre, uri=uri)

    def soloist_desconectado(self) -> None:
        """El WebSocket se cortó: si en la espera no vuelve, la emisora falla (no queda colgada en silencio)."""
        with self._lock:
            if self._estacion is None:
                return
            n, estacion = self._sintonia, self._estacion

        def revisar():
            if not self._soloist.conectado:
                self._fallar(n, estacion, "se perdió la conexión con Soloist")
        self._temporizador(self._espera, revisar)

    def posicion(self) -> float | None:
        with self._lock:
            if self.pista_actual is None or self._posicion is None:
                return None
            ms, ts, speed = self._posicion
            return (ms + (self._reloj() * 1000 - ts) * speed) / 1000

    # --- volumen (se completa en la tarea 5) ---

    def volumen(self, valor: int) -> int:
        valor = max(0, min(100, int(valor)))
        with self._lock:
            self._volumen = valor
        self._aplicar_volumen()
        return valor

    def atenuar(self, factor: float, segundos: float = 0.0) -> None:
        with self._lock:
            self._factor = factor
        self._aplicar_volumen()

    def _aplicar_volumen(self) -> None:
        if self._volumen is None or not self._soloist.conectado:
            return
        try:
            self._soloist.comando("set_volume", volume=round(self._volumen * self._factor))
        except ErrorSpotify:
            pass

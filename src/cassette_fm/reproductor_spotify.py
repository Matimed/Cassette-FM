"""Reproductor de las emisoras de Spotify: la agenda de la radio sonando en Spotify Soloist.

Misma interfaz que el `Reproductor` de mpv. La orden de reproducir (lista `uris` + posición) va por la Web API, en
segundo plano: mientras tanto la radio pone la estática y la saca con `al_sonar`. Los eventos del WebSocket de Soloist
(`manejar_evento`) dicen qué suena; los de una sintonía vieja se ignoran."""
import json
import logging
import subprocess
import threading
import time
from collections.abc import Callable
from itertools import islice

from cassette_fm.agenda import desfase, secuencia
from cassette_fm.biblioteca import Estacion, Pista
from cassette_fm.spotify.api import ErrorSpotify

_log = logging.getLogger("cassette_fm")


def _temporizar(segundos: float, funcion: Callable[[], None]) -> threading.Timer:
    t = threading.Timer(segundos, funcion)
    t.daemon = True
    t.start()
    return t


def _subir_stream_pactl(porcentaje: int) -> None:
    """Volumen del stream "Spotify" de PipeWire (por encima de 100 % cuando Soloist al 100 no alcanza)."""
    try:
        streams = json.loads(subprocess.run(["pactl", "-f", "json", "list", "sink-inputs"], capture_output=True,
                                            text=True, timeout=3).stdout or "[]")
        for st in streams:
            if (st.get("properties") or {}).get("application.name") == "Spotify":
                subprocess.run(["pactl", "set-sink-input-volume", str(st["index"]), f"{porcentaje}%"], timeout=3)
    except (OSError, ValueError, subprocess.SubprocessError, KeyError, TypeError) as e:
        _log.warning("no se pudo ajustar el volumen del stream de Spotify en PipeWire: %s", e)


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
                 en_segundo_plano: Callable[[Callable[[], None]], None] = _en_hilo, ajuste_volumen_db: float = 0.0,
                 tolerancia_resync_segundos: float = 3.0,
                 subir_stream: Callable[[int], None] = _subir_stream_pactl):
        self._control = control
        self._soloist = soloist
        self._reloj = reloj
        self._uris_por_pedido = uris_por_pedido
        self._espera = espera_sonido_segundos
        self._temporizador = temporizador
        self._en_segundo_plano = en_segundo_plano
        self._lock = threading.RLock()
        self._orden_lock = threading.Lock()       # una orden a Spotify por vez, en el orden en que se pidieron
        self._perdido = False                     # otro dispositivo tomó Spotify: no mandarle comandos
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
        self._rampa = 0                                    # una rampa nueva invalida a la anterior
        self._ganancia = 10 ** (ajuste_volumen_db / 60)    # la curva de Soloist es ~cúbica, como la de mpv
        self._stream = 100                                 # % del stream "Spotify" en PipeWire
        self._subir_stream = subir_stream
        self._tolerancia = tolerancia_resync_segundos
        self._activo = False          # Soloist tomó el control en esta sintonía (para notar si lo pierde)
        self._enviados = 0            # cuántos temas tiene la lista que se le mandó a Spotify
        self._vistos = 0              # cuántos de esos ya empezaron
        self._primero_pendiente = False

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
            self._activo, self._enviados, self._vistos, self._primero_pendiente = False, len(uris), 0, True
            self._perdido = False
            self._cancelar_espera()
            self._espera_timer = self._temporizador(self._espera, lambda: self._no_sono(n))
        self._en_segundo_plano(lambda: self._reproducir(n, estacion, uris, posicion_ms))

    def _reproducir(self, n: int, estacion: Estacion, uris: list[str], posicion_ms: int) -> None:
        with self._orden_lock:
            if n != self._sintonia:
                return                            # ya se pidió otra cosa: esta orden no sale
            if not self._soloist.conectado:
                self._fallar(n, estacion, "Soloist no responde: ¿está corriendo o venció su build? "
                                          "(systemctl --user status cassette-soloist · cassette spotify estado)")
                return
            try:
                self._aplicar_volumen()
                self._control.reproducir(uris, posicion_ms)
            except ErrorSpotify as e:
                self._fallar(n, estacion, str(e))
                return
            with self._lock:
                vieja, sin_emisora = n != self._sintonia, self._estacion is None
            if vieja and sin_emisora and not self._perdido:
                # mientras viajaba el play se detuvo la emisora: la pausa de `detener` llegó antes que el play
                try:
                    self._soloist.comando("pause")
                except ErrorSpotify:
                    pass

    def _resintonizar(self) -> None:
        """Vuelve a mandar la agenda desde ahora, en un borde de tema (sin estática ni `al_sonar`): corrige el
        desfase o renueva la lista antes de que Spotify se quede sin temas."""
        with self._lock:
            estacion, n = self._estacion, self._sintonia
            if estacion is None:
                return
            lista = list(islice(secuencia(estacion, self._reloj()), self._uris_por_pedido))
            uris = [p.uri for p, _ in lista]
            self._esperado, self._enviados, self._vistos, self._primero_pendiente = uris[0], len(uris), 0, True
        self._en_segundo_plano(lambda: self._reproducir(n, estacion, uris, int(lista[0][1] * 1000)))

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
            perdido = self._perdido
        if perdido:
            return                # Soloist ya no es el dispositivo activo: una pausa iría al celular
        try:
            self._soloist.comando("pause")
        except ErrorSpotify:
            pass

    def asegurar(self) -> None:
        """El WebSocket se reconecta solo: no hay nada que relanzar."""

    # --- eventos de Soloist ---

    def manejar_evento(self, evento: dict) -> None:
        tipo = evento.get("type")
        avisar = sonar = perdido = None
        resintonizar = False
        with self._lock:
            estacion = self._estacion
            if estacion is None:
                return
            if tipo == "track_changed":
                pista = self._pista_del_item(evento.get("item"))
                if pista is None:
                    return
                if self._esperando_sonido and not self._visto_esperado and pista.clave != self._esperado:
                    return        # lo que sonaba antes en la cuenta o un evento de la sintonía anterior
                if pista.clave == self._esperado:
                    self._visto_esperado = True
                repetido = (self._primero_pendiente and self.pista_actual is not None
                            and pista.clave == self.pista_actual.clave)   # la re-sintonía vuelve a empezarlo
                self.pista_actual = pista
                self._posicion = None
                if not repetido:
                    avisar = (pista, estacion)
                resintonizar = self._hay_que_resintonizar(pista, estacion)
            elif tipo in ("playback_changed", "playback_state"):
                item = evento.get("item")
                if isinstance(item, dict) and item.get("uri") == self._esperado:
                    self._visto_esperado = True
                if evento.get("status") == "playing" and self._esperando_sonido and self._visto_esperado:
                    self._esperando_sonido = False
                    self._cancelar_espera()
                    sonar = True
            elif tipo == "device_changed":
                if evento.get("is_active"):
                    self._activo = True
                elif self._activo:
                    self._activo = False
                    self._perdido = True
                    perdido = (self._sintonia, estacion)
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
        if resintonizar:
            self._resintonizar()
        if perdido is not None:
            self._fallar(*perdido, "Spotify se está escuchando en otro dispositivo")

    def _hay_que_resintonizar(self, pista: Pista, estacion: Estacion) -> bool:
        """Un tema de la agenda empezó: ¿se corrió del reloj o se está acabando la lista enviada?
        Un tema ajeno (encolado por el usuario) se deja sonar."""
        if pista.clave not in self._por_clave:
            return False
        self._vistos += 1
        if self._primero_pendiente:            # el primero de la lista: se pidió con la posición justa
            self._primero_pendiente = False
            return False
        valor = desfase(estacion, pista, self._reloj())
        if valor is None or abs(valor) > self._tolerancia:
            _log.info("Spotify se corrió del reloj en %r (%s s): se vuelve a sintonizar", estacion.nombre,
                      "?" if valor is None else f"{valor:.1f}")
            return True
        return self._enviados - self._vistos < 10

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

    def soloist_reconectado(self) -> None:
        """Volvió el WebSocket (p. ej. systemd reinició Soloist): el Soloist nuevo no está sonando nada, así que se
        vuelve a mandar la agenda desde ahora."""
        with self._lock:
            if self._estacion is None or self._perdido:
                return
        self._resintonizar()

    def posicion(self) -> float | None:
        with self._lock:
            if self.pista_actual is None or self._posicion is None:
                return None
            ms, ts, speed = self._posicion
            return (ms + (self._reloj() * 1000 - ts) * speed) / 1000

    # --- volumen ---

    def volumen(self, valor: int) -> int:
        valor = max(0, min(100, int(valor)))
        with self._lock:
            self._volumen = valor
        self._aplicar_volumen()
        return valor

    def atenuar(self, factor: float, segundos: float = 0.0) -> None:
        """Lleva el volumen efectivo a `volumen * factor` con una rampa lineal de `segundos` (como el de mpv);
        una rampa nueva reemplaza a la que esté en curso, partiendo del valor actual."""
        with self._lock:
            self._rampa += 1
            token, inicio = self._rampa, self._factor
            if segundos <= 0 or inicio == factor:
                self._factor = factor
        if segundos <= 0 or inicio == factor:
            self._aplicar_volumen()
            return
        threading.Thread(target=self._correr_rampa, args=(token, inicio, factor, segundos), daemon=True,
                         name="spotify-rampa").start()

    def _correr_rampa(self, token: int, inicio: float, fin: float, segundos: float) -> None:
        t0 = time.monotonic()
        while True:
            avance = (time.monotonic() - t0) / segundos
            ultimo = avance >= 1
            with self._lock:
                if token != self._rampa:
                    return
                self._factor = fin if ultimo else inicio + (fin - inicio) * avance
            self._aplicar_volumen()
            if ultimo:
                return
            time.sleep(self.PASO_RAMPA)

    def _aplicar_volumen(self) -> None:
        """Se manda bajo el lock (como en mpv): así el último valor calculado es el último que llega. Sin emisora
        de Spotify sintonizada no se manda nada (Soloist podría reenviarlo al dispositivo activo)."""
        with self._lock:
            if self._volumen is None or self._estacion is None or self._perdido or not self._soloist.conectado:
                return
            objetivo = self._volumen * self._factor * self._ganancia
            try:
                self._soloist.comando("set_volume", volume=min(100, round(objetivo)))
            except ErrorSpotify:
                return
            stream = min(150, round(objetivo)) if objetivo > 100 else 100
            if stream != self._stream:
                self._stream = stream
                self._subir_stream(stream)

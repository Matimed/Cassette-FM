"""Reproductor de las emisoras de Spotify: la agenda de la radio sonando en Spotify Soloist.

Misma interfaz que el `Reproductor` de mpv. La orden de reproducir (lista `uris` + posición) va por la Web API, en
segundo plano: mientras tanto la radio pone la estática y la saca con `al_sonar`. Los eventos del WebSocket de Soloist
(`manejar_evento`) dicen qué suena; los de una sintonía vieja se ignoran.

Peticiones: lo que el usuario encola desde la app de Spotify (`queue_changed` con `source == "queue"`) es un pedido
cuando empieza a sonar; la agenda de la emisora se corre (`con_pedido`, `plegar`) en vez de re-sintonizar."""
import json
import logging
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import replace
from itertools import islice

from cassette_fm.agenda import con_pedido, desfase, plegar, secuencia, transiciones
from cassette_fm.biblioteca import Estacion, Pedido, Pista
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


def _nombre(decoraciones) -> str | None:
    identidad = decoraciones.get("identity") if isinstance(decoraciones, dict) else None
    nombre = identidad.get("name") if isinstance(identidad, dict) else None
    return nombre if isinstance(nombre, str) and nombre else None


def _nombre_de_entidad(x) -> str | None:
    """El nombre de `{"entity": {"decorations": ...}}` (artista o álbum de un ítem de Soloist)."""
    entidad = x.get("entity") if isinstance(x, dict) else None
    return _nombre(entidad.get("decorations")) if isinstance(entidad, dict) else None


class ReproductorSpotify:
    PASO_RAMPA = 0.05
    AVISO_REPETIDO_SEGUNDOS = 5.0     # Soloist a veces avisa dos veces el mismo comienzo, con milisegundos de diferencia
    SALTEO_SEGUNDOS = 2.0             # otro tema antes de esto: Soloist no pudo cargar el anterior (o lo saltearon)
    CORREGIR_SEGUNDOS = 1.0           # la Web API tardó más que esto: su play atrasó el tema local lo que se oye

    pista_actual: Pista | None = None
    al_cambiar_pista: Callable[[Pista, Estacion], None] | None = None
    al_fallar: Callable[..., None] | None = None      # (estacion, motivo)
    al_sonar: Callable[[], None] | None = None        # empezó a sonar lo pedido: la radio saca la estática
    al_cambiar_agenda: Callable[[Estacion, Pedido | None], None] | None = None   # empezó un pedido o terminaron
    al_encolado: Callable[[Pista, Estacion, float], None] | None = None          # (pista, emisora, fin del actual)
    al_desencolado: Callable[[str], None] | None = None   # sacaron de la cola el encolado avisado (su clave)

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
        self._cambio_en = float("-inf")           # cuándo llegó el último track_changed que se tomó
        self._encolados: dict[str, Pista] = {}   # la cola de la app según el último queue_changed, por URI
        self._anunciado: str | None = None        # el encolado próximo que ya se avisó con al_encolado
        self._por_anunciar: Pista | None = None   # el próximo encolado, esperando la posición para avisarlo
        # el play local de la sintonía espera su track_changed para saltar a la posición: (sintonía, uri, posición)
        self._seek_pendiente: tuple[int, str, Callable[[], int]] | None = None

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
            posicion_ms = self._posicion_al_play(*lista[0])
            self._esperado, self._visto_esperado, self._esperando_sonido = uris[0], False, True
            self._activo, self._enviados, self._vistos, self._primero_pendiente = False, len(uris), 0, True
            self._perdido = False
            self._cancelar_espera()
            self._espera_timer = self._temporizador(self._espera, lambda: self._no_sono(n))
        self._en_segundo_plano(lambda: self._reproducir(n, estacion, uris, posicion_ms, local=True))

    def _posicion_al_play(self, pista: Pista, segundo: float) -> Callable[[], int]:
        """La posición del primer tema cuando salga el play: `segundo` es la de ahora, y lo que tarden las órdenes
        previas (volumen, shuffle, repeat) corre también; sin pasar el final del tema."""
        calculada = self._reloj()

        def posicion() -> int:
            s = segundo + max(0.0, self._reloj() - calculada)
            return int(max(0.0, min(s, pista.duracion - 1.0)) * 1000)
        return posicion

    def _reproducir(self, n: int, estacion: Estacion, uris: list[str], posicion_ms: Callable[[], int],
                    local: bool = False) -> None:
        """La orden a Spotify. Con `local` (una sintonía: alguien espera que suene), el primer tema sale antes por
        Soloist (~0,3 s) y la lista completa por la Web API, que hay noches que tarda segundos."""
        with self._orden_lock:
            if n != self._sintonia:
                return                            # ya se pidió otra cosa: esta orden no sale
            if not self._soloist.conectado:
                self._fallar(n, estacion, "Soloist no responde: ¿está corriendo o venció su build? "
                                          "(systemctl --user status cassette-soloist · cassette spotify estado)")
                return
            try:
                self._aplicar_volumen()
                # si la cuenta tiene shuffle o repeat, Spotify los aplica a la lista y suena otro tema; por Soloist
                # se apagan en milisegundos (por la Web API eran ~1,2 s en cada sintonía)
                for orden in ("set_shuffle", "set_repeat_context", "set_repeat_track"):
                    self._soloist.comando(orden, enabled=False)
                if local:
                    self._tocar_local(n, uris[0], posicion_ms)
                inicio = self._reloj()
                self._control.reproducir(uris, posicion_ms)
            except ErrorSpotify as e:
                self._fallar(n, estacion, str(e))
                return
            if local:
                self._corregir_posicion(n, uris[0], posicion_ms, self._reloj() - inicio)
            with self._lock:
                vieja, sin_emisora = n != self._sintonia, self._estacion is None
            if vieja and sin_emisora and not self._perdido:
                # mientras viajaba el play se detuvo la emisora: la pausa de `detener` llegó antes que el play
                try:
                    self._soloist.comando("pause")
                except ErrorSpotify:
                    pass

    def _tocar_local(self, n: int, uri: str, posicion_ms: Callable[[], int]) -> None:
        """El primer tema por Soloist: el WebSocket solo acepta un tema y sin posición, así que la posición sale con
        un seek cuando llega su track_changed (antes, Soloist lo ignora). Si falla, queda la Web API sola."""
        with self._lock:
            self._seek_pendiente = (n, uri, posicion_ms)
        try:
            self._soloist.comando("play", uri=uri)
        except ErrorSpotify as e:
            _log.info("Soloist no tomó el play local (%s): la sintonía sigue por la Web API", e)
            with self._lock:
                self._seek_pendiente = None

    def _corregir_posicion(self, n: int, uri: str, posicion_ms: Callable[[], int], demora: float) -> None:
        """La Web API volvió: si tardó, su play recargó el tema (que ya sonaba) en la posición de cuando se mandó;
        un seek local lo devuelve a la de ahora."""
        with self._lock:
            vigente = n == self._sintonia and (self.pista_actual is None or self.pista_actual.clave == uri)
            if not vigente or demora <= self.CORREGIR_SEGUNDOS:
                return
            self._seek_pendiente = None
        try:
            self._soloist.comando("seek", position_ms=posicion_ms())
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
        posicion_ms = self._posicion_al_play(*lista[0])
        self._en_segundo_plano(lambda: self._reproducir(n, estacion, uris, posicion_ms))

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
        if tipo == "error":          # p. ej. no reconoce una orden (set_shuffle…): sin esto el fallo sería mudo
            _log.warning("Soloist rechazó una orden: %s", evento.get("message") or "sin detalle")
            return
        avisar = sonar = perdido = agenda = encolado = desencolado = None
        resintonizar = False
        with self._lock:
            estacion = self._estacion
            if tipo == "queue_changed":       # la cola se sigue aunque no suene Spotify: puede sonar al volver
                encolado, desencolado = self._leer_cola(evento.get("upcoming"), estacion)
            elif estacion is None:
                return
            elif tipo == "track_changed":
                pista = self._pista_del_item(evento.get("item"))
                if pista is None:
                    return
                if (pista.clave not in self._por_clave and pista.clave not in self._encolados
                        and not (self.pista_actual is not None and pista.clave == self.pista_actual.clave)
                        and all(p.pista.clave != pista.clave for p in estacion.pedidos)):
                    pista = self._version_del_esperado(pista, estacion) or pista
                if self._esperando_sonido and not self._visto_esperado and pista.clave != self._esperado:
                    return        # lo que sonaba antes en la cuenta o un evento de la sintonía anterior
                if pista.clave == self._esperado:
                    self._visto_esperado = True
                pendiente = self._seek_pendiente
                if pendiente is not None and pendiente[0] == self._sintonia and pendiente[1] == pista.clave:
                    self._seek_pendiente = None
                    try:
                        self._soloist.comando("seek", position_ms=pendiente[2]())   # el tema local ya cargó
                    except ErrorSpotify:
                        pass
                if (not self._primero_pendiente and self.pista_actual is not None
                        and pista.clave == self.pista_actual.clave
                        and self._reloj() - self._cambio_en < self.AVISO_REPETIDO_SEGUNDOS):
                    return        # el mismo comienzo avisado otra vez: plegaría el pedido recién empezado
                rapido = (self.pista_actual is not None and pista.clave != self.pista_actual.clave
                          and self._reloj() - self._cambio_en < self.SALTEO_SEGUNDOS)
                self._cambio_en = self._reloj()
                saltada = None
                repetido =(self._primero_pendiente and self.pista_actual is not None
                            and pista.clave == self.pista_actual.clave)   # la re-sintonía vuelve a empezarlo
                # la (re)sintonía empezó por un pedido en curso: se retoma, no es un pedido nuevo ni un desfase
                retomado = (self._primero_pendiente and pista.clave == self._esperado
                            and any(p.pista.clave == pista.clave for p in estacion.pedidos))
                pedida = None if retomado else self._encolados.pop(pista.clave, None)
                if pedida is not None:
                    pista, ahora = pedida, self._reloj()
                    estacion = con_pedido(estacion, pedida, ahora)
                    agenda = (estacion, Pedido(pedida, ahora))
                    self._anunciado = self._por_anunciar = None
                elif not retomado and estacion.pedidos and pista.clave in self._por_clave:
                    estacion = plegar(estacion, self._reloj())    # antes de medir el desfase
                    agenda = (estacion, None)
                elif (rapido and not retomado and not self._primero_pendiente and pista.clave in self._por_clave
                      and self.pista_actual.clave in self._por_clave):
                    # Soloist saltó el tema que sonaba al instante (no pudo cargarlo): volver a pedirlo sería un bucle;
                    # la agenda se corre para que lo que suena empiece ahora
                    saltada = self._saltear_hasta(estacion, pista, self._reloj())
                    if saltada is not None:
                        _log.info("Soloist salteó %r en %r: la agenda sigue desde %r", self.pista_actual.titulo,
                                  estacion.nombre, pista.titulo)
                        estacion = saltada
                        agenda = (estacion, None)
                self._estacion = estacion
                self.pista_actual = pista
                self._posicion = None
                if not repetido:
                    avisar = (pista, estacion)
                if retomado:
                    self._primero_pendiente = False
                    self._vistos += 1
                elif saltada is not None:
                    self._vistos += 1
                elif pedida is None:
                    resintonizar = self._hay_que_resintonizar(pista, estacion)
            elif tipo in ("playback_changed", "playback_state"):
                item = evento.get("item")
                if isinstance(item, dict) and item.get("uri") == self._esperado:
                    self._visto_esperado = True
                elif (isinstance(item, dict) and self._primero_pendiente and not self._visto_esperado
                      and item.get("uri") not in self._por_clave):
                    # otra versión del tema que ya sonaba (se reinició la radio): no llega track_changed
                    otra = self._pista_del_item(item)
                    version = self._version_del_esperado(otra, estacion) if otra is not None else None
                    self._visto_esperado = version is not None and version.clave == self._esperado
                if evento.get("status") == "playing" and self._esperando_sonido and self._visto_esperado:
                    self._esperando_sonido = False
                    self._cancelar_espera()
                    sonar = True
                    if self.pista_actual is None:
                        # Spotify ya estaba en ese tema (se reinició la radio): salta a la posición sin track_changed
                        pista = self._por_clave.get(self._esperado) or next(
                            (p.pista for p in estacion.pedidos if p.pista.clave == self._esperado), None)
                        if pista is not None:
                            self.pista_actual = pista
                            self._primero_pendiente = False
                            self._vistos += 1
                            self._cambio_en = self._reloj()
                            avisar = (pista, estacion)
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
                if self._por_anunciar is not None:    # Soloist manda la cola antes que la posición del tema
                    encolado = self._aviso_de_encolado(self._por_anunciar, estacion)
        if sonar and self.al_sonar is not None:
            self.al_sonar()
        if agenda is not None and self.al_cambiar_agenda is not None:
            self.al_cambiar_agenda(*agenda)       # antes que el cambio de tema: la radio mide con la agenda nueva
        if avisar is not None and self.al_cambiar_pista is not None:
            self.al_cambiar_pista(*avisar)
        if desencolado is not None and self.al_desencolado is not None:
            self.al_desencolado(desencolado)
        if encolado is not None and self.al_encolado is not None:
            self.al_encolado(*encolado)
        if resintonizar:
            self._resintonizar()
        if perdido is not None:
            self._fallar(*perdido, "Spotify se está escuchando en otro dispositivo")

    def _saltear_hasta(self, estacion: Estacion, pista: Pista, ahora: float) -> Estacion | None:
        """La emisora con el corrimiento que hace empezar `pista` ahora (si está entre las próximas de la agenda)."""
        if estacion.pedidos:
            return None
        for n, (p, inicio) in enumerate(transiciones(estacion, ahora - self.SALTEO_SEGUNDOS)):
            if n >= 30:
                return None
            if p.clave == pista.clave:
                return replace(estacion, corrimiento=estacion.corrimiento - (inicio - ahora))
        return None

    def _version_del_esperado(self, pista: Pista, estacion: Estacion) -> Pista | None:
        """Soloist a veces toca otra versión del tema pedido (otra URI, mismo nombre con un agregado): es ese tema."""
        if not pista.cancion:
            return None
        if self._primero_pendiente:
            candidatos = [self._por_clave.get(self._esperado)]
        else:
            it = secuencia(estacion, self._reloj())
            candidatos = [next(it)[0], next(it)[0]]
        nombre = pista.cancion.casefold()

        def es_version(c: Pista) -> bool:          # el nombre entero y un agregado: «Run (Live)» sí, «Runaway» no
            base = c.cancion.casefold()
            return nombre.startswith(base) and (len(nombre) == len(base) or not nombre[len(base)].isalnum())
        return next((c for c in candidatos if c is not None and c.cancion and c.clave in self._por_clave
                     and es_version(c)), None)

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

    def _leer_cola(self, upcoming, estacion: Estacion | None) -> tuple[tuple[Pista, Estacion, float] | None,
                                                                       str | None]:
        """Con el lock tomado: recuerda lo encolado en la app (solo con duración: si no, no se puede correr la
        agenda). Devuelve el aviso para `al_encolado` si lo próximo en sonar es un encolado nuevo, y la clave del
        encolado ya avisado si lo sacaron de la cola sin que empezara (para `al_desencolado`)."""
        entradas = [u for u in upcoming if isinstance(u, dict)] if isinstance(upcoming, list) else []
        uris = [u["item"].get("uri") for u in entradas if isinstance(u.get("item"), dict)]
        if any(isinstance(uri, str) and uri.startswith("spotify:meta:") for uri in uris):
            return None, None        # la cola transitoria que manda Soloist al agregar un tema: no es la cola real
        encolados = {}
        for u in entradas:
            if u.get("source") == "queue":
                pista = self._pista_del_item(u.get("item"))
                if pista is not None and pista.duracion > 0:
                    encolados.setdefault(pista.clave, pista)
        self._encolados = encolados
        self._por_anunciar = None
        desencolado = None
        if self._anunciado is not None and self._anunciado not in encolados:
            desencolado, self._anunciado = self._anunciado, None
        if not entradas or entradas[0].get("source") != "queue" or estacion is None:
            return None, desencolado
        proxima = encolados.get((entradas[0].get("item") or {}).get("uri"))
        if proxima is None or proxima.clave == self._anunciado:
            return None, desencolado
        return self._aviso_de_encolado(proxima, estacion), desencolado

    def _aviso_de_encolado(self, proxima: Pista, estacion: Estacion) -> tuple[Pista, Estacion, float] | None:
        """Con el lock tomado: el aviso de `proxima` con el fin del tema actual; sin posición todavía (recién
        empezó un tema), queda pendiente hasta el próximo position_sync."""
        posicion = self.posicion()
        if posicion is None:
            self._por_anunciar = proxima
            return None
        self._anunciado, self._por_anunciar = proxima.clave, None
        return proxima, estacion, self._reloj() + max(0.0, self.pista_actual.duracion - posicion)

    def _pista_del_item(self, item) -> Pista | None:
        """La pista de un ítem de Soloist: la de la emisora si es suya; si no, con lo que trae el ítem."""
        if not isinstance(item, dict) or not isinstance(item.get("uri"), str):
            return None
        uri = item["uri"]
        if uri in self._por_clave:
            return self._por_clave[uri]
        deco = item.get("decorations") if isinstance(item.get("decorations"), dict) else {}
        nombre = _nombre(deco)          # sin nombre no se anuncia (el título queda solo para mostrar)
        ms = (deco.get("playback") or {}).get("duration_ms") if isinstance(deco.get("playback"), dict) else None
        duracion = ms / 1000 if isinstance(ms, (int, float)) and not isinstance(ms, bool) and ms > 0 else 0.0
        creadores = deco.get("creators") if isinstance(deco.get("creators"), list) else []
        artista = ", ".join(n for n in map(_nombre_de_entidad, creadores) if n) or None
        titulo = " - ".join(x for x in (artista, nombre) if x) or uri
        return Pista(ruta=None, duracion=duracion, titulo=titulo, fuente="spotify", artista=artista, cancion=nombre,
                     album=_nombre_de_entidad(deco.get("parent")), uri=uri)

    def actualizar(self, estacion: Estacion) -> None:
        """El rescan de la radio: si `estacion` es la que suena, toma sus pistas. El corrimiento y los pedidos
        siguen siendo los de acá (los ve empezar y terminar este reproductor)."""
        with self._lock:
            if self._estacion is None or self._estacion.nombre != estacion.nombre:
                return
            self._estacion = replace(estacion, corrimiento=self._estacion.corrimiento,
                                     pedidos=self._estacion.pedidos)
            self._por_clave = {p.clave: p for p in estacion.pistas}

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

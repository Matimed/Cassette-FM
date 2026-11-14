import logging
import threading
import time
from collections.abc import Callable

from cassette_fm.biblioteca import Pista
from cassette_fm.config import ConfigDJ
from cassette_fm.intervenciones import Intervencion, RegistroIntervenciones

_log = logging.getLogger("cassette_fm")


class Locutor:
    """Reproduce la voz del DJ en un segundo mpv y baja la música mientras habla.

    La voz se dispara por el inicio REAL del tema en mpv (`pista_iniciada`); el reloj solo sirve para
    entrar a mitad de frase cuando se sintoniza con la ventana ya abierta (`al_sintonizar`)."""

    def __init__(self, voz, musica, registro: RegistroIntervenciones,
                 configuracion: Callable[[str], ConfigDJ], reloj: Callable[[], float] = time.time):
        self._voz = voz
        self._musica = musica
        self._registro = registro
        self._configuracion = configuracion
        self._reloj = reloj
        self._lock = threading.Lock()
        self._sintonizada: str | None = None
        self._reproducidas: set[str] = set()     # ids ya reproducidos en esta sintonía
        self._sonadas: set[str] = set()          # ids que alguna vez sonaron (para avisar de las que vencen mudas)
        self._sesion = 0                         # invalida temporizadores de sintonías anteriores
        self._volumen: int | None = None
        self._hablando = False
        self._entrada: int | None = None         # id de la entrada de mpv que está sonando
        self._cfg_actual: ConfigDJ | None = None
        self._estacion_voz: str | None = None    # estación de la intervención que suena
        self._estacion_anclaje: str | None = None
        self._voz_id = 0
        self._t_seguridad: threading.Timer | None = None
        self._t_anclaje: threading.Timer | None = None
        voz.al_evento = self._evento_voz

    @property
    def hablando(self) -> bool:
        return self._hablando

    def registrar(self, i: Intervencion) -> None:
        cfg = self._configuracion(i.estacion)
        if i.duracion > cfg.duracion_maxima_segundos:
            raise ValueError(f"el clip dura {i.duracion:.1f} s y el máximo es "
                             f"{cfg.duracion_maxima_segundos:g} s")
        with self._lock:
            self._registro.agregar(i)
            ahora = self._reloj()
            if self._sintonizada == i.estacion and i.inicio <= ahora < i.fin:
                self._hablar(i, ahora - i.inicio)

    def al_sintonizar(self, estacion: str) -> None:
        with self._lock:
            self._sesion += 1
            self._cancelar_anclaje()
            self._cortar()
            self._reproducidas.clear()
            self._expirar()
            self._sintonizada = estacion
            ahora = self._reloj()
            activa = self._registro.activa(estacion, ahora)
            if activa is not None:
                self._hablar(activa, ahora - activa.inicio)
            # El tema en el que se entra viene empezado: si el reloj dice que la voz ya debía haber empezado
            # (sonó desde el segundo que correspondía, o ya no queda frase que valga), el `file-loaded` de ese
            # tema NO es el inicio real de nada y no debe dispararla de nuevo.
            for i in self._registro.candidatas(estacion):
                if i.inicio <= ahora:
                    self._reproducidas.add(i.id)

    def descartar_estacion(self, estacion: str) -> None:
        """La agenda de la estación cambió: sus intervenciones ya no valen (y la voz en curso tampoco)."""
        with self._lock:
            self._registro.quitar_estacion(estacion)
            if self._estacion_anclaje == estacion:
                self._cancelar_anclaje()
            if self._hablando and self._estacion_voz == estacion:
                self._cortar()

    def pista_iniciada(self, pista: Pista, estacion: str) -> None:
        with self._lock:
            if estacion != self._sintonizada:
                return
            cfg = self._configuracion(estacion)
            ahora = self._reloj()
            for i in self._registro.candidatas(estacion):
                if (i.pista_destino == str(pista.ruta) and i.id not in self._reproducidas
                        and abs(ahora - (i.inicio - cfg.retraso_voz_segundos)) <= cfg.tolerancia_desfase_segundos):
                    self._reproducidas.add(i.id)     # evita dispararla otra vez en esta sintonía
                    sesion = self._sesion
                    self._cancelar_anclaje()
                    self._estacion_anclaje = estacion
                    self._t_anclaje = threading.Timer(cfg.retraso_voz_segundos, self._hablar_anclada, (i, sesion))
                    self._t_anclaje.daemon = True
                    self._t_anclaje.start()
                    return

    def vigentes(self) -> list[Intervencion]:
        with self._lock:
            self._expirar()
            ahora = self._reloj()
            return [i for i in self._registro.todas() if i.fin > ahora]

    def volumen(self, valor: int) -> None:
        with self._lock:
            self._volumen = valor
            if self._hablando:
                self._poner_volumen_de_la_voz()

    def detener(self) -> None:
        with self._lock:
            self._sesion += 1
            self._cancelar_anclaje()
            self._cortar()
            self._sintonizada = None
            self._reproducidas.clear()

    def cerrar(self) -> None:
        self.detener()
        self._voz.cerrar()

    # --- internos (con el lock tomado) ---

    def _expirar(self) -> None:
        for i in self._registro.limpiar():
            if i.id in self._sonadas:
                self._sonadas.discard(i.id)
            else:
                _log.warning("la intervención %s de %r venció sin sonar", i.id, i.estacion)

    def _hablar_anclada(self, i: Intervencion, sesion: int) -> None:
        with self._lock:
            if sesion == self._sesion:
                self._hablar(i, 0.0)

    def _hablar(self, i: Intervencion, desde: float) -> None:
        cfg = self._configuracion(i.estacion)
        if self._hablando or self._volumen == 0 or i.duracion - desde < cfg.minimo_restante_segundos:
            return
        self._reproducidas.add(i.id)
        self._sonadas.add(i.id)
        self._hablando = True
        self._cfg_actual = cfg
        self._estacion_voz = i.estacion
        try:
            self._musica.atenuar(cfg.nivel_musica_con_voz, cfg.rampa_bajada_segundos)
            self._poner_volumen_de_la_voz()
            resp = self._voz.comando("loadfile", url=str(i.audio), flags="replace",
                                     options={"start": f"{desde:.3f}"})
            self._entrada = (resp or {}).get("playlist_entry_id")
            self._voz_id += 1
            self._armar_seguridad(self._voz_id, (i.duracion - desde) + cfg.margen_seguridad_voz_segundos)
        except Exception:
            _log.exception("no se pudo reproducir la intervención %s", i.id)
            self._terminar()

    def _poner_volumen_de_la_voz(self) -> None:
        if self._volumen is not None:
            try:
                self._voz.comando("set_property", "volume", self._volumen)
            except Exception:
                _log.warning("no se pudo ajustar el volumen de la voz")

    def _terminar(self) -> None:
        """Fin de la voz (idempotente): devuelve la música a su nivel."""
        if not self._hablando:
            return
        self._hablando = False
        self._entrada = None
        if self._t_seguridad is not None:
            self._t_seguridad.cancel()
            self._t_seguridad = None
        rampa = self._cfg_actual.rampa_subida_segundos if self._cfg_actual else 0.0
        try:
            self._musica.atenuar(1.0, rampa)
        except Exception:
            _log.exception("no se pudo restaurar el volumen de la música")

    def _cortar(self) -> None:
        if self._hablando:
            try:
                self._voz.comando("stop")
            except Exception:
                _log.warning("no se pudo detener la voz")
            self._terminar()

    def _armar_seguridad(self, voz_id: int, segundos: float) -> None:
        if self._t_seguridad is not None:
            self._t_seguridad.cancel()
        self._t_seguridad = threading.Timer(segundos, self._seguridad, (voz_id,))
        self._t_seguridad.daemon = True
        self._t_seguridad.start()

    def _seguridad(self, voz_id: int) -> None:
        with self._lock:
            if voz_id == self._voz_id:
                self._terminar()

    def _cancelar_anclaje(self) -> None:
        if self._t_anclaje is not None:
            self._t_anclaje.cancel()
            self._t_anclaje = None

    def _evento_voz(self, evento: dict) -> None:
        if evento.get("event") != "end-file":
            return
        with self._lock:
            # solo el fin de la entrada que suena: el de un clip cortado antes llega tarde y no vale
            if self._hablando and evento.get("playlist_entry_id") == self._entrada:
                self._terminar()

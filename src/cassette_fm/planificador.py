import hashlib
import json
import logging
import math
import os
import random
import re
import threading
import time
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from pathlib import Path

from cassette_fm.agenda import corrimiento_total, secuencia, transiciones
from cassette_fm.biblioteca import Estacion, Pedido, Pista
from cassette_fm.cliente_dj import ClienteDJ, ErrorDJ
from cassette_fm.config import ConfigDJ, Frecuencia
from cassette_fm.intervenciones import Intervencion, RegistroIntervenciones
from cassette_fm.planificacion import Hueco, Ultima, armar_pedido, elegir_hueco

_log = logging.getLogger("cassette_fm")

_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")
_TOLERANCIA_CORRIMIENTO = 2.0     # un pedido que duró casi lo que debía no cambia la agenda


@dataclass
class _Trabajo:
    """El trabajo en curso: ya se hizo el POST al servicio DJ."""
    id: str
    estacion: str
    inicio_tema: float
    inicio_voz: float
    pista_destino: str
    enviado_en: float
    duracion_maxima: float
    estado: str = "enviado"      # lo último que contó el servicio
    peticion: str | None = None  # "antes"/"despues": anuncia una petición (no se cancela si cambia la agenda)
    pedido: str | None = None    # clave del tema pedido que anuncia


@dataclass(frozen=True)
class _Peticion:
    """Un anuncio de petición por pedir (tiene prioridad sobre las intervenciones normales)."""
    estacion: str
    modo: str                    # "antes": sobre el comienzo del pedido; "despues": sobre el tema que lo sigue
    pista: Pista                 # el tema destino
    inicio_tema: float
    anterior: Pista | None
    pedido: str                  # clave del tema pedido


def _firma(estacion: Estacion) -> str:
    """Resume la línea de tiempo futura de la estación (pistas y corrimiento total, con los pedidos en curso por su
    duración nominal): si cambia, las intervenciones reservadas ya no caen donde deben."""
    texto = json.dumps([(p.clave, p.duracion) for p in estacion.pistas], ensure_ascii=False)
    return f"{hashlib.sha1(texto.encode('utf-8')).hexdigest()}|{corrimiento_total(estacion):.3f}"


def _misma_agenda(a: str, b: str) -> bool:
    (sha_a, _, total_a), (sha_b, _, total_b) = a.partition("|"), b.partition("|")
    return sha_a == sha_b and abs(float(total_a or 0) - float(total_b or 0)) <= _TOLERANCIA_CORRIMIENTO


def _con_nombre(pista: Pista | None) -> bool:
    return pista is not None and bool(pista.artista and pista.cancion)


class Planificador:
    """Decide cuándo pedirle una intervención al servicio DJ y la reserva en la agenda de la estación.

    Un solo trabajo en curso a la vez ("en curso" = ya se hizo el POST); antes de eso, a lo sumo el pedido para la
    estación sintonizada, que se recalcula en cada vuelta. La red nunca se toca con el lock tomado: los hooks de
    la radio (`al_sintonizar`, `al_apagar`, `al_rescan`) no esperan al servicio DJ."""

    def __init__(self, cliente: ClienteDJ, locutor, registro: RegistroIntervenciones,
                 configuracion: Callable[[str], ConfigDJ], archivo: Path, dir_clips: Path,
                 reloj: Callable[[], float] = time.time, azar: random.Random | None = None,
                 gracia_segundos: float = 60.0, intervalo_segundos: float = 1.0):
        self._cliente = cliente
        self._locutor = locutor
        self._registro = registro
        self._configuracion = configuracion
        self._archivo = Path(archivo)
        self._dir_clips = Path(dir_clips)
        self._reloj = reloj
        self._azar = azar or random.Random()
        self._gracia = gracia_segundos
        self._intervalo = intervalo_segundos
        self._lock = threading.RLock()          # estado interno (secciones cortas, sin red)
        self._turno = threading.Lock()          # una vuelta a la vez (el hilo, pedir_ahora y los tests)
        self._estacion: Estacion | None = None
        self._ultima: dict[str, Ultima] = {}
        self._recientes: dict[str, list[str]] = {}
        self._firmas: dict[str, str] = {}
        self._epoca: dict[str, int] = {}        # sube cuando la agenda de la estación cambia: lo calculado antes ya no vale
        self._trabajo: _Trabajo | None = None
        self._pendientes: list[_Peticion] = []
        self._encolados: set[str] = set()      # claves de pedidos ya avisados por la cola
        self._ultima_peticion: set[str] = set()  # estaciones cuya última intervención fue una petición
        self._a_cancelar: list[str] = []
        self._apagado = False                   # el DJ apagado: no se le pide nada al servicio (se recuerda)
        self._servicio_caido = False
        self._error: str | None = None
        self._no_antes_de = 0.0
        self._espera_red = 0.0
        self._espera_trabajo = 0.0
        self._parar = threading.Event()
        self._hilo: threading.Thread | None = None
        self._cargar()

    # --- hooks de la radio ---

    def al_sintonizar(self, estacion: Estacion) -> None:
        with self._lock:
            self._estacion = estacion
            cambiada = self._cambio_la_agenda(estacion)
        for nombre in cambiada:
            self._descartar(nombre)

    def al_apagar(self) -> None:
        with self._lock:
            self._estacion = None

    def al_rescan(self, estaciones: Sequence[Estacion]) -> None:
        with self._lock:
            cambiadas = []
            for e in estaciones:
                cambiadas += self._cambio_la_agenda(e)
            actuales = {e.nombre for e in estaciones}
            for nombre in [n for n in self._firmas if n not in actuales]:
                del self._firmas[nombre]
                cambiadas.append(nombre)
            if self._estacion is not None:
                self._estacion = next((e for e in estaciones if e.nombre == self._estacion.nombre), None)
        for nombre in cambiadas:
            self._descartar(nombre)

    # --- peticiones (la cola de Spotify) ---

    def al_encolado(self, pista: Pista, estacion: Estacion, fin_actual: float) -> None:
        """Encolaron `pista`, que va a sonar cuando termine el tema actual (`fin_actual`): si hay tiempo, se pide el
        anuncio "antes"; si no, va "después" cuando empiece."""
        with self._lock:
            if self._apagado or self._estacion is None or self._estacion.nombre != estacion.nombre \
                    or pista.clave in self._encolados:
                return
            # el próximo es otro: lo encolado antes lo sacaron de la cola, y el "después" de un pedido que iba a sonar
            # en ese borde anunciaba un tema que ya no empieza ahí
            viejos, tolerancia = self._encolados, self._configuracion(estacion.nombre).tolerancia_desfase_segundos
            self._olvidar_anuncios("antes", lambda _, destino, __: destino in viejos)
            self._olvidar_anuncios("despues", lambda nombre, _, inicio: nombre == estacion.nombre
                                   and abs(inicio - fin_actual) <= tolerancia)
            self._encolados = {pista.clave}
            if not _con_nombre(pista):
                return
            ahora = self._reloj()
            if fin_actual - ahora < self._configuracion(estacion.nombre).peticion_margen_segundos:
                return
            anterior = next(secuencia(estacion, ahora))[0]
            self._pendientes.append(_Peticion(estacion.nombre, "antes", pista, fin_actual,
                                              anterior if _con_nombre(anterior) else None, pista.clave))

    def al_cambiar_agenda(self, estacion: Estacion, nuevo: Pedido | None) -> None:
        """La agenda cambió por pedidos (`nuevo`: el que acaba de empezar). Si su anuncio "antes" no está listo,
        se pide el "después"."""
        with self._lock:
            if self._estacion is not None and self._estacion.nombre == estacion.nombre:
                self._estacion = estacion
            cambiada = self._cambio_la_agenda(estacion)
        for nombre in cambiada:
            self._descartar(nombre)
        if nuevo is None:
            return
        clave = nuevo.pista.clave
        with self._lock:
            self._encolados.discard(clave)
            self._pendientes = [p for p in self._pendientes if not (p.modo == "antes" and p.pedido == clave)]
            cfg = self._configuracion(estacion.nombre)
            for i in self._registro.todas():
                if i.estacion != estacion.nombre or i.peticion != "antes" or i.pista_destino != clave:
                    continue
                if abs(i.inicio - cfg.retraso_voz_segundos - nuevo.inicio) <= cfg.tolerancia_desfase_segundos:
                    return                     # el "antes" ya está reservado: va a sonar
                # empezó lejos de donde se esperaba (salteado el tema actual): el "antes" no va a sonar
                self._registro.quitar(i)
            t = self._trabajo
            if t is not None and t.peticion == "antes" and t.pedido == clave:
                self._a_cancelar.append(t.id)
                self._trabajo = None
                self._guardar()
            if self._estacion is None or self._estacion.nombre != estacion.nombre or not _con_nombre(nuevo.pista):
                return
            siguiente, inicio = next(transiciones(estacion, nuevo.inicio + 0.001))
            if _con_nombre(siguiente):
                self._pendientes.append(_Peticion(estacion.nombre, "despues", siguiente, inicio, nuevo.pista, clave))

    def _olvidar_anuncios(self, modo: str, cual: Callable[[str, str, float], bool]) -> None:
        """Con el lock tomado: los anuncios `modo` de peticiones que ya no van a sonar (pendientes, en preparación o
        reservados), según `cual(estacion, tema destino, inicio del tema destino)`."""
        self._pendientes = [p for p in self._pendientes
                            if not (p.modo == modo and cual(p.estacion, p.pista.clave, p.inicio_tema))]
        for i in self._registro.todas():
            if i.peticion == modo and cual(i.estacion, i.pista_destino,
                                           i.inicio - self._configuracion(i.estacion).retraso_voz_segundos):
                self._registro.quitar(i)
        t = self._trabajo
        if t is not None and t.peticion == modo and cual(t.estacion, t.pista_destino, t.inicio_tema):
            self._a_cancelar.append(t.id)
            self._trabajo = None
            self._guardar()

    # --- pedido manual ---

    def pedir_ahora(self, en_segundos: float) -> dict:
        """Pide una intervención para el primer tema que arranque dentro de al menos `en_segundos`, ignorando
        la frecuencia."""
        with self._turno:
            with self._lock:
                estacion = self._estacion
                if self._apagado:
                    raise ValueError("el DJ está apagado: prendelo con `cassette dj modo plantillas` (o llm)")
                if estacion is None:
                    raise ValueError("no hay ninguna estación sintonizada")
                if self._trabajo is not None:
                    raise ValueError("ya hay un pedido en curso: esperá a que termine")
                ahora = self._reloj()
                cfg = replace(self._configuracion(estacion.nombre), margen_minutos=en_segundos / 60,
                              frecuencia=Frecuencia("temas", 1, 1))
                ocupados = [(i.inicio, i.fin) for i in self._registro.de_la_estacion(estacion.nombre)]
                hueco = elegir_hueco(estacion, ahora, cfg, None, self._azar, ocupados)
                if hueco is None:
                    raise ValueError("no hay un tema con artista y título para dedicarle una intervención")
                id_ = uuid.uuid4().hex
                pedido = armar_pedido(id_, estacion.nombre, hueco, cfg, self._recientes.get(estacion.nombre, []))
            try:
                devuelto = self._cliente.enviar(pedido)
                if devuelto != id_:
                    raise ErrorDJ(f"el servicio DJ contestó otro id ({devuelto!r}) al pedido {id_}")
            except ErrorDJ as e:
                raise ValueError(str(e)) from None
            with self._lock:
                self._trabajo = _Trabajo(id_, estacion.nombre, hueco.inicio_tema, hueco.inicio_voz,
                                         hueco.pista.clave, ahora, cfg.duracion_maxima_segundos)
                self._guardar()
                self._no_antes_de = 0.0       # un pedido manual no hereda esperas de caídas anteriores
                self._espera_trabajo = 0.0
            self._ok()
            return {"id": id_, "estacion": estacion.nombre, "inicio": hueco.inicio_voz,
                    "en_segundos": hueco.inicio_voz - ahora, "tema": hueco.pista.titulo}

    def modo(self, nuevo: str | None = None) -> dict:
        """El modo del DJ: apagado (la radio no le pide nada al servicio, que puede estar parado) o el del
        servicio (plantillas | llm); con `nuevo` lo cambia. ValueError con el mensaje si el servicio no responde
        o lo rechaza; en ese caso, si estaba apagado, sigue apagado."""
        if nuevo == "apagado":
            self._apagar()
            return {"modo": "apagado"}
        with self._lock:
            if nuevo is None and self._apagado:
                return {"modo": "apagado"}
        try:
            respuesta = {"modo": self._cliente.modo()} if nuevo is None else self._cliente.poner_modo(nuevo)
        except ErrorDJ as e:
            raise ValueError(str(e)) from None
        if nuevo is not None:
            with self._lock:
                if self._apagado:
                    self._apagado = False
                    self._pendientes = []           # lo que llegó mientras estaba apagado ya es viejo
                    self._guardar()
        return respuesta

    def _apagar(self) -> None:
        """Cancela el trabajo en curso (en la próxima vuelta) y descarta todo lo reservado, incluso los anuncios
        de peticiones: apagado, el DJ no habla más."""
        with self._turno:
            with self._lock:
                self._apagado = True
                self._pendientes = []
                if self._trabajo is not None:
                    self._a_cancelar.append(self._trabajo.id)
                    self._trabajo = None
                self._guardar()
            for nombre in sorted({i.estacion for i in self._registro.todas()}):
                self._locutor.descartar_estacion(nombre)
            for i in self._registro.todas():
                self._registro.quitar(i)

    # --- la vuelta ---

    def paso(self) -> None:
        with self._turno:
            self._cancelaciones_pendientes()
            with self._lock:
                if self._apagado:
                    return
            if self._reloj() < self._no_antes_de:
                return
            with self._lock:
                trabajo = self._trabajo
                pendiente = self._pendientes[0] if self._pendientes else None
            if pendiente is not None and (trabajo is None or not trabajo.peticion):
                self._iniciar_peticion(pendiente)
            elif trabajo is not None:
                self._avanzar(trabajo)
            else:
                self._iniciar()

    def iniciar(self) -> None:
        if self._hilo is not None:
            return
        self._parar.clear()
        self._hilo = threading.Thread(target=self._correr, daemon=True, name="planificador-dj")
        self._hilo.start()

    def cerrar(self) -> None:
        """Detiene el hilo. El trabajo en curso no se cancela: queda guardado para retomarlo al volver."""
        self._parar.set()
        if self._hilo is not None:
            self._hilo.join(timeout=15)
            self._hilo = None

    def estado(self) -> dict:
        with self._lock:
            ahora = self._reloj()
            t = self._trabajo
            return {
                "estacion": self._estacion.nombre if self._estacion else None,
                "apagado": self._apagado,
                "en_curso": ({"id": t.id, "estacion": t.estacion, "estado": t.estado,
                              "en_segundos": t.inicio_voz - ahora} if t else None),
                "servicio": "no responde" if self._servicio_caido else "ok",
                "error": self._error,
                "proximo_intento_en": (self._no_antes_de - ahora) if self._no_antes_de > ahora else None,
            }

    # --- internos ---

    def _correr(self) -> None:
        while not self._parar.wait(self._intervalo):
            try:
                self.paso()
            except Exception:
                _log.exception("error inesperado en el planificador del DJ")

    def _cambio_la_agenda(self, estacion: Estacion) -> list[str]:
        """Con el lock tomado: guarda la firma de la agenda y dice si la estación ya tenía otra distinta."""
        firma = _firma(estacion)
        previa = self._firmas.get(estacion.nombre)
        self._firmas[estacion.nombre] = firma
        self._guardar()
        return [estacion.nombre] if previa is not None and not _misma_agenda(previa, firma) else []

    def _descartar(self, nombre: str, motivo: str = "la agenda de %r cambió", desde: float | None = None) -> None:
        """La agenda de `nombre` cambió: sus reservas, su última intervención y su trabajo en curso ya no valen
        (salvo los anuncios de peticiones, anclados a su tema). Con `desde`, lo de antes de ese instante sigue."""
        _log.info(motivo + ": se descartan sus intervenciones reservadas", nombre)
        with self._lock:
            self._epoca[nombre] = self._epoca.get(nombre, 0) + 1
        self._locutor.descartar_estacion(nombre, desde=desde)
        with self._lock:
            ultima = self._ultima.get(nombre)
            if nombre not in self._ultima_peticion and ultima is not None and (desde is None
                                                                               or ultima.inicio_tema >= desde):
                self._ultima.pop(nombre, None)
            if self._trabajo is not None and self._trabajo.estacion == nombre and not self._trabajo.peticion:
                self._a_cancelar.append(self._trabajo.id)
                self._trabajo = None
            self._guardar()

    def _cancelaciones_pendientes(self) -> None:
        with self._lock:
            ids, self._a_cancelar = self._a_cancelar, []
        for id_ in ids:
            self._cancelar_en_el_servicio(id_)

    def _cancelar_en_el_servicio(self, id_: str) -> None:
        try:
            self._cliente.cancelar(id_)
        except (ErrorDJ, ValueError) as e:
            _log.info("no se pudo cancelar el pedido %s en el servicio DJ: %s", id_, e)

    def _limpiar(self, id_: str) -> None:
        with self._lock:
            if self._trabajo is not None and self._trabajo.id == id_:
                self._trabajo = None
                self._guardar()

    def _avanzar(self, t: _Trabajo) -> None:
        ahora = self._reloj()
        cfg = self._configuracion(t.estacion)
        if ahora > t.inicio_voz + t.duracion_maxima + self._gracia:
            _log.info("el pedido %s llegó tarde: su hueco ya pasó, se cancela", t.id)
            self._cancelar_en_el_servicio(t.id)
            return self._limpiar(t.id)
        if ahora - t.enviado_en > cfg.espera_trabajo_maxima_segundos:
            _log.warning("el pedido %s lleva más de %g s sin terminar: se cancela", t.id,
                         cfg.espera_trabajo_maxima_segundos)
            self._cancelar_en_el_servicio(t.id)
            return self._limpiar(t.id)
        try:
            estado = self._cliente.estado(t.id)
        except ErrorDJ as e:
            return self._fallo(e, cfg)
        self._ok()
        if estado is None:
            _log.info("el servicio DJ ya no conoce el pedido %s: se descarta", t.id)
            self._limpiar(t.id)
            return self._esperar_tras_error(cfg)
        situacion = estado.get("estado")
        with self._lock:
            t.estado = str(situacion)
        if situacion == "cancelado":
            self._limpiar(t.id)
            return self._esperar_tras_error(cfg)
        if situacion == "error":
            _log.warning("el servicio DJ no pudo preparar el pedido %s: %s", t.id, estado.get("error") or "sin detalle")
            self._limpiar(t.id)
            return self._esperar_tras_error(cfg)
        if situacion == "listo":
            self._recibir(t, estado, cfg)

    def _recibir(self, t: _Trabajo, estado: dict, cfg: ConfigDJ) -> None:
        if any(i.id == t.id for i in self._registro.todas()):
            return self._limpiar(t.id)       # ya estaba registrada (la radio se reinició a mitad de camino)
        duracion = estado.get("duracion")
        if (isinstance(duracion, bool) or not isinstance(duracion, (int, float)) or not math.isfinite(duracion)
                or not 0 < duracion <= cfg.duracion_maxima_segundos):
            _log.warning("el servicio DJ mandó una duración inválida para %s (%r): se descarta", t.id, duracion)
            self._cancelar_en_el_servicio(t.id)
            self._limpiar(t.id)
            return self._esperar_tras_error(cfg)
        audio = self._dir_clips / f"{t.id}.wav"
        try:
            self._cliente.descargar_audio(t.id, audio)
        except ErrorDJ as e:
            return self._fallo(e, cfg)
        with self._lock:
            if self._trabajo is not t:       # mientras tanto cambió la agenda de la estación: el hueco ya no vale
                audio.unlink(missing_ok=True)
                return
            try:
                intervencion = Intervencion(t.id, t.estacion, t.inicio_voz, float(duracion), audio,
                                            str(estado.get("texto") or ""), t.pista_destino, t.peticion)
                self._locutor.registrar(intervencion)
            except ValueError as e:
                audio.unlink(missing_ok=True)
                _log.warning("no se pudo reservar la intervención %s de %r: %s", t.id, t.estacion, e)
                self._trabajo = None
                self._guardar()
                self._espera_trabajo = self._siguiente(self._espera_trabajo, cfg)
                self._no_antes_de = max(self._no_antes_de, self._reloj() + self._espera_trabajo)
                return
            self._ultima[t.estacion] = Ultima(t.inicio_tema, t.inicio_voz + float(duracion))
            if t.peticion:
                self._ultima_peticion.add(t.estacion)
            else:
                self._ultima_peticion.discard(t.estacion)
            ingredientes = [x for x in (estado.get("ingredientes") or []) if isinstance(x, str)]
            recientes = self._recientes.get(t.estacion, []) + ingredientes
            self._recientes[t.estacion] = recientes[-cfg.recientes_cantidad:] if cfg.recientes_cantidad else []
            self._espera_trabajo = 0.0
            self._trabajo = None
            self._guardar()

    def _iniciar(self) -> None:
        with self._lock:
            estacion = self._estacion
            if estacion is None:
                return
            ahora = self._reloj()
            cfg = self._configuracion(estacion.nombre)
            vigentes = self._registro.de_la_estacion(estacion.nombre)
            if vigentes:
                return
            hueco = elegir_hueco(estacion, ahora, cfg, self._ultima.get(estacion.nombre), self._azar, [])
            if hueco is None:
                return
            id_ = uuid.uuid4().hex
            epoca = self._epoca.get(estacion.nombre, 0)
            pedido = armar_pedido(id_, estacion.nombre, hueco, cfg, self._recientes.get(estacion.nombre, []))
        try:
            devuelto = self._cliente.enviar(pedido)
            if devuelto != id_:
                raise ErrorDJ(f"el servicio DJ contestó otro id ({devuelto!r}) al pedido {id_}")
        except ErrorDJ as e:
            return self._fallo(e, cfg)
        self._ok()
        with self._lock:
            if self._epoca.get(estacion.nombre, 0) != epoca:     # la agenda cambió durante el POST
                self._a_cancelar.append(id_)
                return
            self._trabajo = _Trabajo(id_, estacion.nombre, hueco.inicio_tema, hueco.inicio_voz,
                                     hueco.pista.clave, ahora, cfg.duracion_maxima_segundos)
            self._guardar()

    def _iniciar_peticion(self, p: _Peticion) -> None:
        cfg = self._configuracion(p.estacion)
        ahora = self._reloj()
        inicio_voz = p.inicio_tema + cfg.retraso_voz_segundos
        with self._lock:
            if p in self._pendientes:
                self._pendientes.remove(p)
        if inicio_voz <= ahora:
            _log.info("el anuncio de la petición de %r ya no llega a tiempo: se saltea", p.estacion)
            return
        # lo normal planificado desde el pedido ya no va a caer donde debía (el pedido corre la agenda); lo del
        # tema actual (la voz que suena, la anclada) sigue valiendo. El borde del pedido es el real de Spotify, que
        # puede ir corrido del reloj (hasta la tolerancia): la normal del tema que iba ahí queda un poco antes
        self._descartar(p.estacion, "llegó una petición en %r", desde=p.inicio_tema - cfg.tolerancia_desfase_segundos)
        self._cancelaciones_pendientes()
        id_ = uuid.uuid4().hex
        with self._lock:
            pedido = armar_pedido(id_, p.estacion, Hueco(p.pista, p.inicio_tema, inicio_voz, p.anterior), cfg,
                                  self._recientes.get(p.estacion, []), peticion=p.modo)
        try:
            devuelto = self._cliente.enviar(pedido)
            if devuelto != id_:
                raise ErrorDJ(f"el servicio DJ contestó otro id ({devuelto!r}) al pedido {id_}")
        except ErrorDJ as e:
            with self._lock:
                self._pendientes.insert(0, p)      # se reintenta mientras llegue a tiempo
            return self._fallo(e, cfg)
        self._ok()
        with self._lock:
            self._trabajo = _Trabajo(id_, p.estacion, p.inicio_tema, inicio_voz, p.pista.clave, ahora,
                                     cfg.duracion_maxima_segundos, peticion=p.modo, pedido=p.pedido)
            self._guardar()

    # --- fallos y esperas ---

    def _ok(self) -> None:
        with self._lock:
            if self._servicio_caido:
                _log.info("el servicio DJ volvió a responder")
            self._servicio_caido = False
            self._error = None
            self._espera_red = 0.0

    def _fallo(self, e: Exception, cfg: ConfigDJ) -> None:
        """El servicio no respondió: un solo aviso por episodio y espera creciente antes de reintentar."""
        with self._lock:
            if not self._servicio_caido:
                _log.warning("%s: la radio sigue sin intervenciones y reintenta sola", e)
            self._servicio_caido = True
            self._error = str(e)
            self._espera_red = self._siguiente(self._espera_red, cfg)
            self._no_antes_de = max(self._no_antes_de, self._reloj() + self._espera_red)

    def _esperar_tras_error(self, cfg: ConfigDJ) -> None:
        """El servicio contestó pero el pedido falló: no se vuelve a pedir enseguida."""
        with self._lock:
            self._espera_trabajo = self._siguiente(self._espera_trabajo, cfg)
            self._no_antes_de = max(self._no_antes_de, self._reloj() + self._espera_trabajo)

    @staticmethod
    def _siguiente(actual: float, cfg: ConfigDJ) -> float:
        if actual <= 0:
            return cfg.espera_reintento_segundos
        return min(actual * 2, cfg.espera_reintento_maxima_segundos)

    # --- persistencia ---

    def _guardar(self) -> None:
        with self._lock:
            datos = {
                "ultima": {n: [u.inicio_tema, u.fin] for n, u in self._ultima.items()},
                "recientes": self._recientes,
                "firmas": self._firmas,
                "en_curso": ({k: v for k, v in vars(self._trabajo).items() if k != "estado"}
                             if self._trabajo else None),
                "apagado": self._apagado,
            }
            try:
                self._archivo.parent.mkdir(parents=True, exist_ok=True)
                tmp = self._archivo.with_suffix(self._archivo.suffix + ".tmp")
                tmp.write_text(json.dumps(datos, ensure_ascii=False), encoding="utf-8")
                os.replace(tmp, self._archivo)
            except OSError as e:
                _log.warning("no se pudo guardar el estado del planificador en %s: %s", self._archivo, e)

    def _cargar(self) -> None:
        try:
            datos = json.loads(self._archivo.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return
        except (OSError, ValueError) as e:
            _log.warning("estado del planificador ilegible (%s): se empieza vacío", e)
            return
        if not isinstance(datos, dict):
            return
        self._apagado = datos.get("apagado") is True
        try:
            self._ultima = {str(n): Ultima(float(v[0]), float(v[1])) for n, v in dict(datos.get("ultima", {})).items()}
            self._recientes = {str(n): [str(x) for x in v] for n, v in dict(datos.get("recientes", {})).items()}
            self._firmas = {str(n): str(v) for n, v in dict(datos.get("firmas", {})).items()}
        except (TypeError, ValueError, IndexError, KeyError):
            _log.warning("estado del planificador con datos inválidos: se empieza vacío")
            self._ultima, self._recientes, self._firmas = {}, {}, {}
        try:
            d = datos.get("en_curso")
            if isinstance(d, dict):
                t = _Trabajo(id=str(d["id"]), estacion=str(d["estacion"]), inicio_tema=float(d["inicio_tema"]),
                             inicio_voz=float(d["inicio_voz"]), pista_destino=str(d["pista_destino"]),
                             enviado_en=float(d["enviado_en"]), duracion_maxima=float(d["duracion_maxima"]),
                             peticion=d.get("peticion") if d.get("peticion") in ("antes", "despues") else None,
                             pedido=str(d["pedido"]) if d.get("pedido") else None)
                if _ID.fullmatch(t.id):
                    self._trabajo = t
        except (KeyError, TypeError, ValueError):
            _log.warning("el trabajo en curso guardado es inválido: se descarta")

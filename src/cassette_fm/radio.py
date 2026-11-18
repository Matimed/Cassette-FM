import logging
import shutil
import threading
import time
import unicodedata
import uuid
from collections.abc import Callable
from dataclasses import replace
from itertools import islice
from pathlib import Path

import mutagen

from cassette_fm.audio_router import AudioRouterError
from cassette_fm.agenda import desfase, plegar_vencidos, transiciones
from cassette_fm.biblioteca import Estacion, Pedido, Pista
from cassette_fm.clips import generar_clip_de_prueba
from cassette_fm.config import ConfigDJ, Estado
from cassette_fm.intervenciones import Intervencion

_log = logging.getLogger("cassette_fm")


VOLUMEN_MINIMO = 50   # con el volumen en 0 la radio está apagada; al encender se parte de acá


def agenda_de(estacion: Estacion) -> dict:
    """Lo que se guarda en `Estado.agendas` de una emisora."""
    return {"corrimiento": estacion.corrimiento, "pedidos": [
        {"inicio": p.inicio, "uri": p.pista.uri, "ruta": str(p.pista.ruta) if p.pista.ruta else None,
         "duracion": p.pista.duracion, "titulo": p.pista.titulo, "artista": p.pista.artista,
         "cancion": p.pista.cancion, "album": p.pista.album, "isrc": p.pista.isrc} for p in estacion.pedidos]}


def _pedido(d: dict, fuente: str) -> Pedido:
    pista = Pista(ruta=Path(d["ruta"]) if d.get("ruta") else None, duracion=float(d["duracion"]),
                  titulo=d["titulo"], fuente="spotify" if d.get("uri") else fuente, artista=d.get("artista"),
                  cancion=d.get("cancion"), album=d.get("album"), isrc=d.get("isrc"), uri=d.get("uri"))
    return Pedido(pista, float(d["inicio"]))


def aplicar_agendas(estaciones: list[Estacion], agendas: dict, ahora: float) -> list[Estacion]:
    """Pone a cada emisora el corrimiento y los pedidos guardados (por nombre) y pliega los que ya vencieron."""
    resultado = []
    for e in estaciones:
        a = agendas.get(e.nombre)
        if a is not None:
            try:
                e = replace(e, corrimiento=float(a["corrimiento"]),
                            pedidos=tuple(sorted((_pedido(d, e.fuente) for d in a.get("pedidos", [])),
                                                 key=lambda p: p.inicio)))
            except (KeyError, TypeError, ValueError):
                _log.warning("los pedidos guardados de %r no se pueden leer: se ignoran", e.nombre)
            e = plegar_vencidos(e, ahora)
        resultado.append(e)
    return resultado


def _normalizar(nombre: str) -> str:
    return unicodedata.normalize("NFC", nombre).casefold()


class EstacionInexistente(Exception):
    pass


class SinEstaciones(Exception):
    pass


class DJInactivo(Exception):
    """El DJ está apagado en la configuración."""


class BusInactivo(Exception):
    """El bus de audio virtual está apagado en la configuración (`bus_audio`)."""


class RadioApagada(Exception):
    """No hay una estación sintonizada."""


class Radio:
    def __init__(self, reproductor, estaciones: list[Estacion], estado: Estado,
                 guardar: Callable[[Estado], None], escanear: Callable[[], list[Estacion]],
                 avisar: Callable[[str, str], None] | None = None, dj=None,
                 configuracion_dj: Callable[[str], ConfigDJ] | None = None, dir_clips: Path | None = None,
                 reloj: Callable[[], float] = time.time, planificador=None,
                 iconos: Callable[[], dict[str, str]] | None = None, router=None):
        self._iconos = iconos
        self._router = router
        self._dj = dj
        self._planificador = planificador
        self._configuracion_dj = configuracion_dj or (lambda nombre: ConfigDJ())
        self._dir_clips = Path(dir_clips) if dir_clips is not None else None
        self._reloj = reloj
        self._lock_dj = threading.Lock()
        self._primera_pista = False       # el primer tema tras sintonizar se empieza a mitad de camino
        self._desfase: float | None = None
        self._reproductor = reproductor
        self._estado = estado
        self._estaciones = aplicar_agendas(list(estaciones), estado.agendas, reloj())
        self._guardar = guardar
        self._escanear = escanear
        self._avisar = avisar
        self._lock = threading.RLock()
        self.encendida = False
        # avisa cada cambio de emisora, de tema o de prendida/apagada; puede llegar con el lock tomado: no bloquear
        self.al_cambiar: Callable[[], None] | None = None
        reproductor.al_cambiar_pista = self._al_cambiar_pista
        reproductor.al_fallar = self._al_fallar
        reproductor.al_cambiar_agenda = self._al_cambiar_agenda
        reproductor.al_encolado = self._al_encolado
        reproductor.al_desencolado = self._al_desencolado
        self._poner_volumen(estado.volumen)
        if router is not None:
            try:
                self._aplicar_monitor(estado.monitor_local)
            except AudioRouterError as e:      # sin pactl la radio anda igual, solo que sin monitor
                _log.warning("no se pudo prender el monitor local: %s", e)

    def estaciones(self) -> list[Estacion]:
        with self._lock:
            return list(self._estaciones)

    def sintonizar(self, nombre: str) -> None:
        with self._lock:
            self._sintonizar(self._buscar(nombre))

    def siguiente(self) -> None:
        self._rotar(+1)

    def anterior(self) -> None:
        self._rotar(-1)

    def encender(self) -> None:
        with self._lock:
            self._requerir_estaciones()
            if self._router is not None and self.encendida:
                self._escuchar()          # ya transmite al bus: solo se vuelve a oír, sin re-sintonizar
                return
            actual = self._indice_actual()
            self._sintonizar(self._estaciones[0 if actual is None else actual])

    def apagar(self) -> None:
        with self._lock:
            self._apagar()

    def alternar(self) -> None:
        """Play/pausa. Con el bus, "pausa" es silenciar el monitor: la transmisión sigue (ver `apagar`)."""
        with self._lock:
            if not self.encendida:
                self.encender()
            elif self._router is None:
                self._apagar()
            elif self._router.local_monitor_enabled:
                self._poner_monitor(False)
            else:
                self._escuchar()

    def silenciar(self) -> None:
        """Dejar de oír la radio en esta PC. Sin bus no hay otra forma de callarla que apagarla; con bus la
        transmisión sigue y solo `apagar` la corta."""
        with self._lock:
            if self._router is None:
                self._apagar()
            else:
                self._poner_monitor(False)

    def volumen(self, valor: int | None = None, delta: int | None = None) -> int:
        with self._lock:
            if valor is None and delta is None:
                return self._estado.volumen
            previo = self._estado.volumen
            nuevo = valor if valor is not None else previo + delta
            self._estado.volumen = self._poner_volumen(nuevo)
            self._guardar(self._estado)
            if self._router is not None:
                # volumen 0 = silenciar el monitor (la transmisión sigue); subirlo desde el silencio lo prende
                if self._estado.volumen == 0:
                    self._poner_monitor(False)
                elif self._estado.volumen > previo:
                    self.encender()
                return self._estado.volumen
            # volumen 0 = mutear = apagada; subir el volumen estando apagada enciende
            if self._estado.volumen == 0:
                if self.encendida:
                    self._apagar()
            elif not self.encendida and self._estado.volumen > previo:
                self.encender()
            return self._estado.volumen

    def monitor(self, activo: bool) -> bool:
        """Prende o apaga la escucha en los parlantes de esta PC (el bus sigue sonando para otros)."""
        with self._lock:
            if self._router is None:
                raise BusInactivo("el bus de audio está apagado: poné `bus_audio = true` en config.toml")
            if activo:
                self._escuchar()
            else:
                self._poner_monitor(False)
            return activo

    def rescan(self) -> None:
        nuevas = list(self._escanear())   # fuera del lock: puede tardar con bibliotecas grandes
        with self._lock:
            nuevas = aplicar_agendas(nuevas, self._estado.agendas, self._reloj())
            self._estaciones = nuevas
            actual = self._indice_actual()
            if self.encendida and actual is None:
                if self._estaciones:
                    self._sintonizar(self._estaciones[0])
                else:
                    self._apagar()
            elif self.encendida:
                self._reproductor.actualizar(self._estaciones[actual])   # sus pistas nuevas (Spotify)
        if self._planificador is not None:   # fuera del lock: no tiene por qué frenar a la radio
            self._planificador.al_rescan(nuevas)

    def estado(self) -> dict:
        with self._lock:
            pista = self._reproductor.pista_actual
            segundo = self._reproductor.posicion() if self.encendida and pista else None
            return {
                "encendida": self.encendida,
                "estacion": self._estado.estacion,
                "pista": pista.titulo if self.encendida and pista else None,
                "volumen": self._estado.volumen,
                "estaciones": [e.nombre for e in self._estaciones],
                "fuente": self._fuente_actual() if self.encendida else None,
                "segundo": round(segundo, 1) if segundo is not None else None,
                "iconos": self._iconos() if self._iconos is not None else {},
            } | ({"monitor_local": self._router.local_monitor_enabled} if self._router is not None else {})

    def sonando(self) -> tuple[str, Pista] | None:
        """(emisora, pista) de lo que está sonando, o None si está apagada o todavía sin tema."""
        with self._lock:
            pista = self._reproductor.pista_actual
            if not self.encendida or pista is None:
                return None
            return self._estado.estacion, pista

    def _avisar_cambio(self) -> None:
        if self.al_cambiar is None:
            return
        try:
            self.al_cambiar()
        except Exception:
            _log.exception("error al avisar un cambio de la radio")

    def _fuente_actual(self) -> str | None:
        i = self._indice_actual()
        return self._estaciones[i].fuente if i is not None else None

    def _requerir_estaciones(self) -> None:
        if not self._estaciones:
            raise SinEstaciones("no hay estaciones")

    def _indice_actual(self) -> int | None:
        for i, e in enumerate(self._estaciones):
            if e.nombre == self._estado.estacion:
                return i
        return None

    def _buscar(self, nombre: str) -> Estacion:
        buscado = _normalizar(nombre)
        exactas = [e for e in self._estaciones if _normalizar(e.nombre) == buscado]
        if exactas:
            return exactas[0]
        prefijo = [e for e in self._estaciones if _normalizar(e.nombre).startswith(buscado)]
        if len(prefijo) == 1:
            return prefijo[0]
        motivo = "es ambigua" if prefijo else "no existe"
        raise EstacionInexistente(f"la estación {nombre!r} {motivo}")

    def _rotar(self, paso: int) -> None:
        with self._lock:
            self._requerir_estaciones()
            actual = self._indice_actual()
            if actual is None:
                destino = 0 if paso > 0 else len(self._estaciones) - 1
            else:
                destino = (actual + paso) % len(self._estaciones)
            self._sintonizar(self._estaciones[destino])

    def _sintonizar(self, estacion: Estacion) -> None:
        if self._estado.volumen == 0:
            self._estado.volumen = self._poner_volumen(VOLUMEN_MINIMO)
        plegada = plegar_vencidos(estacion, self._reloj())   # la lista que se manda empieza donde corresponde
        if plegada is not estacion:
            self._reemplazar(plegada)
            estacion = plegada
        anterior = self._estado.estacion
        self._estado.estacion = estacion.nombre
        self._primera_pista = True
        try:
            self._reproductor.sintonizar(estacion)
        except Exception:
            self._estado.estacion = anterior
            raise
        if self._router is not None:
            self._estado.monitor_local = self._prender_monitor()
        self._guardar(self._estado)
        self.encendida = True
        if self._dj is not None:
            self._dj.al_sintonizar(estacion.nombre)
        if self._planificador is not None:
            self._planificador.al_sintonizar(estacion)
        self._avisar_cambio()

    def _aplicar_monitor(self, activo: bool) -> None:
        if activo:
            self._router.enable_local_monitor()
        else:
            self._router.disable_local_monitor()

    def _prender_monitor(self) -> bool:
        """Prende el monitor (con volumen 0 parte de VOLUMEN_MINIMO); True si quedó prendido."""
        if self._estado.volumen == 0:
            self._estado.volumen = self._poner_volumen(VOLUMEN_MINIMO)
        try:
            self._router.enable_local_monitor()
        except AudioRouterError as e:
            _log.warning("no se pudo prender el monitor local: %s", e)
        return self._router.local_monitor_enabled

    def _escuchar(self) -> None:
        self._estado.monitor_local = self._prender_monitor()
        self._guardar(self._estado)
        self._avisar_cambio()

    def _poner_monitor(self, activo: bool) -> None:
        self._aplicar_monitor(activo)
        self._estado.monitor_local = activo
        self._guardar(self._estado)
        self._avisar_cambio()

    def _poner_volumen(self, valor: int) -> int:
        if self._router is None:
            valor = fuente = self._reproductor.volumen(valor)
        else:
            # el volumen de la radio es el del monitor local: la señal del bus (y la de otros oyentes) no cambia, así
            # que las fuentes y la voz quedan al 100 % (el ducking y la calibración siguen en ellas)
            valor, fuente = max(0, min(100, int(valor))), 100
            self._reproductor.volumen(fuente)
            try:
                self._router.set_local_volume(valor)
            except AudioRouterError as e:
                _log.warning("no se pudo ajustar el volumen del monitor local: %s", e)
        if self._dj is not None:
            self._dj.volumen(fuente)
        return valor

    def _apagar(self) -> None:
        self._reproductor.detener()
        self.encendida = False
        if self._dj is not None:
            self._dj.detener()
        if self._planificador is not None:
            self._planificador.al_apagar()
        self._avisar_cambio()

    def _al_cambiar_pista(self, pista, estacion) -> None:
        if self._avisar is not None and estacion is not None:
            self._avisar(estacion.nombre, pista.titulo)
        if self._dj is not None and estacion is not None:
            self._dj.pista_iniciada(pista, estacion.nombre)
            self._medir_desfase(pista, estacion)
        self._avisar_cambio()

    def _reemplazar(self, estacion: Estacion) -> None:
        """Con el lock tomado: la agenda de la emisora cambió (pedidos): se reemplaza y se guarda."""
        self._estaciones = [estacion if e.nombre == estacion.nombre else e for e in self._estaciones]
        if estacion.corrimiento or estacion.pedidos:
            self._estado.agendas[estacion.nombre] = agenda_de(estacion)
        else:
            self._estado.agendas.pop(estacion.nombre, None)
        self._guardar(self._estado)

    def _al_cambiar_agenda(self, estacion: Estacion, nuevo: Pedido | None) -> None:
        """El reproductor vio empezar un pedido (`nuevo`) o terminar los que había. Las pistas son de la radio (un
        rescan pudo cambiarlas mientras tanto); del reproductor se toman el corrimiento y los pedidos."""
        with self._lock:
            suya = next((e for e in self._estaciones if e.nombre == estacion.nombre), None)
            if suya is not None:
                estacion = replace(suya, corrimiento=estacion.corrimiento, pedidos=estacion.pedidos)
            self._reemplazar(estacion)
        if self._planificador is not None:      # fuera del lock, como al_rescan
            self._planificador.al_cambiar_agenda(estacion, nuevo)

    def _al_encolado(self, pista: Pista, estacion: Estacion, fin_actual: float) -> None:
        """Encolaron un tema que va a sonar cuando termine el actual (`fin_actual`, epoch)."""
        if self._planificador is not None:
            self._planificador.al_encolado(pista, estacion, fin_actual)

    def _al_desencolado(self, clave: str) -> None:
        """Sacaron de la cola de la app el tema encolado que iba a sonar."""
        if self._planificador is not None:
            self._planificador.al_desencolado(clave)

    def _medir_desfase(self, pista, estacion) -> None:
        with self._lock_dj:
            if self._primera_pista:
                self._primera_pista = False
                return
            valor = desfase(estacion, pista, self._reloj())
            self._desfase = valor
        umbral = self._configuracion_dj(estacion.nombre).desfase_aviso_segundos
        if valor is not None and abs(valor) > umbral:
            _log.warning("desfase de %.1f s entre la música real y el reloj en %r", valor, estacion.nombre)

    def dj_estado(self) -> dict:
        if self._dj is None:
            return {"activo": False, "hablando": False, "desfase_segundos": None, "intervenciones": [],
                    "planificador": None}
        ahora = self._reloj()
        return {
            "activo": True,
            "hablando": self._dj.hablando,
            "desfase_segundos": self._desfase,
            "intervenciones": [
                {"estacion": i.estacion, "inicio": i.inicio, "duracion": i.duracion, "texto": i.texto,
                 "en_segundos": round(i.inicio - ahora, 1)}
                for i in self._dj.vigentes()],
            "planificador": self._planificador.estado() if self._planificador is not None else None,
        }

    def dj_pedir(self, en_segundos: float = 20.0) -> dict:
        """Le pide una intervención de verdad al servicio DJ para el primer tema que arranque dentro de
        `en_segundos` o más, sin esperar a la frecuencia."""
        if self._planificador is None:
            raise DJInactivo("el DJ no está activo o no tiene la url del servicio")
        with self._lock:
            if not self.encendida or self._estado.estacion is None:
                raise RadioApagada("no hay una estación sintonizada")
        return self._planificador.pedir_ahora(en_segundos)

    def dj_modo(self, nuevo: str | None = None) -> dict:
        """Muestra o cambia cómo redacta el servicio DJ (plantillas | llm)."""
        if self._planificador is None:
            raise DJInactivo("el DJ no está activo o no tiene la url del servicio")
        return self._planificador.modo(nuevo)

    def dj_probar(self, audio: Path | None = None, en_segundos: float = 20.0) -> dict:
        """Registra una intervención de prueba en la próxima transición de la estación sintonizada."""
        if self._dj is None:
            raise DJInactivo("el DJ está apagado")
        with self._lock:
            estacion = next((e for e in self._estaciones if e.nombre == self._estado.estacion), None)
            if not self.encendida or estacion is None:
                raise RadioApagada("no hay una estación sintonizada")
            cfg = self._configuracion_dj(estacion.nombre)
            origen = Path(audio) if audio else None
            if origen is not None and not origen.is_file():
                raise ValueError(f"no existe el audio {origen}")
            self._dir_clips.mkdir(parents=True, exist_ok=True)
            clip = self._dir_clips / f"{uuid.uuid4().hex}{(origen.suffix if origen else '.wav')}"
            try:
                if origen is not None:
                    shutil.copyfile(origen, clip)
                else:
                    generar_clip_de_prueba(clip, 8.0)
                info = mutagen.File(clip)
                if info is None or not info.info.length:
                    raise ValueError(f"no se puede leer el audio {origen or clip}")
                duracion = float(info.info.length)
                if duracion > cfg.duracion_maxima_segundos:
                    raise ValueError(f"el clip dura {duracion:.1f} s y el máximo es "
                                     f"{cfg.duracion_maxima_segundos:g} s")
                ahora = self._reloj()
                for pista, inicio_tema in islice(transiciones(estacion, ahora), 20):
                    inicio = inicio_tema + cfg.retraso_voz_segundos
                    if inicio < ahora + en_segundos:
                        continue
                    try:
                        self._dj.registrar(Intervencion(uuid.uuid4().hex, estacion.nombre, inicio, duracion,
                                                        clip, "(clip de prueba)", pista.clave))
                    except ValueError:
                        continue     # ese hueco ya está ocupado
                    return {"estacion": estacion.nombre, "inicio": inicio, "duracion": duracion,
                            "pista_destino": pista.clave, "en_segundos": round(inicio - ahora, 1)}
                raise ValueError("no hay un hueco libre en las próximas transiciones")
            except BaseException:
                clip.unlink(missing_ok=True)
                raise

    def _al_fallar(self, estacion, motivo: str | None = None) -> None:
        with self._lock:
            # el aviso llega con la estación que falló: si el usuario ya cambió, no se la apaga
            if not (self.encendida and self._estado.estacion == estacion.nombre):
                return
            self._apagar()
        if motivo and self._avisar is not None:
            self._avisar(estacion.nombre, motivo)

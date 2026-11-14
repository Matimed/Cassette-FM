import logging
import shutil
import threading
import time
import unicodedata
import uuid
from collections.abc import Callable
from itertools import islice
from pathlib import Path

import mutagen

from cassette_fm.agenda import desfase, transiciones
from cassette_fm.biblioteca import Estacion
from cassette_fm.clips import generar_clip_de_prueba
from cassette_fm.config import ConfigDJ, Estado
from cassette_fm.intervenciones import Intervencion

_log = logging.getLogger("cassette_fm")


VOLUMEN_MINIMO = 10   # con el volumen en 0 la radio está apagada; al encender se parte de acá


def _normalizar(nombre: str) -> str:
    return unicodedata.normalize("NFC", nombre).casefold()


class EstacionInexistente(Exception):
    pass


class SinEstaciones(Exception):
    pass


class DJInactivo(Exception):
    """El DJ está apagado en la configuración."""


class RadioApagada(Exception):
    """No hay una estación sintonizada."""


class Radio:
    def __init__(self, reproductor, estaciones: list[Estacion], estado: Estado,
                 guardar: Callable[[Estado], None], escanear: Callable[[], list[Estacion]],
                 avisar: Callable[[str, str], None] | None = None, dj=None,
                 configuracion_dj: Callable[[str], ConfigDJ] | None = None, dir_clips: Path | None = None,
                 reloj: Callable[[], float] = time.time, planificador=None):
        self._dj = dj
        self._planificador = planificador
        self._configuracion_dj = configuracion_dj or (lambda nombre: ConfigDJ())
        self._dir_clips = Path(dir_clips) if dir_clips is not None else None
        self._reloj = reloj
        self._lock_dj = threading.Lock()
        self._primera_pista = False       # el primer tema tras sintonizar se empieza a mitad de camino
        self._desfase: float | None = None
        self._reproductor = reproductor
        self._estaciones = list(estaciones)
        self._estado = estado
        self._guardar = guardar
        self._escanear = escanear
        self._avisar = avisar
        self._lock = threading.RLock()
        self.encendida = False
        reproductor.al_cambiar_pista = self._al_cambiar_pista
        reproductor.al_fallar = self._al_fallar
        self._poner_volumen(estado.volumen)

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
            actual = self._indice_actual()
            self._sintonizar(self._estaciones[0 if actual is None else actual])

    def apagar(self) -> None:
        with self._lock:
            self._apagar()

    def alternar(self) -> None:
        with self._lock:
            if self.encendida:
                self._apagar()
            else:
                self.encender()

    def volumen(self, valor: int | None = None, delta: int | None = None) -> int:
        with self._lock:
            if valor is None and delta is None:
                return self._estado.volumen
            previo = self._estado.volumen
            nuevo = valor if valor is not None else previo + delta
            self._estado.volumen = self._poner_volumen(nuevo)
            self._guardar(self._estado)
            # volumen 0 = mutear = apagada; subir el volumen estando apagada enciende
            if self._estado.volumen == 0:
                if self.encendida:
                    self._apagar()
            elif not self.encendida and self._estado.volumen > previo:
                self.encender()
            return self._estado.volumen

    def rescan(self) -> None:
        nuevas = list(self._escanear())   # fuera del lock: puede tardar con bibliotecas grandes
        with self._lock:
            self._estaciones = nuevas
            if self.encendida and self._indice_actual() is None:
                if self._estaciones:
                    self._sintonizar(self._estaciones[0])
                else:
                    self._apagar()
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
            }

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
        anterior = self._estado.estacion
        self._estado.estacion = estacion.nombre
        self._primera_pista = True
        try:
            self._reproductor.sintonizar(estacion)
        except Exception:
            self._estado.estacion = anterior
            raise
        self._guardar(self._estado)
        self.encendida = True
        if self._dj is not None:
            self._dj.al_sintonizar(estacion.nombre)
        if self._planificador is not None:
            self._planificador.al_sintonizar(estacion)

    def _poner_volumen(self, valor: int) -> int:
        valor = self._reproductor.volumen(valor)
        if self._dj is not None:
            self._dj.volumen(valor)
        return valor

    def _apagar(self) -> None:
        self._reproductor.detener()
        self.encendida = False
        if self._dj is not None:
            self._dj.detener()
        if self._planificador is not None:
            self._planificador.al_apagar()

    def _al_cambiar_pista(self, pista, estacion) -> None:
        if self._avisar is not None and estacion is not None:
            self._avisar(estacion.nombre, pista.titulo)
        if self._dj is not None and estacion is not None:
            self._dj.pista_iniciada(pista, estacion.nombre)
            self._medir_desfase(pista, estacion)

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

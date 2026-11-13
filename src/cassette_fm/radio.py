import threading
import unicodedata
from collections.abc import Callable

from cassette_fm.biblioteca import Estacion
from cassette_fm.config import Estado


VOLUMEN_MINIMO = 10   # con el volumen en 0 la radio está apagada; al encender se parte de acá


def _normalizar(nombre: str) -> str:
    return unicodedata.normalize("NFC", nombre).casefold()


class EstacionInexistente(Exception):
    pass


class SinEstaciones(Exception):
    pass


class Radio:
    def __init__(self, reproductor, estaciones: list[Estacion], estado: Estado,
                 guardar: Callable[[Estado], None], escanear: Callable[[], list[Estacion]],
                 avisar: Callable[[str, str], None] | None = None):
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
        reproductor.volumen(estado.volumen)

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
            self._estado.volumen = self._reproductor.volumen(nuevo)
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
                "segundo": round(segundo, 1) if segundo is not None else None,
            }

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
            self._estado.volumen = self._reproductor.volumen(VOLUMEN_MINIMO)
        anterior = self._estado.estacion
        self._estado.estacion = estacion.nombre
        try:
            self._reproductor.sintonizar(estacion)
        except Exception:
            self._estado.estacion = anterior
            raise
        self._guardar(self._estado)
        self.encendida = True

    def _apagar(self) -> None:
        self._reproductor.detener()
        self.encendida = False

    def _al_cambiar_pista(self, pista, estacion) -> None:
        if self._avisar is not None and estacion is not None:
            self._avisar(estacion.nombre, pista.titulo)

    def _al_fallar(self) -> None:
        with self._lock:
            if self.encendida:
                self._apagar()

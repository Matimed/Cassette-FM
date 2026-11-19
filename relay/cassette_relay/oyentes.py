"""Los oyentes de cada calidad: una cola de bytes por oyente y la demanda que se le avisa a la PC.

Todo corre en el loop de asyncio del relay (sin hilos). Repartir un pedazo solo lo agrega a cada cola: nunca espera a
un oyente, así uno lento no frena la lectura del audio de la PC ni a los demás."""
import asyncio
import logging
from collections.abc import Callable

from .config import CALIDADES, MAESTRA

_log = logging.getLogger("cassette_relay.oyentes")


class Oyente:
    def __init__(self, kbps: int, tope: int, id: str = MAESTRA):
        self.kbps = kbps
        self.id = id                            # con qué clave entró (`MAESTRA` o el id de una clave de la PC)
        self.saltos = 0
        self.cerrado = False
        self._tope = tope
        self._datos = bytearray()
        self._hay = asyncio.Event()

    def _poner(self, datos: bytes) -> None:
        if self.cerrado:
            return
        if len(self._datos) + len(datos) > self._tope:
            self._datos.clear()                 # cola llena: un solo salto al vivo, no pedacitos sueltos
            self.saltos += 1
            _log.info("oyente de %d kbps atrasado: salta al vivo", self.kbps)
        self._datos += datos
        self._hay.set()

    async def tomar(self, timeout: float) -> bytes | None:
        """Todo lo encolado; None si no llegó nada en `timeout`; b"" si el oyente se cerró."""
        if not self._datos and not self.cerrado:
            try:
                await asyncio.wait_for(self._hay.wait(), timeout)
            except TimeoutError:
                return None
        if self.cerrado:
            return b""
        datos = bytes(self._datos)
        self._datos.clear()
        self._hay.clear()
        return datos

    def cerrar(self) -> None:
        self.cerrado = True
        self._datos.clear()
        self._hay.set()


class Oyentes:
    def __init__(self, al_cambiar_demanda: Callable[[list[int]], None], gracia: float = 10.0,
                 cola_segundos: float = 15.0):
        self._avisar = al_cambiar_demanda
        self._gracia = gracia
        self._cola_segundos = cola_segundos
        self._por_calidad: dict[int, list[Oyente]] = {k: [] for k in CALIDADES}
        self._en_gracia: dict[int, asyncio.TimerHandle] = {}
        self._avisado: list[int] = []

    def agregar(self, kbps: int, id: str = MAESTRA) -> Oyente:
        oyente = Oyente(kbps, int(self._cola_segundos * kbps * 1000 / 8), id)
        self._por_calidad[kbps].append(oyente)
        espera = self._en_gracia.pop(kbps, None)
        if espera is not None:
            espera.cancel()
        _log.info("entra un oyente de %d kbps (%d en esa calidad)", kbps, len(self._por_calidad[kbps]))
        self._revisar()
        return oyente

    def quitar(self, oyente: Oyente) -> None:
        lista = self._por_calidad[oyente.kbps]
        if oyente not in lista:
            return
        lista.remove(oyente)
        _log.info("sale un oyente de %d kbps (quedan %d)", oyente.kbps, len(lista))
        if not lista:
            loop = asyncio.get_running_loop()
            self._en_gracia[oyente.kbps] = loop.call_later(self._gracia, self._vencio, oyente.kbps)

    def cortar_fuera(self, vigentes: set[str]) -> int:
        """Cierra a los oyentes que entraron con una clave que ya no está (nunca a los de la maestra). Cada oyente
        cerrado termina su pedido y se saca solo de la cuenta."""
        cerrados = 0
        for lista in self._por_calidad.values():
            for oyente in list(lista):
                if oyente.id != MAESTRA and oyente.id not in vigentes and not oyente.cerrado:
                    oyente.cerrar()
                    cerrados += 1
        if cerrados:
            _log.info("se cortaron %d oyentes de claves que ya no valen", cerrados)
        return cerrados

    def _vencio(self, kbps: int) -> None:
        self._en_gracia.pop(kbps, None)
        self._revisar()

    def repartir(self, kbps: int, datos: bytes) -> None:
        for oyente in self._por_calidad.get(kbps, ()):
            oyente._poner(datos)

    def pedidas(self) -> list[int]:
        return [k for k in CALIDADES if self._por_calidad[k] or k in self._en_gracia]

    def cuantos(self, kbps: int) -> int:
        return len(self._por_calidad.get(kbps, ()))

    def _revisar(self) -> None:
        pedidas = self.pedidas()
        if pedidas != self._avisado:
            self._avisado = pedidas
            self._avisar(pedidas)

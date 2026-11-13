import hashlib
import math
import random
from collections.abc import Iterator

from cassette_fm.biblioteca import Estacion, Pista

# 2026-01-01T00:00:00Z
EPOCA: float = 1767225600.0


def _mezcla(base: list[Pista], nombre: str, k: int) -> list[Pista]:
    semilla = int.from_bytes(hashlib.sha256(f"{nombre}\x00{k}".encode()).digest()[:8], "big")
    lista = list(base)
    random.Random(semilla).shuffle(lista)
    return lista


def orden_ciclo(estacion: Estacion, k: int) -> list[Pista]:
    base = sorted(estacion.pistas, key=lambda p: str(p.ruta))
    if len(base) <= 2:
        return base
    orden = _mezcla(base, estacion.nombre, k)
    if orden[0] == _mezcla(base, estacion.nombre, k - 1)[-1]:
        # con len >= 3 el intercambio no toca el último: no hay cascada entre ciclos
        orden[0], orden[1] = orden[1], orden[0]
    return orden


def secuencia(estacion: Estacion, instante: float) -> Iterator[tuple[Pista, float]]:
    if not estacion.pistas:
        raise ValueError(f"la estación {estacion.nombre!r} no tiene pistas")
    ciclo = sum(p.duracion for p in estacion.pistas)
    t = instante - EPOCA
    k = math.floor(t / ciclo)
    resto = t - k * ciclo
    primera = True
    while True:
        for pista in orden_ciclo(estacion, k):
            if primera:
                if resto >= pista.duracion:
                    resto -= pista.duracion
                    continue
                primera = False
                yield pista, resto
            else:
                yield pista, 0.0
        if primera:
            # error de redondeo: el resto quedó en el borde del ciclo
            primera = False
            resto = 0.0
        k += 1

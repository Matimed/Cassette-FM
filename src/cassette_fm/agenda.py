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
    base = sorted(estacion.pistas, key=lambda p: p.clave)
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
    resto = max(0.0, t - k * ciclo)  # puede salir -ε por redondeo justo en un borde
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


def transiciones(estacion: Estacion, instante: float) -> Iterator[tuple[Pista, float]]:
    """(tema que empieza, epoch de su inicio) para todos los temas posteriores a `instante`, en orden."""
    siguientes = secuencia(estacion, instante)
    actual, desde = next(siguientes)
    inicio = instante + (actual.duracion - desde)
    for pista, _ in siguientes:
        yield pista, inicio
        inicio += pista.duracion


def desfase(estacion: Estacion, pista: Pista, instante: float) -> float | None:
    """Cuánto se aparta la música real del reloj cuando `pista` acaba de empezar a sonar.

    > 0: la agenda ya contó esos segundos de `pista` (la música real va atrasada);
    < 0: la agenda todavía está en el tema anterior y `pista` empieza en |valor| s (la real va adelantada);
    None: `pista` no es ni el tema actual ni el siguiente de la agenda.
    """
    it = secuencia(estacion, instante)
    actual, desde = next(it)
    siguiente, _ = next(it)
    candidatos = []
    if actual == pista:
        candidatos.append(desde)
    if siguiente == pista:
        candidatos.append(-(actual.duracion - desde))
    return min(candidatos, key=abs) if candidatos else None

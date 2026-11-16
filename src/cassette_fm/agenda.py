import hashlib
import math
import random
from collections.abc import Iterator
from dataclasses import replace

from cassette_fm.biblioteca import Estacion, Pedido, Pista

# 2026-01-01T00:00:00Z
EPOCA: float = 1767225600.0
# lo que un pedido puede durar de más al plegarlo: Spotify tarda en cargar el tema siguiente (o en saltar a la posición
# al retomarlo); más que esto es una pausa, y la radio sigue siendo un reloj
HOLGURA_PEDIDO_SEGUNDOS: float = 15.0


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
    """(tema, segundo desde el que suena) en `instante`, y después los que siguen (desde 0), sin fin.

    Con pedidos: durante un pedido suena el pedido; mientras tanto la agenda "se detiene" y después sigue donde
    estaba. El corrimiento atrasa la agenda lo que ya duraron los pedidos plegados."""
    if not estacion.pedidos:
        return _base(estacion, instante - estacion.corrimiento)
    return _con_pedidos(estacion, instante)


def _duracion(p: Pedido) -> float:
    return p.pista.duracion


def _con_pedidos(estacion: Estacion, instante: float) -> Iterator[tuple[Pista, float]]:
    linea = _linea(estacion, instante)
    pista, inicio = next(linea)
    for siguiente, inicio_sig in linea:
        if inicio_sig > instante:
            break
        pista, inicio = siguiente, inicio_sig
    else:                                  # la línea es infinita: no se llega acá
        return
    yield pista, max(0.0, instante - inicio)
    yield siguiente, 0.0
    for p, _ in linea:
        yield p, 0.0


def _linea(estacion: Estacion, instante: float) -> Iterator[tuple[Pista, float]]:
    """La línea de tiempo real: (tema, epoch en que empieza), desde el tema que suena en `instante` o un poco antes.

    Cada tema termina cuando empieza el siguiente. Un pedido se mete antes del tema de la agenda que empezaría
    pasada menos de la mitad de ese tema desde el inicio del pedido (en la práctica empiezan en un borde)."""
    pedidos = sorted(estacion.pedidos, key=lambda p: p.inicio)
    dentro = next((p for p in pedidos if p.inicio <= instante < p.inicio + _duracion(p)), None)
    desde = dentro.inicio if dentro is not None else instante
    pasados = sum(_duracion(p) for p in pedidos if p.inicio + _duracion(p) <= desde)
    pendientes = [p for p in pedidos if p.inicio + _duracion(p) > desde]
    base = _base(estacion, desde - estacion.corrimiento - pasados)
    primera, d0 = next(base)
    cursor = desde - d0

    def agenda():
        yield primera
        for p, _ in base:
            yield p

    for pista in agenda():
        while pendientes and pendientes[0].inicio <= cursor + pista.duracion / 2:
            p = pendientes.pop(0)
            yield p.pista, p.inicio
            cursor = p.inicio + _duracion(p)
        yield pista, cursor
        cursor += pista.duracion


def corrimiento_total(estacion: Estacion) -> float:
    """El atraso total de la agenda contando los pedidos en curso por su duración nominal."""
    return estacion.corrimiento + sum(_duracion(p) for p in estacion.pedidos)


def con_pedido(estacion: Estacion, pista: Pista, inicio: float) -> Estacion:
    """Empezó un pedido en `inicio`: los que empezaron antes terminaron (se pliegan con lo que sonaron)."""
    plegada = plegar(estacion, inicio)
    return replace(plegada, pedidos=plegada.pedidos + (Pedido(pista, inicio),))


def plegar(estacion: Estacion, hasta: float) -> Estacion:
    """En `hasta` empezó otra cosa: los pedidos que empezaron antes se pliegan al corrimiento con su duración real
    (hasta que empezó lo siguiente), con tope en la nominal más la holgura."""
    pedidos = sorted(estacion.pedidos, key=lambda p: p.inicio)
    viejos = [p for p in pedidos if p.inicio < hasta]
    if not viejos:
        return estacion
    fines = [q.inicio for q in viejos[1:]] + [hasta]
    real = sum(max(0.0, min(_duracion(p) + HOLGURA_PEDIDO_SEGUNDOS, fin - p.inicio))
               for p, fin in zip(viejos, fines))
    return replace(estacion, corrimiento=estacion.corrimiento + real,
                   pedidos=tuple(p for p in pedidos if p.inicio >= hasta))


def plegar_vencidos(estacion: Estacion, ahora: float) -> Estacion:
    """Los pedidos que ya terminaron por la agenda (sin que se viera el tema siguiente) se pliegan con su duración
    nominal: la agenda da lo mismo que antes, pero la lista queda corta."""
    vencidos = [p for p in estacion.pedidos if p.inicio + _duracion(p) <= ahora]
    if not vencidos:
        return estacion
    return replace(estacion, corrimiento=estacion.corrimiento + sum(_duracion(p) for p in vencidos),
                   pedidos=tuple(p for p in estacion.pedidos if p not in vencidos))


def _base(estacion: Estacion, instante: float) -> Iterator[tuple[Pista, float]]:
    """La agenda determinista sin pedidos ni corrimiento."""
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

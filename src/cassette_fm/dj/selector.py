import random
from collections.abc import Collection, Mapping, Sequence


def elegir_ingredientes(disponibles: Collection[str], pesos: Mapping[str, float], recientes: Sequence[str],
                        azar: random.Random, maximo: int = 3, penalizacion: float = 0.3) -> tuple[str, ...]:
    """Qué ingredientes lleva la frase: siempre "cancion" y, con probabilidad `peso * penalizacion ** veces`
    (veces = cuántas aparece en `recientes`), cada uno de los demás; si se ofrecen más que los lugares que quedan
    (`maximo - 1`), se priorizan al azar ponderado por esa misma probabilidad."""
    ofrecidos: list[tuple[str, float]] = []
    for nombre in sorted(set(disponibles) - {"cancion"}):
        p = pesos.get(nombre, 0.0) * penalizacion ** recientes.count(nombre)
        if p > 0 and azar.random() < p:
            ofrecidos.append((nombre, p))
    # muestreo ponderado sin reposición (Efraimidis-Spirakis): clave = u ** (1 / p), de mayor a menor
    ofrecidos.sort(key=lambda x: azar.random() ** (1.0 / x[1]), reverse=True)
    return ("cancion", *(n for n, _ in ofrecidos[:max(0, maximo - 1)]))

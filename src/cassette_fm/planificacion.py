import random
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from cassette_fm.agenda import secuencia, transiciones
from cassette_fm.biblioteca import Estacion, Pista
from cassette_fm.config import ConfigDJ

MAX_CANDIDATAS = 200          # cuántas transiciones se evalúan como máximo
_TOPE_ITERACIONES = 100_000   # corta la búsqueda si la última intervención quedó muy atrás


@dataclass(frozen=True)
class Ultima:
    """La última intervención de una estación."""
    inicio_tema: float   # epoch en que arrancó el tema destino
    fin: float           # epoch en que terminó la voz


@dataclass(frozen=True)
class Hueco:
    pista: Pista                 # el tema destino: arranca justo antes de la voz
    inicio_tema: float
    inicio_voz: float            # inicio_tema + retraso_voz_segundos
    anterior: Pista | None       # el tema que sonaba justo antes


def _tiene_nombre(pista: Pista) -> bool:
    return bool(pista.artista and pista.cancion)


def elegir_hueco(estacion: Estacion, ahora: float, cfg: ConfigDJ, ultima: Ultima | None,
                 azar: random.Random, ocupados: Sequence[tuple[float, float]] = ()) -> Hueco | None:
    """El tema destino de la próxima intervención, según la frecuencia de `cfg` (ver el plan 2b, Task 4)."""
    minimo = ahora + cfg.margen_minutos * 60
    f = cfg.frecuencia
    if f.modo == "minutos":
        objetivo = (ultima.fin if ultima else ahora) + azar.uniform(f.min, f.max) * 60
        piso, k, primera = max(objetivo, minimo), 0, 1
        serie = transiciones(estacion, ahora)
    else:
        k = azar.randint(int(f.min), int(f.max))
        piso = minimo
        # si la última quedó tan atrás que la k-ésima transición desde ella ya pasó, contarla no sirve: se
        # cuenta desde ahora (y no se recorren miles de transiciones viejas)
        mas_larga = max(p.duracion for p in estacion.pistas)
        if ultima and ahora - ultima.inicio_tema <= (k + 1) * mas_larga:
            serie, primera = transiciones(estacion, ultima.inicio_tema - 0.001), 0
        else:
            serie, primera = transiciones(estacion, ahora), 1
    evaluadas = 0
    for i, (pista, inicio) in enumerate(serie):
        if i >= _TOPE_ITERACIONES or evaluadas >= MAX_CANDIDATAS:
            break
        if primera + i < k or inicio < piso or inicio <= ahora:
            continue
        evaluadas += 1
        inicio_voz = inicio + cfg.retraso_voz_segundos
        fin_voz = inicio_voz + cfg.duracion_maxima_segundos
        if not _tiene_nombre(pista) or any(inicio_voz < b and a < fin_voz for a, b in ocupados):
            continue
        anterior = next(secuencia(estacion, inicio - 0.001))[0]
        return Hueco(pista, inicio, inicio_voz, anterior)
    return None


def armar_pedido(id: str, estacion: str, hueco: Hueco, cfg: ConfigDJ, recientes: Sequence[str]) -> dict:
    """El cuerpo del `POST /intervenciones` del servicio DJ."""
    siguiente = {"artista": hueco.pista.artista, "titulo": hueco.pista.cancion}
    if hueco.pista.album:
        siguiente["album"] = hueco.pista.album
    if hueco.pista.isrc:
        siguiente["isrc"] = hueco.pista.isrc
    pedido = {
        "id": id, "estacion": estacion, "idioma": cfg.idioma, "voz": cfg.voz,
        "momento": datetime.fromtimestamp(hueco.inicio_voz).astimezone().isoformat(timespec="seconds"),
        "siguiente": siguiente, "recientes": list(recientes),
        "duracion_maxima_segundos": cfg.duracion_maxima_segundos,
    }
    if cfg.personalidad:
        pedido["personalidad"] = cfg.personalidad
    anterior = hueco.anterior
    if anterior is not None and _tiene_nombre(anterior):
        pedido["anterior"] = {"artista": anterior.artista, "titulo": anterior.cancion}
    return pedido

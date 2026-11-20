import random
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from cassette_fm.agenda import secuencia, transiciones
from cassette_fm.biblioteca import Estacion, Pista
from cassette_fm.config import ConfigDJ
from cassette_fm.posiciones import POSICIONES

MAX_CANDIDATAS = 200          # cuántas transiciones se evalúan como máximo
_TOPE_ITERACIONES = 100_000   # corta la búsqueda si la última intervención quedó muy atrás


@dataclass(frozen=True)
class Ultima:
    """La última intervención de una estación."""
    inicio_tema: float   # epoch en que arrancó el tema destino
    fin: float           # epoch en que terminó la voz


@dataclass(frozen=True)
class Hueco:
    pista: Pista                 # el tema destino: arranca en el corte
    inicio_tema: float           # el CORTE: cuándo termina el origen y empieza el destino
    inicio_voz: float            # instante nominal de la voz: inicio_tema + retraso_voz_segundos (el real depende de
                                 # la posición y del largo del clip: ver `inicio_de_la_voz`)
    anterior: Pista | None       # el tema que sonaba justo antes
    posicion: str = "inicio"     # dónde cae la voz respecto del corte: inicio | entre | final
    origen: Pista | None = None  # el tema que termina en el corte (igual a `anterior`, pero sin pasar por el nombre)


def _tiene_nombre(pista: Pista) -> bool:
    return bool(pista.artista and pista.cancion)


def sortear_posicion(cfg: ConfigDJ, azar: random.Random, margen_disponible: float | None = None) -> str:
    """La posición de la voz para una intervención: la de `cfg.posicion_voz` o, con "mixto", una de las tres al
    azar. Con `margen_disponible` (segundos hasta el corte) menor que lo que hace falta para generar el clip
    (`peticion_margen_segundos` + `duracion_maxima_segundos`), una voz que empieza antes del corte no llega: "inicio"."""
    posicion = azar.choice(POSICIONES) if cfg.posicion_voz == "mixto" else cfg.posicion_voz
    if (posicion != "inicio" and margen_disponible is not None
            and margen_disponible < cfg.peticion_margen_segundos + cfg.duracion_maxima_segundos):
        return "inicio"
    return posicion


def inicio_de_la_voz(posicion: str, corte: float, duracion: float, cfg: ConfigDJ, azar: random.Random,
                     duracion_origen: float | None = None) -> float:
    """Epoch en que empieza la voz de un clip de `duracion` segundos para un corte en `corte`. "inicio": después del
    corte; "entre": una fracción del clip (`fraccion_entre_*`) suena antes del corte; "final": el clip termina
    `final_antes_*_segundos` antes del corte. Con `duracion_origen`, no empieza antes de la mitad del tema de origen."""
    if posicion == "inicio":
        return corte + cfg.retraso_voz_segundos
    if posicion == "entre":
        inicio = corte - azar.uniform(cfg.fraccion_entre_min, cfg.fraccion_entre_max) * duracion
    else:
        inicio = corte - azar.uniform(cfg.final_antes_min_segundos, cfg.final_antes_max_segundos) - duracion
    if duracion_origen is not None:
        inicio = max(inicio, corte - duracion_origen / 2)
    return inicio


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
        # todavía no se sabe cuánto dura el clip ni dónde cae: la voz puede empezar hasta `duracion_maxima` antes
        # del corte y terminar `retraso + duracion_maxima` después
        desde_voz, fin_voz = inicio - cfg.duracion_maxima_segundos, inicio_voz + cfg.duracion_maxima_segundos
        if not _tiene_nombre(pista) or any(desde_voz < b and a < fin_voz for a, b in ocupados):
            continue
        anterior = next(secuencia(estacion, inicio - 0.001))[0]
        return Hueco(pista, inicio, inicio_voz, anterior, sortear_posicion(cfg, azar), anterior)
    return None


def armar_pedido(id: str, estacion: str, hueco: Hueco, cfg: ConfigDJ, recientes: Sequence[str],
                 peticion: str | None = None) -> dict:
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
        "posicion": hueco.posicion,
    }
    if cfg.velocidad is not None:
        pedido["velocidad"] = cfg.velocidad
    if cfg.personalidad:
        pedido["personalidad"] = cfg.personalidad
    if peticion is not None:
        pedido["peticion"] = peticion
    anterior = hueco.anterior
    if anterior is not None and _tiene_nombre(anterior):
        pedido["anterior"] = {"artista": anterior.artista, "titulo": anterior.cancion}
    return pedido

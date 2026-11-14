"""Frases de plantilla del DJ (respaldo y primera versión del contenido). Solo usan datos del pedido y el reloj."""
import random
import re
from dataclasses import dataclass
from datetime import datetime, tzinfo

from cassette_fm.dj.lexico import Lexico
from cassette_fm.dj.pedido import Pedido
from cassette_fm.dj.texto_voz import marcar

_MARCA = re.compile(r"\{([A-Za-z-]+):([^{}]*)\}")

_HORAS_ES = ["doce", "una", "dos", "tres", "cuatro", "cinco", "seis", "siete", "ocho", "nueve", "diez", "once"]
_HORAS_EN = ["twelve", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven"]
_MIN_ES = {5: "y cinco", 10: "y diez", 15: "y cuarto", 20: "y veinte", 25: "y veinticinco", 30: "y media",
           35: "menos veinticinco", 40: "menos veinte", 45: "menos cuarto", 50: "menos diez", 55: "menos cinco"}
_MIN_EN = {5: "five past", 10: "ten past", 15: "quarter past", 20: "twenty past", 25: "twenty five past",
           30: "half past", 35: "twenty five to", 40: "twenty to", 45: "quarter to", 50: "ten to", 55: "five to"}


@dataclass(frozen=True)
class Redaccion:
    marcado: str                       # frase con marcas {lang:Nombre} en los nombres propios
    ingredientes: tuple[str, ...]


@dataclass(frozen=True)
class _Plantilla:
    texto: str
    ingredientes: tuple[str, ...]
    requiere: frozenset[str] = frozenset()      # datos opcionales del pedido: "album", "anterior"


def _p(texto, ingredientes, requiere=()):
    return _Plantilla(texto, tuple(ingredientes), frozenset(requiere))


_ES = [
    _p("Seguimos con {artista} y su tema {titulo} para acompañar este momento de la mejor manera.", ["cancion"]),
    _p("Esto es {estacion} y ahora te dejamos con {artista} cantando {titulo} para vos.", ["cancion", "estacion"]),
    _p("{son} {hora} y suena {titulo} de {artista} para que sigas disfrutando de la música.", ["cancion", "hora"]),
    _p("Seguimos {este_momento} con {titulo} de la mano de {artista} para todos los que nos escuchan.",
       ["cancion", "momento"]),
    _p("Terminamos con {artista_ant} y {titulo_ant} y seguimos ahora con {artista} y su tema {titulo}.",
       ["cancion", "anterior"], ["anterior"]),
    _p("En {estacion} {son_min} {hora} y toca el turno de {artista} con {titulo} sin cortes.",
       ["cancion", "estacion", "hora"]),
    _p("De su disco {album} escuchamos ahora {titulo} de {artista} acá en la radio de siempre.",
       ["cancion", "album"], ["album"]),
    _p("Estamos en {estacion} {este_momento} y ahora suena {titulo} de {artista} para todos nosotros.",
       ["cancion", "estacion", "momento"]),
    _p("{son} {hora} y después de {artista_ant} llega {artista} con su tema {titulo} para seguir.",
       ["cancion", "hora", "anterior"], ["anterior"]),
]

_EN = [
    _p("Coming up next we have {artista} with {titulo} to keep you company right here.", ["cancion"]),
    _p("You are listening to {estacion} and now it is time for {titulo} by {artista} for you.",
       ["cancion", "estacion"]),
    _p("It is {hora} and here is {titulo} from {artista} to keep the music going right here.",
       ["cancion", "hora"]),
    _p("Let us spend {este_momento} together with {titulo} from {artista} for everyone listening.",
       ["cancion", "momento"]),
    _p("We just heard {artista_ant} with {titulo_ant} and now we continue with {artista} and {titulo}.",
       ["cancion", "anterior"], ["anterior"]),
    _p("On {estacion} it is {hora} and {artista} takes the stage with {titulo} for all of you.",
       ["cancion", "estacion", "hora"]),
    _p("From the album {album} here is {titulo} by {artista} for everybody out there right now.",
       ["cancion", "album"], ["album"]),
    _p("Staying on {estacion} {este_momento} with {titulo} by {artista} for everybody out there.",
       ["cancion", "estacion", "momento"]),
    _p("It is {hora} and after {artista_ant} comes {artista} with their song {titulo} for you.",
       ["cancion", "hora", "anterior"], ["anterior"]),
]


def frase_hora(momento: datetime, idioma: str) -> str:
    total = (momento.hour * 60 + momento.minute + 2) // 5 * 5      # al múltiplo de 5 más cercano
    h, m = divmod(total % (24 * 60), 60)
    siguiente = (h + 1) % 24
    if idioma == "es":
        def articulo_hora(hh):
            h12 = hh % 12
            return ("la " if h12 == 1 else "las ") + _HORAS_ES[h12]
        if m == 0:
            return f"{articulo_hora(h)} en punto"
        if m <= 30:
            return f"{articulo_hora(h)} {_MIN_ES[m]}"
        resto = _MIN_ES[m].removeprefix("menos ")
        return f"{articulo_hora(siguiente)} menos {resto}"
    if m == 0:
        return f"{_HORAS_EN[h % 12]} o'clock"
    return f"{_MIN_EN[m]} {_HORAS_EN[(h if m <= 30 else siguiente) % 12]}"


def _este_momento(momento: datetime, es: bool) -> str:
    h = momento.hour
    if es:
        return "esta mañana" if 5 <= h < 12 else "esta tarde" if 12 <= h < 20 else "esta noche"
    return ("this morning" if 5 <= h < 12 else "this afternoon" if 12 <= h < 18
            else "this evening" if 18 <= h < 21 else "tonight")


def _palabras(marcado: str) -> int:
    return len(_MARCA.sub(lambda m: m.group(2), marcado).split())


def redactar(pedido: Pedido, lexico: Lexico, azar: random.Random, palabras_maximas: int,
             zona: tzinfo | None = None) -> Redaccion:
    es = pedido.idioma == "es"
    momento = pedido.momento.astimezone(zona) if zona is not None else pedido.momento
    lang = pedido.lang
    disponibles = set()
    if pedido.siguiente.album:
        disponibles.add("album")
    if pedido.anterior is not None:
        disponibles.add("anterior")
    elegibles = [t for t in (_ES if es else _EN) if t.requiere <= disponibles]

    def m(nombre: str) -> str:
        return marcar(lexico.pronunciacion(nombre), lexico.idioma_de(nombre, lang))

    hora = frase_hora(momento, "es" if es else "en")
    campos = {
        "artista": m(pedido.siguiente.artista), "titulo": m(pedido.siguiente.titulo), "estacion": m(pedido.estacion),
        "hora": hora, "son": "Es" if hora.startswith("la ") else "Son",
        "son_min": "es" if hora.startswith("la ") else "son",
        "este_momento": _este_momento(momento, es),
    }
    if pedido.siguiente.album:
        campos["album"] = m(pedido.siguiente.album)
    if pedido.anterior is not None:
        campos["artista_ant"] = m(pedido.anterior.artista)
        campos["titulo_ant"] = m(pedido.anterior.titulo)

    def armar(t: _Plantilla) -> Redaccion:
        return Redaccion(t.texto.format(**campos), t.ingredientes)

    for _ in range(10):
        r = armar(azar.choice(elegibles))
        if _palabras(r.marcado) <= palabras_maximas:
            return r
    return min((armar(t) for t in elegibles), key=lambda r: _palabras(r.marcado))

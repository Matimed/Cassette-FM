"""Frases de plantilla del DJ (respaldo y primera versión del contenido). Solo usan datos del pedido y el reloj."""
import random
import re
from dataclasses import dataclass
from datetime import datetime, tzinfo

from collections.abc import Mapping, Sequence

from cassette_fm.dj.config import PESOS_POR_DEFECTO
from cassette_fm.dj.hechos import Hechos
from cassette_fm.dj.hechos.numeros import anio_en_palabras, en_palabras
from cassette_fm.dj.hechos.paises import nombre_de_pais
from cassette_fm.dj.lexico import Lexico
from cassette_fm.dj.pedido import Pedido
from cassette_fm.dj.selector import elegir_ingredientes
from cassette_fm.dj.texto_voz import marcar

_MARCA = re.compile(r"\{([A-Za-z-]+):([^{}]*)\}")

_HORAS_ES = ["doce", "una", "dos", "tres", "cuatro", "cinco", "seis", "siete", "ocho", "nueve", "diez", "once"]
_HORAS_EN = ["twelve", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven"]
_MIN_ES = {5: "y cinco", 10: "y diez", 15: "y cuarto", 20: "y veinte", 25: "y veinticinco", 30: "y media",
           35: "menos veinticinco", 40: "menos veinte", 45: "menos cuarto", 50: "menos diez", 55: "menos cinco"}
_MIN_EN = {5: "five past", 10: "ten past", 15: "quarter past", 20: "twenty past", 25: "twenty five past",
           30: "half past", 35: "twenty five to", 40: "twenty to", 45: "quarter to", 50: "ten to", 55: "five to"}


_DIAS_ES = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
_DIAS_EN = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

# La frase = extras de apertura + marco (tema y artista) + extras de cierre. Cada oración tiene al menos cuatro
# palabras aunque el nombre propio sea una sola (si no, el texto para voz la une con la vecina).
_MARCOS = {
    "es": ["Seguimos con {artista} y su tema {titulo} para acompañar este momento de la mejor manera.",
           "Ahora suena {titulo} de {artista} para todos ustedes.",
           "Con ustedes {artista} y su tema {titulo} sin interrupciones.",
           "Sigue {artista} con {titulo} para que no pares.",
           "Llega {titulo} de {artista} para vos."],
    "en": ["Coming up next we have {artista} with {titulo} to keep you company.",
           "Now playing {titulo} by {artista} for everybody out there.",
           "Here comes {artista} with {titulo} right on time.",
           "Stay with us for {titulo} from {artista} right now."],
}
_EXTRAS = {
    "es": {
        "hora": ["{son} {hora} y seguimos con vos.", "{son} {hora} para que lo sepas.", "{son} {hora} en la radio."],
        "estacion": ["Estás escuchando {estacion} en vivo.", "Esto es {estacion} tu radio de siempre.",
                     "Acá en {estacion} seguimos con vos.", "Bienvenidos a {estacion} la radio que no para."],
        "hora+estacion": ["En {estacion} {son_min} {hora} para vos.", "{son} {hora} acá en {estacion} con ustedes."],
        "momento": ["Seguimos {este_momento} juntos.", "Pasamos {este_momento} con la mejor música.",
                    "Qué lindo pasar {este_momento} con ustedes.", "Compartimos {este_dia} con todos ustedes.",
                    "Para disfrutar {este_dia} con buena música."],
        "anterior": ["Veníamos de {artista_ant} con {titulo_ant}.", "Recién sonó {artista_ant} con {titulo_ant}."],
        "album": ["Del disco {album} para ustedes.", "Del álbum {album} de su discografía."],
    },
    "en": {
        "hora": ["It is {hora} and we keep going.", "It is {hora} right here with you.",
                 "The time is {hora} on the dial."],
        "estacion": ["You are listening to {estacion} right now.", "This is {estacion} the station that never stops.",
                     "Right here on {estacion} with all of you.", "Welcome to {estacion} where the music never stops."],
        "hora+estacion": ["On {estacion} it is {hora} right now.", "It is {hora} here on {estacion} with you."],
        "momento": ["Let us spend {este_momento} together.", "We share {este_momento} with all of you.",
                    "Nothing beats {este_momento} with good music.", "Enjoy {este_dia} with great music.",
                    "Let us make {este_dia} sound good."],
        "anterior": ["We just heard {artista_ant} with {titulo_ant}.", "That was {artista_ant} with {titulo_ant}."],
        "album": ["From the album {album} for you.", "Taken from the album {album} for everybody."],
    },
}
_CLIMA = {
    "es": ["Afuera hay {grados} y {cielo}.", "Ahora mismo en Buenos Aires hay {grados}.",
           "Con {grados} afuera seguimos acá."],
    "en": ["It is {grados} outside and {cielo}.", "Right now in Buenos Aires it is {grados}.",
           "With {grados} outside we keep going."],
}
_CIELO = {
    "es": {"despejado": "el cielo está despejado", "nublado": "está nublado", "lluvia": "está lloviendo",
           "tormenta": "hay tormenta", "niebla": "hay niebla", "nieve": "está nevando"},
    "en": {"despejado": "the sky is clear", "nublado": "it is cloudy", "lluvia": "it is raining",
           "tormenta": "there is a storm", "niebla": "it is foggy", "nieve": "it is snowing"},
}
_NOCHE_DESPEJADA = {"es": "la noche está despejada", "en": "the night is clear"}
# (campos que necesita, texto)
_DATO = {
    "es": [("anio", "Este tema salió en {anio}."), ("anio", "{titulo} es de {anio}."),
           ("pais", "{artista} viene de {pais}."), ("inicio", "{artista} es una banda que empezó en {inicio}.")],
    "en": [("anio", "This one came out in {anio}."), ("anio", "{titulo} dates from {anio}."),
           ("pais", "{artista} comes from {pais}."), ("inicio", "{artista} is a band that started in {inicio}.")],
}
_DESCARTE = ("dato", "clima", "anterior", "album")        # lo primero que se saca si la frase no entra
_APERTURA = ("hora", "estacion", "momento", "clima", "anterior")
_CIERRE = ("album", "dato")


@dataclass(frozen=True)
class Redaccion:
    marcado: str                       # frase con marcas {lang:Nombre} en los nombres propios
    ingredientes: tuple[str, ...]


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
        return ("esta madrugada" if h < 5 else "esta mañana" if h < 12 else "esta tarde" if h < 20
                else "esta noche")
    return ("this morning" if 5 <= h < 12 else "this afternoon" if 12 <= h < 18
            else "this evening" if 18 <= h < 21 else "tonight")


def _palabras(marcado: str) -> int:
    return len(_MARCA.sub(lambda m: m.group(2), marcado).split())


def _grados(temperatura: int, idioma: str) -> str:
    """La temperatura en palabras con su unidad ("veintidós grados", "menos un grado", "one degree")."""
    n = abs(temperatura)
    if n == 1:
        cuerpo = "un grado" if idioma == "es" else "one degree"
        return (f"menos {cuerpo}" if idioma == "es" else f"minus {cuerpo}") if temperatura < 0 else cuerpo
    return f"{en_palabras(temperatura, idioma)} {'grados' if idioma == 'es' else 'degrees'}"


def _variantes_de_dato(hechos: Hechos, idioma: str) -> list[str]:
    """Las frases de dato que se pueden decir con lo verificado (cada una exige sus campos)."""
    t = hechos.tema
    if t is None:
        return []
    tiene = {"anio": t.anio is not None and 1900 <= t.anio <= 2099,
             "pais": t.pais is not None and nombre_de_pais(t.pais, idioma) is not None,
             "inicio": t.es_grupo and t.anio_inicio_artista is not None and 1900 <= t.anio_inicio_artista <= 2099}
    return [texto for campo, texto in _DATO[idioma] if tiene[campo]]


def ingredientes_disponibles(pedido: Pedido, hechos: Hechos = Hechos()) -> set[str]:
    """Qué ingredientes se pueden usar para este pedido con lo que hay (y lo verificado)."""
    disponibles = {"cancion", "estacion", "hora", "momento"}
    if pedido.siguiente.album:
        disponibles.add("album")
    if pedido.anterior is not None:
        disponibles.add("anterior")
    if hechos.clima is not None:
        disponibles.add("clima")
    idioma = "es" if pedido.idioma == "es" else "en"
    if _variantes_de_dato(hechos, idioma):
        disponibles.add("dato")
    return disponibles


def redactar(pedido: Pedido, lexico: Lexico, azar: random.Random, palabras_maximas: int,
             zona: tzinfo | None = None, hechos: Hechos = Hechos(),
             pesos: Mapping[str, float] = PESOS_POR_DEFECTO, maximo: int = 3,
             penalizacion: float = 0.3) -> Redaccion:
    idioma = "es" if pedido.idioma == "es" else "en"
    es = idioma == "es"
    momento = pedido.momento.astimezone(zona) if zona is not None else pedido.momento
    lang = pedido.lang

    def m(nombre: str) -> str:
        return marcar(lexico.pronunciacion(nombre), lexico.idioma_de(nombre, lang))

    hora = frase_hora(momento, idioma)
    dia = _DIAS_ES[momento.weekday()] if es else _DIAS_EN[momento.weekday()]
    campos = {
        "artista": m(pedido.siguiente.artista), "titulo": m(pedido.siguiente.titulo), "estacion": m(pedido.estacion),
        "hora": hora, "son": "Es" if hora.startswith("la ") else "Son",
        "son_min": "es" if hora.startswith("la ") else "son",
        "este_momento": _este_momento(momento, es), "este_dia": f"este {dia}" if es else f"this {dia}",
    }
    if pedido.siguiente.album:
        campos["album"] = m(pedido.siguiente.album)
    if pedido.anterior is not None:
        campos["artista_ant"] = m(pedido.anterior.artista)
        campos["titulo_ant"] = m(pedido.anterior.titulo)
    if hechos.clima is not None:
        c = hechos.clima
        cielo = (_NOCHE_DESPEJADA[idioma] if not c.es_de_dia and c.cielo == "despejado" else _CIELO[idioma][c.cielo])
        campos["grados"] = _grados(c.temperatura, idioma)
        campos["cielo"] = cielo
    if hechos.tema is not None:
        t = hechos.tema
        if t.anio is not None and 1900 <= t.anio <= 2099:
            campos["anio"] = anio_en_palabras(t.anio, idioma)
        if t.pais is not None and nombre_de_pais(t.pais, idioma):
            campos["pais"] = nombre_de_pais(t.pais, idioma)
        if t.anio_inicio_artista is not None and 1900 <= t.anio_inicio_artista <= 2099:
            campos["inicio"] = anio_en_palabras(t.anio_inicio_artista, idioma)

    elegidos = elegir_ingredientes(ingredientes_disponibles(pedido, hechos), pesos, pedido.recientes, azar,
                                   maximo, penalizacion)

    def extra(ingrediente: str) -> str:
        if ingrediente == "clima":
            return azar.choice(_CLIMA[idioma]).format(**campos)
        if ingrediente == "dato":
            return azar.choice(_variantes_de_dato(hechos, idioma)).format(**campos)
        return azar.choice(_EXTRAS[idioma][ingrediente]).format(**campos)

    def armar(marco: str, usados: Sequence[str]) -> tuple[str, tuple[str, ...]]:
        frases = {i: extra(i) for i in usados if i != "hora+estacion"}
        if "hora" in usados and "estacion" in usados and azar.random() < 0.5:
            frases["hora"] = azar.choice(_EXTRAS[idioma]["hora+estacion"]).format(**campos)
            del frases["estacion"]
        partes = [frases[i] for i in _APERTURA if i in frases] + [marco.format(**campos)] \
            + [frases[i] for i in _CIERRE if i in frases]
        return " ".join(partes), ("cancion", *usados)

    def ajustar(marco: str) -> Redaccion | None:
        usados = [i for i in elegidos if i != "cancion"]
        while True:
            texto, ingredientes = armar(marco, usados)
            if _palabras(texto) <= palabras_maximas:
                return Redaccion(texto, ingredientes)
            candidato = next((i for i in _DESCARTE if i in usados), None)
            if candidato is None:
                candidato = next(iter(usados), None)
            if candidato is None:
                return None
            usados.remove(candidato)

    for _ in range(10):
        r = ajustar(azar.choice(_MARCOS[idioma]))
        if r is not None:
            return r
    marco = min(_MARCOS[idioma], key=lambda t: _palabras(t.format(**campos)))
    return Redaccion(marco.format(**campos), ("cancion",))

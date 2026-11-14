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

# La frase = [oraciones sueltas: hora, estación, momento, tema anterior] + UNA oración principal: el marco (tema y
# artista) con, si toca, un comienzo enganchado delante (clima o álbum) y un dato colgado al final del nombre al que
# se refiere (el año del tema, el país del artista). Cada oración tiene al menos cuatro palabras aunque el nombre
# propio sea una sola (si no, el texto para voz la une con la vecina).
# (marco, nombre con el que termina: "artista", "titulo" o None si termina en un relleno)
_MARCOS = {
    "es": [("Seguimos con {artista} y su tema {titulo} para acompañar este momento de la mejor manera", None),
           ("Llega {titulo} de {artista} para vos", None),
           ("Ahora suena {titulo} de {artista}", "artista"),
           ("Sigue {titulo} con {artista}", "artista"),
           ("Llega {titulo} de la mano de {artista}", "artista"),
           ("Con ustedes {artista} y su tema {titulo}", "titulo"),
           ("De {artista} escuchamos ahora {titulo}", "titulo"),
           ("Sigue {artista} con {titulo}", "titulo")],
    "en": [("Coming up next we have {artista} with {titulo} to keep you company", None),
           ("Now playing {titulo} by {artista}", "artista"),
           ("Up next is {titulo} by {artista}", "artista"),
           ("Here comes {titulo} from {artista}", "artista"),
           ("Here comes {artista} with {titulo}", "titulo"),
           ("Stay with us for {artista} and {titulo}", "titulo")],
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
    },
}
# comienzos enganchados delante del marco (van con una coma y el marco empieza en minúscula)
_COMIENZOS = {
    "es": {"clima": ["Con {grados} afuera", "Afuera hay {grados} y {cielo}"],
           "album": ["Del disco {album}", "Desde el álbum {album}"]},
    "en": {"clima": ["With {grados} outside", "It is {grados} outside and {cielo}"],
           "album": ["From the album {album}", "Taken from the album {album}"]},
}
_CIELO = {
    "es": {"despejado": "el cielo está despejado", "nublado": "está nublado", "lluvia": "está lloviendo",
           "tormenta": "hay tormenta", "niebla": "hay niebla", "nieve": "está nevando"},
    "en": {"despejado": "the sky is clear", "nublado": "it is cloudy", "lluvia": "it is raining",
           "tormenta": "there is a storm", "niebla": "it is foggy", "nieve": "it is snowing"},
}
_NOCHE_DESPEJADA = {"es": "la noche está despejada", "en": "the night is clear"}
# datos colgados del final del marco: (campo que necesita, nombre al que se pegan, texto)
_COLAS = {
    "es": [("anio", "titulo", "que salió en {anio}"), ("anio", "titulo", "que es de {anio}"),
           ("pais", "artista", "que viene de {pais}"), ("inicio", "artista", "una banda que empezó en {inicio}")],
    "en": [("anio", "titulo", "which came out in {anio}"), ("anio", "titulo", "from {anio}"),
           ("pais", "artista", "an artist from {pais}"), ("inicio", "artista", "a band that started in {inicio}")],
}
_DESCARTE = ("dato", "clima", "anterior", "album")        # lo primero que se saca si la frase no entra
_SUELTOS = ("hora", "estacion", "momento", "anterior")


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
    palabras = en_palabras(temperatura, idioma)
    if idioma == "es" and palabras.endswith("uno"):          # "veintiún grados", "treinta y un grados"
        palabras = palabras[:-3] + ("ún" if palabras.endswith("veintiuno") else "un")
    return f"{palabras} {'grados' if idioma == 'es' else 'degrees'}"


def _variantes_de_dato(hechos: Hechos, idioma: str) -> list[tuple[str, str]]:
    """Las colas de dato que se pueden decir con lo verificado: (nombre al que se pegan, texto)."""
    t = hechos.tema
    if t is None:
        return []
    tiene = {"anio": t.anio is not None and 1900 <= t.anio <= 2099,
             "pais": t.pais is not None and nombre_de_pais(t.pais, idioma) is not None,
             "inicio": t.es_grupo and t.anio_inicio_artista is not None and 1900 <= t.anio_inicio_artista <= 2099}
    return [(nombre, texto) for campo, nombre, texto in _COLAS[idioma] if tiene[campo]]


def ingredientes_disponibles(pedido: Pedido, hechos: Hechos = Hechos()) -> set[str]:
    """Qué ingredientes se pueden usar para este pedido con lo que hay (y lo verificado)."""
    disponibles = {"cancion", "estacion", "hora", "momento"}
    if pedido.siguiente.album:
        disponibles.add("album")
    if pedido.anterior is not None:
        disponibles.add("anterior")
    c = hechos.clima
    if c is not None and -99 <= c.temperatura <= 99 and c.cielo in _CIELO["es"]:
        disponibles.add("clima")
    idioma = "es" if pedido.idioma == "es" else "en"
    if _variantes_de_dato(hechos, idioma):
        disponibles.add("dato")
    return disponibles


def _artistas(artista: str) -> list[str]:
    """Los artistas del tag sin repetidos ("R.K.M & Ken-Y, Ken-Y" → uno solo) y a lo sumo dos."""
    partes = [p.strip() for p in artista.split(", ") if p.strip()]
    claves = [re.sub(r"\W+", " ", p.casefold()).strip() for p in partes]
    utiles = [p for i, p in enumerate(partes)
              if not any(i != j and (f" {claves[i]} " in f" {claves[j]} ") and (claves[i] != claves[j] or j < i)
                         for j in range(len(partes)))]
    return (utiles or partes)[:2]


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
        "artista": (" y " if es else " and ").join(m(a) for a in _artistas(pedido.siguiente.artista)),
        "titulo": m(pedido.siguiente.titulo), "estacion": m(pedido.estacion),
        "hora": hora, "son": "Es" if hora.startswith("la ") else "Son",
        "son_min": "es" if hora.startswith("la ") else "son",
        "este_momento": _este_momento(momento, es), "este_dia": f"este {dia}" if es else f"this {dia}",
    }
    if pedido.siguiente.album:
        campos["album"] = m(pedido.siguiente.album)
    if pedido.anterior is not None:
        campos["artista_ant"] = (" y " if es else " and ").join(m(a) for a in _artistas(pedido.anterior.artista))
        campos["titulo_ant"] = m(pedido.anterior.titulo)
    disponibles = ingredientes_disponibles(pedido, hechos)
    if "clima" in disponibles:
        c = hechos.clima
        campos["grados"] = _grados(c.temperatura, idioma)
        campos["cielo"] = (_NOCHE_DESPEJADA[idioma] if not c.es_de_dia and c.cielo == "despejado"
                           else _CIELO[idioma][c.cielo])
    if hechos.tema is not None:
        t = hechos.tema
        if t.anio is not None and 1900 <= t.anio <= 2099:
            campos["anio"] = anio_en_palabras(t.anio, idioma)
        if t.pais is not None and nombre_de_pais(t.pais, idioma):
            campos["pais"] = nombre_de_pais(t.pais, idioma)
        if t.anio_inicio_artista is not None and 1900 <= t.anio_inicio_artista <= 2099:
            campos["inicio"] = anio_en_palabras(t.anio_inicio_artista, idioma)

    elegidos = elegir_ingredientes(disponibles, pesos, pedido.recientes, azar, maximo, penalizacion)
    if "clima" in elegidos and "album" in elegidos:
        elegidos = tuple(i for i in elegidos if i != "album")         # un solo comienzo enganchado por frase

    def armar(marco: str, usados: Sequence[str], comienzo: str | None, cola: str | None) -> str:
        sueltos = {i: azar_sueltos[i] for i in usados if i in _SUELTOS}
        if "hora" in sueltos and "estacion" in sueltos and fusion:
            sueltos["hora"] = fusion
            del sueltos["estacion"]
        principal = marco.format(**campos)
        if comienzo is not None and comienzo in usados:
            enganche = azar_comienzos[comienzo].format(**campos)
            principal = f"{enganche}, {principal[0].lower()}{principal[1:]}"
        if cola is not None and "dato" in usados:
            principal += f", {cola.format(**campos)}"
        partes = [sueltos[i] for i in _SUELTOS if i in sueltos] + [principal + "."]
        return " ".join(partes)

    def ajustar(marco: str, cola: str | None) -> Redaccion | None:
        usados = [i for i in elegidos if i != "cancion"]
        comienzo = next((i for i in ("clima", "album") if i in usados), None)
        while True:
            texto = armar(marco, usados, comienzo, cola)
            if _palabras(texto) <= palabras_maximas:
                return Redaccion(texto, ("cancion", *usados))
            candidato = next((i for i in _DESCARTE if i in usados), None) or next(iter(usados), None)
            if candidato is None:
                return None
            usados.remove(candidato)
            if candidato == comienzo:
                comienzo = None

    for _ in range(10):
        # lo que se elige al azar una vez por intento: las oraciones sueltas, su fusión y los comienzos
        azar_sueltos = {i: azar.choice(_EXTRAS[idioma][i]).format(**campos) for i in _SUELTOS
                        if i != "anterior" or pedido.anterior is not None}
        fusion = (azar.choice(_EXTRAS[idioma]["hora+estacion"]).format(**campos) if azar.random() < 0.5 else None)
        azar_comienzos = {i: azar.choice(f) for i, f in _COMIENZOS[idioma].items()}
        cola = None
        pool = _MARCOS[idioma]
        if "dato" in elegidos:
            nombre, cola = azar.choice(_variantes_de_dato(hechos, idioma))
            pool = [mc for mc in pool if mc[1] == nombre]
        marco = azar.choice(pool)[0]
        r = ajustar(marco, cola)
        if r is not None:
            return r
    marco = min((mc[0] for mc in _MARCOS[idioma]), key=lambda t: _palabras(t.format(**campos)))
    return Redaccion(marco.format(**campos) + ".", ("cancion",))

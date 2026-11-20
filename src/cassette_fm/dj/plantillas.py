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
# Los marcos se clasifican según dónde cae la voz respecto del corte entre dos temas:
#   "ahora"    el tema nuevo ya está sonando ("Ahora suena X"): solo valen si la voz empieza después del corte;
#   "neutra"   sirven a ambos lados del corte ("Llega X", "Sigue X");
#   "adelante" el tema nuevo todavía no empezó ("A continuación X"): solo valen si la voz termina antes del corte.
# (marco, nombre con el que termina: "artista", "titulo" o None si termina en un relleno)
_MARCOS = {
    "es": {"ahora": [("Ahora suena {titulo} de {artista}", "artista"),
                     ("De {artista} escuchamos ahora {titulo}", "titulo"),
                     ("Y ya suena {titulo} de {artista}", "artista"),
                     ("Suena ahora {artista} con {titulo}", "titulo")],
           "neutra": [("Seguimos con {artista} y su tema {titulo} para acompañar este momento de la mejor manera", None),
                      ("Llega {titulo} de {artista} para seguir con la mejor música", None),
                      ("Sigue {titulo} con {artista}", "artista"),
                      ("Llega {titulo} de la mano de {artista}", "artista"),
                      ("Con ustedes {artista} y su tema {titulo}", "titulo"),
                      ("Sigue {artista} con {titulo}", "titulo")],
           "adelante": [("A continuación escuchamos {titulo} de {artista}", "artista"),
                        ("Enseguida llega {titulo} de {artista}", "artista"),
                        ("A continuación tenemos a {artista} con {titulo}", "titulo"),
                        ("Enseguida sigue {artista} con {titulo}", "titulo")]},
    "en": {"ahora": [("Now playing {titulo} by {artista}", "artista"),
                     ("Right now you are hearing {titulo} by {artista}", "artista"),
                     ("Playing right now is {artista} with {titulo}", "titulo"),
                     ("Now we are hearing {artista} with {titulo}", "titulo")],
           "neutra": [("Here comes {titulo} from {artista}", "artista"),
                      ("Here comes {artista} with {titulo}", "titulo"),
                      ("Stay with us for {artista} and {titulo}", "titulo")],
           "adelante": [("Coming up next we have {artista} with {titulo} to keep you company", None),
                        ("Coming up next we have {artista} with {titulo} to keep the music going", None),
                        ("Up next is {titulo} by {artista}", "artista"),
                        ("Coming up next is {artista} with {titulo}", "titulo")]},
}
_EXTRAS = {
    "es": {
        "hora": ["{son} {hora} y seguimos con vos.", "En este momento {son_min} {hora}.", "{son} {hora} en la radio."],
        "estacion": ["Estás escuchando {estacion} en vivo.", "Esto es {estacion} tu radio de siempre.",
                     "Acá en {estacion} seguimos con vos.", "Bienvenidos a {estacion} la radio que no para."],
        "hora+estacion": ["Acá en {estacion} {son_min} {hora}.", "{son} {hora} acá en {estacion} con ustedes."],
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
# el tema anterior fue una petición del público ("despues" y "seguidas"): va primero y nunca se descarta
_PETICION_ANTERIOR = {
    "es": ["Escuchábamos {titulo_ant} de {artista_ant} por petición especial de nuestro público.",
           "Eso fue {titulo_ant} de {artista_ant}, a petición de uno de nuestros oyentes.",
           "Recién sonó {titulo_ant} de {artista_ant}, un pedido especial del público."],
    "en": ["We were listening to {titulo_ant} by {artista_ant}, a special request from our audience.",
           "That was {titulo_ant} by {artista_ant}, requested by one of our listeners.",
           "We just heard {titulo_ant} by {artista_ant}, a special request from the audience."],
}
# el tema que sigue es una petición ("antes" y "seguidas"): el marco mismo la anuncia, sin comienzo enganchado
# (mismas clases que los marcos normales: [idioma][modo][clase])
_MARCOS_PETICION = {
    "es": {"antes": {"ahora": [("Por pedido de uno de nuestros oyentes suena {artista} con {titulo}", "titulo"),
                               ("A petición de un oyente ahora suena {titulo} de {artista}", "artista"),
                               ("Ahora suena por pedido del público {artista} con {titulo}", "titulo")],
                     "neutra": [("A petición de uno de nuestros oyentes llega {titulo} de {artista}", "artista"),
                                ("Y ahora, a petición de uno de nuestros escuchas, tenemos {titulo} de {artista}",
                                 "artista"),
                                ("Llega una petición especial del público: {titulo} de {artista}", "artista"),
                                ("Llega un pedido especial de un oyente, {artista} con {titulo}", "titulo")],
                     "adelante": [("A continuación, a petición de un oyente, {titulo} de {artista}", "artista"),
                                  ("Enseguida llega un pedido del público: {artista} con {titulo}", "titulo"),
                                  ("A continuación una petición especial: {titulo} de {artista}", "artista")]},
           "seguidas": {"ahora": [("Seguimos con los pedidos del público y ahora suena {artista} con {titulo}", "titulo"),
                                  ("Y ahora suena otro pedido del público: {titulo} de {artista}", "artista"),
                                  ("Otro oyente pidió y ahora suena {artista} con {titulo}", "titulo")],
                        "neutra": [("Y llega otra petición especial: {titulo} de {artista}", "artista"),
                                   ("A petición de otro oyente llega {titulo} de {artista}", "artista"),
                                   ("Seguimos con los pedidos y llega {artista} con {titulo}", "titulo")],
                        "adelante": [("Y enseguida llega otra petición: {titulo} de {artista}", "artista"),
                                     ("A continuación otro pedido del público: {artista} con {titulo}", "titulo"),
                                     ("Enseguida otra petición especial de un oyente: {titulo} de {artista}",
                                      "artista")]}},
    "en": {"antes": {"ahora": [("At a listener's request we are now hearing {titulo} by {artista}", "artista"),
                               ("Playing now by request of our audience is {artista} with {titulo}", "titulo"),
                               ("A listener asked for this one and now playing is {artista} with {titulo}", "titulo")],
                     "neutra": [("At the request of one of our listeners here is {titulo} by {artista}", "artista"),
                                ("And now, a special request from our audience: {titulo} by {artista}", "artista"),
                                ("One of our listeners asked for {artista} and here is {titulo}", "titulo")],
                     "adelante": [("Coming up next by request of a listener is {titulo} by {artista}", "artista"),
                                  ("Up next is a special request from our audience: {artista} with {titulo}", "titulo"),
                                  ("Coming up next a request from one of our listeners: {titulo} by {artista}",
                                   "artista")]},
           "seguidas": {"ahora": [("And now playing is another request: {titulo} by {artista}", "artista"),
                                  ("Another request from our audience is now playing: {artista} with {titulo}", "titulo"),
                                  ("Now we are hearing another listener's pick, {artista} with {titulo}", "titulo")],
                        "neutra": [("And here comes another request: {titulo} by {artista}", "artista"),
                                   ("Another listener asked for {artista} and here is {titulo}", "titulo"),
                                   ("Here comes one more request from our audience: {titulo} by {artista}", "artista")],
                        "adelante": [("Coming up next is another request: {titulo} by {artista}", "artista"),
                                     ("Up next we have one more listener request: {artista} with {titulo}", "titulo"),
                                     ("Coming up next another request from our audience: {titulo} by {artista}",
                                      "artista")]}},
}
_CLASES_POR_POSICION = {"inicio": ("ahora", "neutra"), "entre": ("neutra",), "final": ("adelante", "neutra")}
_DESCARTE = ("dato", "clima", "anterior", "album")        # lo primero que se saca si la frase no entra
_SUELTOS = ("hora", "estacion", "momento", "anterior")


@dataclass(frozen=True)
class Redaccion:
    marcado: str                       # frase con marcas {lang:Nombre} en los nombres propios
    ingredientes: tuple[str, ...]


def marcos_para(idioma: str, posicion: str, peticion: str | None) -> list[tuple[str, str | None]]:
    """Los marcos que se pueden decir si la voz cae en `posicion` (inicio | entre | final) respecto del corte entre
    temas. Con `peticion` "antes" o "seguidas" son los marcos de petición; con cualquier otro valor, los normales."""
    por_clase = _MARCOS_PETICION[idioma][peticion] if peticion in ("antes", "seguidas") else _MARCOS[idioma]
    return [marco for clase in _CLASES_POR_POSICION[posicion] for marco in por_clase[clase]]


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


_RECOPILATORIO = re.compile(
    r"\b(?:hits?|greatest|best of|collection|chartshow|compilation|anthology|essentials?|ultimate|"
    r"vol(?:ume)?\b\.?|now that'?s|\blive\b|dj mix|\bmix\b|b2b|sixties|seventies|eighties|nineties|"
    r"love songs|disc\b|cd\s*\d|grandes [eé]xitos|[eé]xitos|lo mejor|colecci[oó]n|antolog[ií]a|en vivo|\d+\s+of the)\b",
    re.IGNORECASE)


def es_recopilatorio(album: str) -> bool:
    """Un álbum de la etiqueta que no vale la pena nombrar: recopilatorios, en vivo, mezclas de DJ."""
    return bool(_RECOPILATORIO.search(album))


def ingredientes_disponibles(pedido: Pedido, hechos: Hechos = Hechos()) -> set[str]:
    """Qué ingredientes se pueden usar para este pedido con lo que hay (y lo verificado)."""
    disponibles = {"cancion", "estacion", "hora", "momento"}
    if pedido.siguiente.album and not es_recopilatorio(pedido.siguiente.album):
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
        "titulo": m(titulo_hablado(pedido.siguiente.titulo)), "estacion": m(pedido.estacion),
        "hora": hora, "son": "Es" if hora.startswith("la ") else "Son",
        "son_min": "es" if hora.startswith("la ") else "son",
        "este_momento": _este_momento(momento, es), "este_dia": f"este {dia}" if es else f"this {dia}",
    }
    if pedido.siguiente.album:
        campos["album"] = m(pedido.siguiente.album)
    if pedido.anterior is not None:
        campos["artista_ant"] = (" y " if es else " and ").join(m(a) for a in _artistas(pedido.anterior.artista))
        campos["titulo_ant"] = m(titulo_hablado(pedido.anterior.titulo))
    disponibles = ingredientes_disponibles(pedido, hechos)
    peticion = pedido.peticion
    if peticion in ("despues", "seguidas") and pedido.anterior is None:
        peticion = "antes" if peticion == "seguidas" else None      # sin el anterior no se lo puede nombrar
    if peticion in ("despues", "seguidas"):
        disponibles.discard("anterior")          # ya lo nombra la oración de la petición
    if peticion in ("antes", "seguidas"):
        disponibles -= {"clima", "album"}        # el marco de la petición no lleva comienzo enganchado
    marcos = marcos_para(idioma, pedido.posicion, peticion)
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
        return " ".join(([prefijo] if prefijo else []) + partes)

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

    prefijo = None
    for _ in range(10):
        # lo que se elige al azar una vez por intento: las oraciones sueltas, su fusión y los comienzos
        prefijo = (azar.choice(_PETICION_ANTERIOR[idioma]).format(**campos) if peticion in ("despues", "seguidas")
                   else None)
        azar_sueltos = {i: azar.choice(_EXTRAS[idioma][i]).format(**campos) for i in _SUELTOS
                        if i != "anterior" or pedido.anterior is not None}
        fusion = (azar.choice(_EXTRAS[idioma]["hora+estacion"]).format(**campos) if azar.random() < 0.5 else None)
        azar_comienzos = {i: azar.choice(f) for i, f in _COMIENZOS[idioma].items()}
        cola = None
        pool = marcos
        if "dato" in elegidos:
            nombre, cola = azar.choice(_variantes_de_dato(hechos, idioma))
            pool = [mc for mc in pool if mc[1] == nombre]
        marco = azar.choice(pool)[0]
        r = ajustar(marco, cola)
        if r is not None:
            return r
    marco = min((mc[0] for mc in marcos), key=lambda t: _palabras(t.format(**campos)))
    return Redaccion(" ".join(([prefijo] if prefijo else []) + [marco.format(**campos) + "."]), ("cancion",))


# --- piezas que usa también el redactor del LLM ---

def grados_en_palabras(temperatura: int, idioma: str) -> str:
    return _grados(temperatura, "es" if idioma == "es" else "en")


def cielo_en_palabras(clima, idioma: str) -> str:
    idioma = "es" if idioma == "es" else "en"
    if not clima.es_de_dia and clima.cielo == "despejado":
        return _NOCHE_DESPEJADA[idioma]
    return _CIELO[idioma][clima.cielo]


def artistas_del_tag(artista: str) -> list[str]:
    return _artistas(artista)


_FEAT = re.compile(r"\s*[\(\[]\s*(?:feat|ft|featuring|with)\b[^\)\]]*[\)\]]|\s+[-–—]\s+(?:feat|ft)\b.*$",
                   re.IGNORECASE)


def titulo_hablado(titulo: str) -> str:
    """El título sin el "(feat. X)": el artista ya lo nombra y repetirlo suena a lista."""
    return _FEAT.sub("", titulo).strip() or titulo.strip()


def momento_en_palabras(momento: datetime, idioma: str) -> str:
    return _este_momento(momento, idioma == "es")

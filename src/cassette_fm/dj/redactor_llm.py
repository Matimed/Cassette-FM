"""Prompt, limpieza, verificación y marcado de la frase que escribe el LLM (reglas del diseño de la Etapa 3)."""
import difflib
import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, tzinfo

from cassette_fm.dj.hechos import Hechos
from cassette_fm.dj.hechos.numeros import anio_en_palabras, en_palabras
from cassette_fm.dj.hechos.paises import nombre_de_pais
from cassette_fm.dj.lexico import Lexico
from cassette_fm.dj.pedido import Pedido
from cassette_fm.dj.plantillas import (artistas_del_tag, cielo_en_palabras, frase_hora, grados_en_palabras,
                                       momento_en_palabras)
from cassette_fm.dj.texto_voz import marcar

_DIAS = {"es": ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"],
         "en": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]}
_MESES = {"es": ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
                 "noviembre", "diciembre"],
          "en": ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
                 "November", "December"]}
_EXCEPCIONES = {"buenos", "aires", "argentina"}      # nombres comunes que no hace falta que estén en los hechos
_PALABRA = re.compile(r"[^\W\d_][\w'’-]*")
_NUMERO = re.compile(r"\d+(?:[.,]\d+)?")


@dataclass(frozen=True)
class Peticion:
    sistema: str
    usuario: str
    permitido: str            # todo el texto de los hechos que se le pasaron (para verificar), con las cifras en dígitos


def _sin_acentos(texto: str) -> str:
    t = unicodedata.normalize("NFD", texto)
    return "".join(c for c in t if unicodedata.category(c) != "Mn").casefold()


def _norm(texto: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[\W_]+", " ", _sin_acentos(texto))).strip()


def _titulo_limpio(titulo: str) -> str:
    t = re.sub(r"\s*[\(\[][^\)\]]*[\)\]]", "", titulo)
    t = re.sub(r"\s+[-–—]\s+.*$", "", t)
    return t.strip() or titulo.strip()


def _idioma(pedido: Pedido) -> str:
    return "es" if pedido.idioma == "es" else "en"


def campos_de_voz(pedido: Pedido, hechos: Hechos, zona: tzinfo | None = None) -> dict[str, str]:
    """Hora, momento, día, grados y cielo ya en palabras, como los dicen las plantillas."""
    idioma = _idioma(pedido)
    momento = pedido.momento.astimezone(zona) if zona is not None else pedido.momento
    campos = {"hora": frase_hora(momento, idioma), "momento": momento_en_palabras(momento, idioma),
              "dia": _DIAS[idioma][momento.weekday()]}
    if hechos.clima is not None:
        campos["grados"] = grados_en_palabras(hechos.clima.temperatura, idioma)
        campos["cielo"] = cielo_en_palabras(hechos.clima, idioma)
    return campos


def _hechos_del_tema(hechos: Hechos, idioma: str) -> list[str]:
    t = hechos.tema
    if t is None:
        return []
    frases = []
    if t.anio is not None and 1900 <= t.anio <= 2099:
        frases.append(("Año de la canción (no del álbum): %s" if idioma == "es"
                       else "Song year (the song, not the album): %s") % t.anio)
    pais = nombre_de_pais(t.pais, idioma) if t.pais else None
    if pais:
        frases.append(("El artista viene de %s." if idioma == "es" else "The artist comes from %s.") % pais)
    if t.es_grupo and t.anio_inicio_artista is not None and 1900 <= t.anio_inicio_artista <= 2099:
        frases.append(("Año en que empezó la banda: %s" if idioma == "es" else "Year the band started: %s")
                      % t.anio_inicio_artista)
    return frases


def construir_peticion(pedido: Pedido, ingredientes: Sequence[str], hechos: Hechos,
                       campos_de_voz: Mapping[str, str], palabras_maximas: int) -> Peticion:
    idioma = _idioma(pedido)
    es = idioma == "es"
    artista = (" y " if es else " and ").join(artistas_del_tag(pedido.siguiente.artista))
    lineas = [f"Tema: {_titulo_limpio(pedido.siguiente.titulo)} de {artista}" if es
              else f"Song: {_titulo_limpio(pedido.siguiente.titulo)} by {artista}"]
    cifras: list[str] = []
    if "estacion" in ingredientes:
        lineas.append(f"{'Estación' if es else 'Station'}: {pedido.estacion}")
    if "hora" in ingredientes:
        lineas.append(f"{'Hora' if es else 'Time'}: {campos_de_voz['hora']} ({campos_de_voz['momento']})")
    if "momento" in ingredientes:
        lineas.append(f"{'Momento' if es else 'Moment'}: {campos_de_voz['momento']} ({campos_de_voz['dia']})"
                      if es else f"Moment: {campos_de_voz['momento']} ({campos_de_voz['dia']})")
    if "album" in ingredientes and pedido.siguiente.album:
        lineas.append(f"{'Álbum' if es else 'Album'}: {pedido.siguiente.album}")
    if "anterior" in ingredientes and pedido.anterior is not None:
        previo = " y ".join(artistas_del_tag(pedido.anterior.artista)) if es \
            else " and ".join(artistas_del_tag(pedido.anterior.artista))
        lineas.append(f"{'Tema anterior' if es else 'Previous song'}: {_titulo_limpio(pedido.anterior.titulo)} "
                      f"{'de' if es else 'by'} {previo}")
    if "clima" in ingredientes and hechos.clima is not None:
        lineas.append(f"{'Clima afuera' if es else 'Weather outside'}: {campos_de_voz['grados']}, "
                      f"{campos_de_voz['cielo']}")
        cifras.append(str(hechos.clima.temperatura))
    if "dato" in ingredientes:
        if hechos.wikipedia is not None:
            lineas.append(f"{'Dato del artista (Wikipedia; usá a lo sumo uno, con tus palabras)' if es else 'Artist fact (Wikipedia; use at most one, in your own words)'}: "
                          f"{hechos.wikipedia.texto}")
        for frase in _hechos_del_tema(hechos, idioma):
            lineas.append(f"{'Dato' if es else 'Fact'}: {frase}")
        if hechos.tema is not None:
            cifras += [str(x) for x in (hechos.tema.anio, hechos.tema.anio_inicio_artista) if x is not None]
    minimo = max(8, palabras_maximas // 2)
    tono = (f"\nTono: {pedido.personalidad}" if pedido.personalidad else "")
    if es:
        sistema = (f"Sos el locutor de la radio {pedido.estacion}. Escribí UNA sola intervención hablada, de entre "
                   f"{minimo} y {palabras_maximas} palabras, en español.\n"
                   "Reglas:\n"
                   "- Usá SOLO los hechos del mensaje. No inventes nada: ni años, ni cifras, ni nombres, ni datos.\n"
                   "- Nombrá el tema y el artista exactamente como están escritos.\n"
                   "- Hablá natural, con frases cortas. Sin exclamaciones, emojis, comillas, listas, títulos ni "
                   "explicaciones.\n"
                   "- Unilo todo en un solo discurso fluido: enlazá las ideas con conectores (\"y\", \"además\", "
                   "\"por cierto\", \"mientras tanto\") en vez de frases sueltas.\n"
                   "- No empieces con \"aquí tienes\" ni digas que sos una IA.\n"
                   "- No menciones el momento del día, el día de la semana ni el clima si el mensaje no los da.\n"
                   "- Escribí los años con cifras (por ejemplo 1984).\n"
                   "- Si hay un dato de Wikipedia, usá a lo sumo uno y decilo con tus palabras en una frase corta."
                   + tono)
    else:
        sistema = (f"You are the radio host of {pedido.estacion}. Write ONE single spoken announcement of between "
                   f"{minimo} and {palabras_maximas} words, in English.\n"
                   "Rules:\n"
                   "- Use ONLY the facts in the message. Invent nothing: no years, figures, names or facts.\n"
                   "- Say the song and the artist exactly as written.\n"
                   "- Sound natural, with short sentences. No exclamation marks, emojis, quotes, lists, headings or "
                   "explanations.\n"
                   "- Make it one flowing speech: join the ideas with connectors (\"and\", \"also\", \"by the way\", "
                   "\"meanwhile\") instead of separate stand-alone sentences.\n"
                   "- Do not start with \"here is\" and never say you are an AI.\n"
                   "- Do not mention the time of day, the day of the week or the weather unless the message gives it.\n"
                   "- Write years as digits (for example 1984).\n"
                   "- If there is a Wikipedia fact, use at most one, in your own words, in one short sentence."
                   + tono)
    usuario = "\n".join(lineas)
    permitido = "\n".join([usuario, pedido.estacion, pedido.siguiente.titulo, pedido.siguiente.artista,
                           *(["[" + " ".join(cifras) + "]"] if cifras else [])])
    return Peticion(sistema, usuario, permitido)


# --- limpieza ---

_EMOJI = re.compile("[\U0001F000-\U0001FFFF\U00002600-\U000027BF\U0000FE0F\U0000200D\U00002B00-\U00002BFF]")
_PREFIJO = re.compile(r"^[^:\n]{0,80}?\b(?:aqu[ií]|ac[aá]|here)\b[^:\n]{0,50}:\s*", re.I)
_INTERJECCION = re.compile(r"^[¡¿]?(?:claro|por supuesto|dale|listo|sure|of course|certainly|okay|ok|absolutely)\b"
                           r"[!.,¡]*\s*", re.I)


def _es_preambulo(parrafo: str) -> bool:
    """Una línea corta de cortesía antes del texto ("Here's the announcement:", "Okay, here we go!")."""
    return len(parrafo.split()) <= 10 and (parrafo.endswith(":") or bool(_INTERJECCION.match(parrafo)))


def limpiar_salida(crudo: str) -> str:
    texto = re.sub(r"```[^\n]*", "", crudo or "")
    parrafos = [p.strip() for p in re.split(r"\n\s*\n", texto) if p.strip()]
    while len(parrafos) > 1 and _es_preambulo(parrafos[0]):
        parrafos = parrafos[1:]                  # "Okay, here's the announcement:" va en un párrafo aparte
    if not parrafos:
        return ""
    lineas = [ln.strip() for ln in parrafos[0].splitlines() if ln.strip()]
    lineas = [ln for ln in lineas if not ln.startswith("#")] or lineas
    if len(lineas) > 1 and re.match(r"(?i)^(aqu[ií]|ac[aá]|here)\b.*:$", lineas[0]):
        lineas = lineas[1:]
    t = " ".join(lineas)
    t = _INTERJECCION.sub("", t)
    t = _PREFIJO.sub("", t)
    t = _EMOJI.sub("", t)
    t = re.sub(r"[*_`#{}]", "", t)
    t = t.strip().strip("\"'“”«»‘’").strip()
    t = re.sub(r"\s+([.,;:?!])", r"\1", t)
    return re.sub(r"\s+", " ", t).strip()


def _nombres_del_pedido(pedido: Pedido) -> list[str]:
    """Los nombres propios del pedido que el LLM puede repetir (artistas, tema, estación, álbum, tema anterior)."""
    nombres = list(artistas_del_tag(pedido.siguiente.artista))
    nombres += [pedido.siguiente.titulo, _titulo_limpio(pedido.siguiente.titulo), pedido.estacion]
    if pedido.siguiente.album:
        nombres.append(pedido.siguiente.album)
    if pedido.anterior is not None:
        nombres += artistas_del_tag(pedido.anterior.artista)
        nombres += [pedido.anterior.titulo, _titulo_limpio(pedido.anterior.titulo)]
    return sorted(dict.fromkeys(n for n in nombres if n.strip()), key=len, reverse=True)


def _sin_nombres(texto: str, pedido: Pedido) -> str:
    for nombre in _nombres_del_pedido(pedido):
        texto = re.sub(r"(?<![\w])" + re.escape(nombre) + r"(?![\w])", " ", texto, flags=re.I)
    return texto


# palabras funcionales para reconocer el idioma (ya sin acentos ni mayúsculas)
_FUNCIONALES = {
    "es": set("de la que el en y a los las un una por con para se su es del al lo como mas pero sus le ya o fue "
              "muy sin sobre entre vos nos te mi tu todo todos esta este eso".split()),
    "en": set("the and of is to in for with by on it this that you your are we our here next now at as be was an or "
              "from there they have has not but all".split()),
}
_ANIOS_EN_PALABRAS = {
    "es": re.compile(r"\b(?:mil novecientos|dos mil)\b"),
    "en": re.compile(r"\b(?:nineteen (?:hundred|oh|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety)|two thousand|"
                     r"twenty (?:ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|"
                     r"twenty|oh))\b"),
}

# --- verificación ---

def _oraciones(texto: str) -> list[str]:
    return [o for o in re.split(r"(?<=[.!?])[\"”’»)]*\s+", texto) if o.strip()]


def verificar(texto: str, pedido: Pedido, peticion: Peticion, palabras_maximas: int,
              zona: tzinfo | None = None) -> str | None:
    """None si la frase se puede decir; si no, el motivo (corto, en español) para el guion."""
    palabras = texto.split()
    if not texto.strip():
        return "vacío"
    if len(palabras) > palabras_maximas * 1.3:
        return "demasiado largo"
    if len(palabras) < 4:
        return "demasiado corto"
    if re.search(r"https?://|www\.|[@#]|\b[\w-]+\.(?:org|com|net|ar|io|fm|es|co|uk|tv|me|info)\b", texto, re.I):
        return "tiene enlaces o etiquetas"
    plano = _norm(texto)
    artistas = artistas_del_tag(pedido.siguiente.artista)
    if _norm(_titulo_limpio(pedido.siguiente.titulo)) not in plano or not any(_norm(a) in plano for a in artistas):
        return "no nombra el tema o el artista"
    idioma = _idioma(pedido)
    resto = _sin_nombres(texto, pedido)                    # lo que dijo el LLM fuera de los nombres del pedido
    propias = _FUNCIONALES[idioma]
    ajenas = _FUNCIONALES["en" if idioma == "es" else "es"]
    fichas = _norm(resto).split()
    n_propias, n_ajenas = sum(f in propias for f in fichas), sum(f in ajenas for f in fichas)
    if n_ajenas >= 2 and n_ajenas > n_propias:
        return f"no está en {'español' if idioma == 'es' else 'inglés'}"
    momento = pedido.momento.astimezone(zona) if zona is not None else pedido.momento
    hoy = momento.weekday()
    for i, dia in enumerate(_DIAS[idioma]):
        if i != hoy and re.search(rf"(?<!\w){_norm(dia)}(?!\w)", _norm(resto)):
            return f"día de la semana que no es hoy: {dia}"
    permitidos = {int(n) for n in re.findall(r"\d+", peticion.permitido)}
    for numero in _NUMERO.findall(resto):
        if not numero.isdigit():
            return "número que no se puede decir"
        if int(numero) not in permitidos:
            return "número que no está en los hechos"
        if not (0 <= int(numero) <= 99 or 1900 <= int(numero) <= 2099):
            return "número que no se puede decir"
    hablado = _norm(resto)
    for anio in (n for n in permitidos if 1900 <= n <= 2099):
        hablado = hablado.replace(_norm(anio_en_palabras(anio, idioma)), " ")
    if _ANIOS_EN_PALABRAS[idioma].search(hablado):
        return "año en palabras que no está en los hechos"
    vocabulario = set(_norm(peticion.permitido).split()) | set(_norm(pedido.estacion).split())
    vocabulario |= set(_norm(peticion.permitido.replace(".", "")).split())        # "F.M." también como "FM"
    vocabulario |= set(_norm(pedido.estacion.replace(".", "")).split())
    vocabulario |= {_norm(x) for x in _DIAS[idioma] + _MESES[idioma]} | _EXCEPCIONES
    for oracion in _oraciones(texto):
        for i, m in enumerate(_PALABRA.finditer(oracion)):
            palabra = m.group(0)
            if i == 0 or not palabra[0].isupper() or len(palabra) == 1:
                continue    # la mayúscula del arranque de una oración no indica un nombre
            partes = [p for p in re.split(r"['’-]", _sin_acentos(palabra)) if p]
            if not all(p in vocabulario or len(p) == 1 or difflib.get_close_matches(p, vocabulario, 1, 0.85)
                       for p in partes):
                return f"nombre propio que no está en los hechos: {palabra}"
    if len(_oraciones(texto)) > 4:
        return "demasiadas oraciones"
    return None


def numeros_a_palabras(texto: str, idioma: str) -> str:
    """Pasa las cifras a palabras (años 1900–2099, 0–99); ValueError si hay una que no se puede decir.
    Lo que está dentro de una marca {idioma:Nombre} (U2, Blink-182…) no se toca."""
    idioma = "es" if idioma == "es" else "en"

    def grados(m: re.Match) -> str:
        return grados_en_palabras(int(m.group(1).replace("−", "-")), idioma)

    def numero(m: re.Match) -> str:
        crudo = m.group(0)
        if not crudo.isdigit():
            raise ValueError(f"número que no se puede decir: {crudo}")
        n = int(crudo)
        if 1900 <= n <= 2099:
            return anio_en_palabras(n, idioma)
        if 0 <= n <= 99:
            return en_palabras(n, idioma)
        raise ValueError(f"número que no se puede decir: {crudo}")

    def convertir(trozo: str) -> str:
        trozo = re.sub(r"(?<![\w-])([-−]?\d{1,2})\s+(?:grados?|degrees?)\b", grados, trozo)
        return _NUMERO.sub(numero, trozo)

    return "".join(p if p.startswith("{") and p.endswith("}") else convertir(p)
                   for p in re.split(r"(\{[^{}]*\})", texto))


# --- marcado de nombres ---

def marcar_nombres(texto: str, pedido: Pedido, hechos: Hechos, lexico: Lexico) -> str:
    """El texto con {idioma:Nombre} en cada aparición exacta de los nombres del pedido (con la pronunciación del
    léxico y su idioma, como las plantillas)."""
    lang = pedido.lang
    ocupado: list[tuple[int, int, str]] = []
    for nombre in _nombres_del_pedido(pedido):
        patron = re.compile(r"(?<![\w])" + re.escape(nombre) + r"(?![\w])", re.I)
        for m in patron.finditer(texto):
            if any(m.start() < f and i < m.end() for i, f, _ in ocupado):
                continue
            ocupado.append((m.start(), m.end(), nombre))
    salida, cursor = [], 0
    for inicio, fin, nombre in sorted(ocupado):
        salida.append(texto[cursor:inicio])
        salida.append(marcar(lexico.pronunciacion(nombre), lexico.idioma_de(nombre, lang)))
        cursor = fin
    salida.append(texto[cursor:])
    return "".join(salida)

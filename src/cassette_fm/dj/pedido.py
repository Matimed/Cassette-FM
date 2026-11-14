import re
from dataclasses import dataclass
from datetime import datetime

IDIOMAS = {"es": "es", "en": "en-us", "en-us": "en-us", "en-gb": "en-gb"}   # idioma del pedido -> `lang` de Kokoro

_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")
_VOZ = re.compile(r"[A-Za-z0-9_+.-]+")
_MAX_TEXTO = 300


@dataclass(frozen=True)
class Tema:
    artista: str
    titulo: str
    album: str | None = None
    isrc: str | None = None


@dataclass(frozen=True)
class Pedido:
    id: str
    estacion: str
    idioma: str
    voz: str
    momento: datetime
    anterior: Tema | None
    siguiente: Tema
    recientes: tuple[str, ...] = ()
    personalidad: str = ""
    duracion_maxima_segundos: float | None = None

    @property
    def lang(self) -> str:
        return IDIOMAS[self.idioma]


def _texto(datos: dict, campo: str, donde: str = "", obligatorio: bool = True) -> str | None:
    nombre = f"{donde}{campo}"
    if campo not in datos or datos[campo] is None:
        if obligatorio:
            raise ValueError(f"campo '{nombre}': falta")
        return None
    valor = datos[campo]
    if not isinstance(valor, str):
        raise ValueError(f"campo '{nombre}': tiene que ser un texto")
    valor = valor.strip()[:_MAX_TEXTO]
    # lo que queda al sacarle las llaves y las comillas (lo que se va a decir): no puede ser nada
    if not re.sub(r"[{}\"“”]", "", valor).strip():
        if obligatorio:
            raise ValueError(f"campo '{nombre}': no puede estar vacío")
        return None
    return valor


def _tema(datos: object, campo: str) -> Tema:
    if not isinstance(datos, dict):
        raise ValueError(f"campo '{campo}': tiene que ser un objeto con artista y titulo")
    donde = f"{campo}."
    return Tema(
        artista=_texto(datos, "artista", donde),
        titulo=_texto(datos, "titulo", donde),
        album=_texto(datos, "album", donde, obligatorio=False) or None,
        isrc=_texto(datos, "isrc", donde, obligatorio=False) or None,
    )


def leer_pedido(datos: object) -> Pedido:
    if not isinstance(datos, dict):
        raise ValueError("el pedido tiene que ser un objeto JSON")

    id_ = datos.get("id")
    if not isinstance(id_, str) or not _ID.fullmatch(id_):
        raise ValueError("campo 'id': tiene que ser un texto de 1 a 64 letras, números, guion o guion bajo")

    estacion = _texto(datos, "estacion")
    idioma = datos.get("idioma")
    if not isinstance(idioma, str) or idioma not in IDIOMAS:
        raise ValueError(f"campo 'idioma': tiene que ser uno de {', '.join(IDIOMAS)}")
    voz = datos.get("voz")
    if not isinstance(voz, str) or not _VOZ.fullmatch(voz):
        raise ValueError("campo 'voz': tiene que ser el nombre de una voz (letras, números, _ + . -)")

    crudo = datos.get("momento")
    try:
        momento = datetime.fromisoformat(crudo)
    except (TypeError, ValueError):
        raise ValueError("campo 'momento': tiene que ser una fecha ISO-8601 con zona horaria")
    if momento.tzinfo is None or momento.utcoffset() is None:
        raise ValueError("campo 'momento': falta la zona horaria (por ejemplo -03:00)")

    if "siguiente" not in datos:
        raise ValueError("campo 'siguiente': falta")
    siguiente = _tema(datos["siguiente"], "siguiente")
    anterior = None if datos.get("anterior") is None else _tema(datos["anterior"], "anterior")

    recientes = datos.get("recientes", [])
    if recientes is None:
        recientes = []
    if not isinstance(recientes, list) or not all(isinstance(r, str) for r in recientes):
        raise ValueError("campo 'recientes': tiene que ser una lista de textos")

    personalidad = datos.get("personalidad")
    if personalidad is not None and not isinstance(personalidad, str):
        raise ValueError("campo 'personalidad': tiene que ser un texto")

    maxima = datos.get("duracion_maxima_segundos")
    if maxima is not None:
        if isinstance(maxima, bool) or not isinstance(maxima, (int, float)) or maxima <= 0:
            raise ValueError("campo 'duracion_maxima_segundos': tiene que ser un número mayor que 0")
        maxima = float(maxima)

    return Pedido(id=id_, estacion=estacion, idioma=idioma, voz=voz, momento=momento, anterior=anterior,
                  siguiente=siguiente, recientes=tuple(recientes),
                  personalidad=(personalidad or "").strip()[:_MAX_TEXTO], duracion_maxima_segundos=maxima)

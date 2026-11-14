import re
import tomllib
import unicodedata
from collections.abc import Mapping
from pathlib import Path

from cassette_fm.config import ErrorConfig

_LANG = re.compile(r"[a-z]{2,3}(-[a-z]{2,3})?")


def _clave(nombre: str) -> str:
    sin_acentos = "".join(c for c in unicodedata.normalize("NFD", nombre) if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", sin_acentos.casefold()).strip()


class Lexico:
    """En qué idioma se pronuncia cada nombre propio (p. ej. "Daddy Yankee" → "en-us")."""

    def __init__(self, idiomas: Mapping[str, str] | None = None):
        self._idiomas = {_clave(n): lang for n, lang in (idiomas or {}).items()}

    @classmethod
    def cargar(cls, archivo: Path) -> "Lexico":
        try:
            with open(archivo, "rb") as f:
                datos = tomllib.load(f)
        except FileNotFoundError:
            return cls()
        except (tomllib.TOMLDecodeError, OSError) as e:
            raise ErrorConfig(f"{archivo}: {e}")
        tabla = datos.get("idiomas", {})
        if not isinstance(tabla, dict):
            raise ErrorConfig(f"{archivo}: 'idiomas' tiene que ser una tabla de nombre = idioma")
        for nombre, lang in tabla.items():
            if not isinstance(lang, str) or not _LANG.fullmatch(lang):
                raise ErrorConfig(f"{archivo}: el idioma de {nombre!r} tiene que ser como es, en-us o en-gb")
        return cls(tabla)

    def idioma_de(self, nombre: str, defecto: str) -> str:
        return self._idiomas.get(_clave(nombre), defecto)

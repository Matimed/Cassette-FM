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

    def __init__(self, idiomas: Mapping[str, str] | None = None, pronunciaciones: Mapping[str, str] | None = None):
        self._idiomas = {_clave(n): lang for n, lang in (idiomas or {}).items()}
        self._pronunciaciones = {_clave(n): dicho for n, dicho in (pronunciaciones or {}).items()}

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
        dichos = datos.get("pronunciacion", {})
        if not isinstance(dichos, dict):
            raise ErrorConfig(f"{archivo}: 'pronunciacion' tiene que ser una tabla de nombre = cómo se dice")
        for nombre, dicho in dichos.items():
            if not isinstance(dicho, str) or not dicho.strip():
                raise ErrorConfig(f"{archivo}: la pronunciación de {nombre!r} tiene que ser un texto no vacío")
        return cls(tabla, dichos)

    def idioma_de(self, nombre: str, defecto: str) -> str:
        return self._idiomas.get(_clave(nombre), defecto)

    def pronunciacion(self, nombre: str) -> str:
        """Cómo escribir el nombre para que la voz lo diga bien (\"Regueton\" → \"Reguetón\"); si no hay, el mismo."""
        return self._pronunciaciones.get(_clave(nombre), nombre)

import json
import logging
import re
import time
import urllib.parse
import urllib.request
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from cassette_fm.dj.config import ConfigServicioDJ
from cassette_fm.dj.hechos.cache import CacheHechos

_log = logging.getLogger("cassette_fm")
_QID = re.compile(r"Q\d+")


@dataclass(frozen=True)
class Resumen:
    texto: str       # el extracto, recortado en un fin de oración
    titulo: str
    idioma: str      # "es" | "en"
    url: str         # URL de la página (para el guion: el texto es CC BY-SA)


class _Fallo(Exception):
    pass


def _recortar(texto: str, maximo: int) -> str:
    """Oraciones completas hasta `maximo` palabras; si la primera ya se pasa, se corta en palabras."""
    oraciones = [o for o in re.split(r"(?<=[.!?])\s+", texto.strip()) if o]
    elegidas, total = [], 0
    for o in oraciones:
        n = len(o.split())
        if total + n > maximo:
            break
        elegidas.append(o)
        total += n
    if elegidas:
        return " ".join(elegidas)
    palabras = texto.split()[:maximo]
    return " ".join(palabras).rstrip(",;:") + ("" if palabras[-1].endswith((".", "!", "?")) else ".")


class ClienteWikipedia:
    """Resumen de Wikipedia de un artista a partir de su Q de Wikidata. Nunca lanza: sin dato, None."""

    def __init__(self, config: ConfigServicioDJ, cache: CacheHechos, version: str = "0.1"):
        self._config = config
        self._cache = cache
        self._version = version
        self._avisado = False

    def resumen(self, wikidata: str, idiomas: Sequence[str]) -> Resumen | None:
        c = self._config
        if not isinstance(wikidata, str) or not _QID.fullmatch(wikidata) or not c.contacto.strip():
            return None
        idiomas = [i for i in dict.fromkeys(idiomas) if re.fullmatch(r"[a-z]{2,3}", i)]
        if not idiomas:
            return None
        fallo: list[Exception] = []
        buscado = []

        def buscar():
            try:
                valor = self._buscar(wikidata, idiomas)
                buscado.append(1)
                return valor
            except Exception as e:
                fallo.append(e)
                return None

        def vigencia(valor) -> float:
            if fallo:
                return c.cache_error_minutos * 60
            return (c.wikipedia_dias if valor is not None else c.cache_sin_dato_dias) * 86400

        valor = self._cache.consultar(f"wp:{wikidata}:{'-'.join(idiomas)}", vigencia, buscar)
        if fallo:
            if not self._avisado:
                self._avisado = True
                _log.warning("Wikipedia no respondió (%s): el DJ sigue sin su resumen", fallo[0])
            return None
        if buscado:
            self._avisado = False
        if not isinstance(valor, dict):
            return None
        try:
            return Resumen(str(valor["texto"]), str(valor["titulo"]), str(valor["idioma"]), str(valor["url"]))
        except KeyError:
            return None

    def _buscar(self, wikidata: str, idiomas: list[str]) -> dict | None:
        c = self._config
        filtro = "|".join(f"{i}wiki" for i in idiomas)
        datos = self._pedir(c.wikidata_url, {"action": "wbgetentities", "ids": wikidata, "props": "sitelinks",
                                              "sitefilter": filtro, "format": "json"})
        entidad = datos.get("entities", {}).get(wikidata) if isinstance(datos, dict) else None
        enlaces = entidad.get("sitelinks") if isinstance(entidad, dict) else None
        if not isinstance(entidad, dict) or not isinstance(enlaces, dict):
            if isinstance(entidad, dict) and "sitelinks" not in entidad:
                return None            # la entidad existe y no tiene artículos en esos idiomas
            raise _Fallo("la respuesta de Wikidata no es la esperada")
        for idioma in idiomas:
            enlace = enlaces.get(f"{idioma}wiki")
            titulo = enlace.get("title") if isinstance(enlace, dict) else None
            if not isinstance(titulo, str) or not titulo.strip():
                continue
            base = c.wikipedia_url.format(idioma=idioma).rstrip("/")
            pagina = self._pedir(f"{base}/api/rest_v1/page/summary/{urllib.parse.quote(titulo, safe='')}", None)
            if (isinstance(pagina, dict) and pagina.get("type") == "standard"
                    and pagina.get("wikibase_item", wikidata) == wikidata      # si apunta a otro Q (redirección), no
                    and isinstance(pagina.get("extract"), str) and pagina["extract"].strip()):
                url = ((pagina.get("content_urls") or {}).get("desktop") or {}).get("page")
                return {"texto": _recortar(pagina["extract"], c.wikipedia_palabras_maximas),
                        "titulo": str(pagina.get("title") or titulo), "idioma": idioma,
                        "url": url if isinstance(url, str) else f"{base}/wiki/{urllib.parse.quote(titulo)}"}
        return None

    def _pedir(self, url: str, parametros: dict | None):
        c = self._config
        if parametros:
            url = f"{url}?{urllib.parse.urlencode(parametros)}"
        req = urllib.request.Request(url, headers={"User-Agent": f"cassette-dj/{self._version} ({c.contacto})",
                                                   "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=c.timeout_hechos_segundos) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None            # la página no existe: sin resumen, no es un fallo de la red
            raise _Fallo(f"HTTPError: {e}") from None
        except Exception as e:
            raise _Fallo(f"{type(e).__name__}: {e}") from None

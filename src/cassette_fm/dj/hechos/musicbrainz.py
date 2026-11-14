import json
import logging
import re
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass

from cassette_fm.dj.config import ConfigServicioDJ
from cassette_fm.dj.hechos.cache import CacheHechos

_log = logging.getLogger("cassette_fm")

_UUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
_ISRC = re.compile(r"[A-Z]{2}[A-Z0-9]{3}[0-9]{7}")
_FECHA = re.compile(r"(\d{4})(?:-(\d{2})(?:-(\d{2}))?)?")
_RELLENO = re.compile(r"remaster|remix|radio edit|\bfeat\b|\bft\b|\bfrom\b|version|\bmono\b|\bstereo\b|single|\blive\b|"
                      r"soundtrack|\bedit\b|deluxe|bonus", re.I)
_GUIONES = "‐‑‒–—―"
_LETRAS = str.maketrans({"ø": "o", "æ": "ae", "œ": "oe", "ł": "l", "đ": "d", "ß": "ss", "ð": "d", "þ": "th"})
_GENERICOS = {"intro", "outro", "interlude", "skit", "prelude", "interludio", "intermezzo", "untitled",
              "sin titulo", "introduccion", "epilogo", "prologue", "prologo", "reprise", "bonus track"}
INTERVALO_SEGUNDOS = 1.0


@dataclass(frozen=True)
class DatosTema:
    anio: int | None                   # año de lanzamiento del tema (el mínimo entre las grabaciones que coinciden)
    pais: str | None                   # código ISO del artista ("NO")
    anio_inicio_artista: int | None    # solo si es un grupo
    es_grupo: bool
    fuente: str                        # URL del artista en MusicBrainz


class _Fallo(Exception):
    pass


class _NoExiste(_Fallo):
    """El servidor contestó 404."""


def normalizar(texto: str) -> str:
    t = unicodedata.normalize("NFD", texto or "")
    t = "".join(c for c in t if unicodedata.category(c) != "Mn").casefold()
    t = t.translate(_LETRAS)
    for g in _GUIONES:
        t = t.replace(g, "-")
    t = t.replace("&", " and ")
    t = re.sub(r"[\W_]+", " ", t)            # conserva las letras de cualquier alfabeto
    return re.sub(r"\s+", " ", t).strip()


def _limpiar_titulo(titulo: str) -> str:
    """Quita lo que no es el nombre del tema (remaster, feat., from…) para buscar y comparar."""
    t = titulo.strip()
    for _ in range(4):
        previo = t
        t = re.sub(r"\s*[\(\[][^\)\]]*[\)\]]\s*$",
                   lambda m: "" if _RELLENO.search(m.group(0)) else m.group(0), t)
        m = re.search(r"\s+[-–—]\s+(.*)$", t)
        if m and _RELLENO.search(m.group(1)):
            t = t[:m.start()]
        m = re.search(r"\s+(feat\.?|ft\.?|featuring)\s.*$", t, re.I)
        if m:
            t = t[:m.start()]
        t = t.strip()
        if t == previo:
            break
    return t or titulo.strip()


def _escapar(texto: str) -> str:
    """Para ir entre comillas en una consulta Lucene: se escapan la barra y las comillas."""
    return re.sub(r'(["\\])', r"\\\1", texto)


def _primer_artista(artista: str) -> str:
    return artista.split(", ")[0].strip()


def _anio(fecha) -> int | None:
    if not isinstance(fecha, str):
        return None
    m = _FECHA.fullmatch(fecha)
    if not m:
        return None
    anio, mes, dia = int(m.group(1)), m.group(2), m.group(3)
    if (mes and not 1 <= int(mes) <= 12) or (dia and not 1 <= int(dia) <= 31):
        return None
    return anio if 1900 <= anio <= 2099 else None


class ClienteMusicBrainz:
    """Año del tema, país y comienzo del artista, verificados en MusicBrainz. Nunca lanza: sin dato, None."""

    def __init__(self, config: ConfigServicioDJ, cache: CacheHechos, reloj: Callable[[], float] = time.time,
                 dormir: Callable[[float], None] = time.sleep, version: str = "0.1"):
        self._config = config
        self._cache = cache
        self._reloj = reloj
        self._dormir = dormir
        self._version = version
        self._lock_ritmo = threading.Lock()
        self._ultimo = None
        self._avisado = False
        if not config.contacto.strip():
            _log.warning("cassette-dj: sin 'contacto' en config.toml no se consulta MusicBrainz "
                         "(se usa en el User-Agent que pide MusicBrainz)")

    def datos_del_tema(self, artista: str, titulo: str, isrc: str | None = None,
                       album: str | None = None) -> DatosTema | None:
        c = self._config
        if not c.contacto.strip() or not artista.strip() or not titulo.strip():
            return None
        isrc = isrc if isrc and _ISRC.fullmatch(isrc) else None
        n_artista, n_titulo = normalizar(_primer_artista(artista)), normalizar(_limpiar_titulo(titulo))
        if not n_artista or not n_titulo:
            return None            # sin letras con que comparar: no se puede verificar nada
        n_album = normalizar(album) if album else ""
        clave = f"mb:isrc:{isrc}" if isrc else f"mb:{n_artista}|{n_titulo}|{n_album}"
        fallo: list[Exception] = []

        buscado = []

        def buscar():
            try:
                valor = self._buscar(artista, titulo, isrc, album)
                buscado.append(1)
                return valor
            except _Fallo as e:
                fallo.append(e)
                return None
            except Exception as e:                      # nada debe escapar
                fallo.append(e)
                return None

        def vigencia(valor) -> float:
            if fallo:
                return c.cache_error_minutos * 60
            return (c.cache_datos_dias if valor is not None else c.cache_sin_dato_dias) * 86400

        valor = self._cache.consultar(clave, vigencia, buscar)
        if fallo:
            if not self._avisado:
                self._avisado = True
                _log.warning("MusicBrainz no respondió (%s): las frases siguen sin datos del tema", fallo[0])
            return None
        if buscado:
            self._avisado = False        # una consulta de verdad salió bien (no una respuesta de la caché)
        if not isinstance(valor, dict):
            return None
        try:
            return DatosTema(valor["anio"], valor["pais"], valor["anio_inicio_artista"], bool(valor["es_grupo"]),
                             str(valor["fuente"]))
        except KeyError:
            return None

    # --- consulta ---

    def _buscar(self, artista: str, titulo: str, isrc: str | None, album: str | None = None) -> dict | None:
        primero = _primer_artista(artista)
        limpio = _limpiar_titulo(titulo)
        grabaciones = []
        if isrc:
            try:
                grabaciones = self._filtrar(self._grabaciones(f"/isrc/{isrc}", {"inc": "artists", "fmt": "json"}),
                                            primero, None)
            except _NoExiste:
                grabaciones = []       # MusicBrainz no conoce ese ISRC: se busca por artista y título
        if not grabaciones:
            consulta = 'recording:"%s" AND artist:"%s"' % (_escapar(limpio), _escapar(primero))
            crudas = self._grabaciones("/recording", {"query": consulta, "limit": "25", "fmt": "json"})
            grabaciones = self._filtrar(crudas, primero, normalizar(limpio))
        if not grabaciones:
            return None
        confirmadas = self._del_album(grabaciones, album) if album else []
        if confirmadas:
            grabaciones = confirmadas
        elif normalizar(limpio) in _GENERICOS:
            return None            # "Intro", "Interlude"…: sin el álbum no se sabe de cuál se trata
        ids = {a["id"] for g in grabaciones for a in g["_artistas"]}
        if len(ids) != 1:
            return None            # dos artistas distintos con ese nombre: no se sabe cuál es
        id_artista = ids.pop()
        anios = [a for a in (_anio(g.get("first-release-date")) for g in grabaciones) if a is not None]
        anio = min(anios) if anios else None
        datos = self._pedir(f"/artist/{id_artista}", {"fmt": "json"})
        if not isinstance(datos, dict) or not ("id" in datos or "name" in datos):
            raise _Fallo("la respuesta del artista no es un artista")
        pais = datos.get("country")
        pais = pais if isinstance(pais, str) and re.fullmatch(r"[A-Z]{2}", pais) else None
        es_grupo = datos.get("type") == "Group"
        inicio = None
        vida = datos.get("life-span")
        if es_grupo and isinstance(vida, dict):
            inicio = _anio(vida.get("begin"))
        if anio is not None and inicio is not None and anio < inicio:
            anio = None
        if anio is None and pais is None and inicio is None:
            return None
        return {"anio": anio, "pais": pais, "anio_inicio_artista": inicio, "es_grupo": es_grupo,
                "fuente": f"https://musicbrainz.org/artist/{id_artista}"}

    def _grabaciones(self, ruta: str, parametros: dict) -> list:
        datos = self._pedir(ruta, parametros)
        crudas = datos.get("recordings") if isinstance(datos, dict) else None
        if not isinstance(crudas, list):
            raise _Fallo("la respuesta de MusicBrainz no trae 'recordings'")
        return crudas

    @staticmethod
    def _del_album(grabaciones: list[dict], album: str) -> list[dict]:
        """Las grabaciones que salieron en un disco con ese nombre (igual o uno dentro del otro: "(Deluxe)")."""
        buscado = normalizar(album)
        buenas = []
        for g in grabaciones:
            for r in g.get("releases") or []:
                titulo = normalizar(str(r.get("title", ""))) if isinstance(r, dict) else ""
                if titulo and (titulo == buscado or (min(len(titulo), len(buscado)) >= 4
                                                     and (titulo in buscado or buscado in titulo))):
                    buenas.append(g)
                    break
        return buenas

    @staticmethod
    def _filtrar(crudas: list, artista: str, titulo_normalizado: str | None) -> list[dict]:
        buscado = normalizar(artista)
        buenas = []
        for g in crudas:
            if not isinstance(g, dict):
                continue
            creditos = g.get("artist-credit")
            if not isinstance(creditos, list):
                continue
            artistas = [x["artist"] for x in creditos if isinstance(x, dict) and isinstance(x.get("artist"), dict)
                        and isinstance(x["artist"].get("id"), str) and _UUID.fullmatch(x["artist"]["id"])
                        and isinstance(x["artist"].get("name"), str)]
            coincide = [a for a in artistas if normalizar(a["name"]) == buscado]
            if not coincide:
                continue
            if titulo_normalizado is not None and normalizar(_limpiar_titulo(str(g.get("title", "")))) != titulo_normalizado:
                continue
            buenas.append(dict(g, _artistas=coincide))
        return buenas

    def _pedir(self, ruta: str, parametros: dict):
        c = self._config
        url = f"{c.musicbrainz_url.rstrip('/')}{ruta}?{urllib.parse.urlencode(parametros)}"
        req = urllib.request.Request(url, headers={"User-Agent": f"cassette-dj/{self._version} ({c.contacto})",
                                                   "Accept": "application/json"})
        with self._lock_ritmo:                       # a lo sumo un pedido por segundo
            if self._ultimo is not None:
                falta = INTERVALO_SEGUNDOS - (self._reloj() - self._ultimo)
                if falta > 0:
                    self._dormir(falta)
            self._ultimo = self._reloj()
        try:
            with urllib.request.urlopen(req, timeout=c.timeout_hechos_segundos) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise _NoExiste(f"HTTPError: {e}") from None
            raise _Fallo(f"HTTPError: {e}") from None
        except Exception as e:
            raise _Fallo(f"{type(e).__name__}: {e}") from None

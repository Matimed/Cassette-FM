import json
import logging
import os
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import mutagen

_log = logging.getLogger("cassette_fm")

EXTENSIONES = frozenset({".mp3", ".flac", ".ogg", ".m4a"})


@dataclass(frozen=True)
class Pista:
    ruta: Path
    duracion: float
    titulo: str
    fuente: str = "local"
    artista: str | None = None
    cancion: str | None = None  # solo el título del tag; `titulo` es "Artista - Título"
    album: str | None = None
    isrc: str | None = None


@dataclass(frozen=True)
class Estacion:
    nombre: str
    pistas: tuple[Pista, ...]


def _tag(tags, clave: str) -> str | None:
    valor = (tags.get(clave) or [None])[0]
    if not isinstance(valor, str):
        return None
    return valor.strip() or None


def leer_pista(ruta: Path) -> Pista | None:
    try:
        f = mutagen.File(ruta, easy=True)
    except Exception:
        return None
    if f is None or f.info is None or not f.info.length or f.info.length <= 0:
        return None
    tags = f.tags or {}
    titulo = _tag(tags, "title")
    artista = _tag(tags, "artist")
    if titulo and artista:
        texto = f"{artista} - {titulo}"
    else:
        texto = titulo or Path(ruta).stem
    return Pista(ruta=Path(ruta), duracion=float(f.info.length), titulo=texto, artista=artista,
                 cancion=titulo, album=_tag(tags, "album"), isrc=_tag(tags, "isrc"))


def clave_orden(nombre: str) -> str:
    """Orden alfabético sin mayúsculas ni acentos (\"Árbol\" va con la A)."""
    sin_acentos = "".join(c for c in unicodedata.normalize("NFD", nombre)
                          if unicodedata.category(c) != "Mn")
    return sin_acentos.casefold()


def _cargar_cache(cache: Path | None) -> dict:
    if cache is None:
        return {}
    try:
        datos = json.loads(Path(cache).read_text(encoding="utf-8"))
        return datos if isinstance(datos, dict) else {}
    except (OSError, ValueError):
        return {}


def _guardar_cache(cache: Path | None, datos: dict) -> None:
    if cache is None:
        return
    cache = Path(cache)
    cache.parent.mkdir(parents=True, exist_ok=True)
    tmp = cache.with_suffix(cache.suffix + ".tmp")
    tmp.write_text(json.dumps(datos, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, cache)


def _es_utf8(ruta: Path) -> bool:
    """mpv por IPC JSON y el caché solo manejan UTF-8; los demás nombres se saltean."""
    try:
        str(ruta).encode("utf-8")
        return True
    except UnicodeEncodeError:
        _log.warning("se ignora %r: el nombre no es UTF-8 válido", os.fsencode(ruta))
        return False


def _archivos_de_audio(carpeta: Path):
    for dirpath, dirnames, filenames in os.walk(carpeta):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for nombre in filenames:
            if not nombre.startswith(".") and Path(nombre).suffix.lower() in EXTENSIONES:
                ruta = Path(dirpath) / nombre
                if _es_utf8(ruta):
                    yield ruta


def _pista_con_cache(ruta: Path, previa: dict, nueva: dict) -> Pista | None:
    try:
        st = ruta.stat()
    except OSError:
        return None
    clave = str(ruta)
    entrada = previa.get(clave)
    if (isinstance(entrada, dict) and entrada.get("mtime_ns") == st.st_mtime_ns
            and entrada.get("tamano") == st.st_size
            and isinstance(entrada.get("duracion"), (int, float))
            and isinstance(entrada.get("titulo"), str) and "artista" in entrada):
        nueva[clave] = entrada
        return Pista(ruta=ruta, duracion=entrada["duracion"], titulo=entrada["titulo"],
                     artista=entrada["artista"], cancion=entrada.get("cancion"),
                     album=entrada.get("album"), isrc=entrada.get("isrc"))
    pista = leer_pista(ruta)
    if pista is not None:
        nueva[clave] = {"mtime_ns": st.st_mtime_ns, "tamano": st.st_size,
                        "duracion": pista.duracion, "titulo": pista.titulo, "artista": pista.artista,
                        "cancion": pista.cancion, "album": pista.album, "isrc": pista.isrc}
    return pista


def escanear(raiz: Path, cache: Path | None = None) -> list[Estacion]:
    raiz = Path(raiz)
    if not raiz.is_dir():
        return []
    previa = _cargar_cache(cache)
    nueva: dict = {}
    estaciones = []
    try:
        carpetas = list(raiz.iterdir())
    except OSError as e:
        _log.warning("no se puede leer %s: %s", raiz, e)
        return []
    for carpeta in carpetas:
        if not carpeta.is_dir() or carpeta.name.startswith(".") or not _es_utf8(carpeta):
            continue
        pistas = [p for r in _archivos_de_audio(carpeta)
                  if (p := _pista_con_cache(r, previa, nueva)) is not None]
        if pistas:
            pistas.sort(key=lambda p: str(p.ruta))
            estaciones.append(Estacion(carpeta.name, tuple(pistas)))
    estaciones.sort(key=lambda e: clave_orden(e.nombre))
    _guardar_cache(cache, nueva)
    return estaciones

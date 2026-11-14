"""Las emisoras de la radio: `estaciones.json` (nombre, fuente y ajustes del DJ de cada una)."""
import json
import logging
import os
import re
import threading
import tomllib
import unicodedata
from dataclasses import dataclass, field, replace
from pathlib import Path

from cassette_fm import biblioteca
from cassette_fm.biblioteca import Estacion
from cassette_fm.config import Config, ConfigDJ, ErrorConfig, Rutas, campos_dj

_log = logging.getLogger("cassette_fm")

_CAMPOS = {"nombre", "fuente", "dj"}
_PLAYLIST = re.compile(r"^(?:https?://open\.spotify\.com/(?:intl-[a-z-]+/)?playlist/|spotify:playlist:)"
                       r"([A-Za-z0-9]{22})(?:[?#].*)?$")


@dataclass(frozen=True)
class Fuente:
    tipo: str     # "carpeta" (valor: ruta absoluta) o "spotify" (valor: id de la playlist)
    valor: str


@dataclass(frozen=True)
class DefEmisora:
    nombre: str
    fuente: Fuente
    dj: ConfigDJ                                    # ya fusionado con el [dj] general
    dj_crudo: dict = field(default_factory=dict)   # la tabla "dj" tal como está en el archivo


def playlist_de(texto: str) -> str | None:
    """El id de una playlist de Spotify a partir de su link (con o sin ?si=…) o de su URI."""
    m = _PLAYLIST.match(texto.strip()) if isinstance(texto, str) else None
    return m.group(1) if m else None


def _normalizar(nombre: str) -> str:
    return unicodedata.normalize("NFC", nombre).casefold()


def _fuente(archivo: Path, nombre: str, valor) -> Fuente:
    donde = f'{archivo}: "{nombre}"'
    if not isinstance(valor, dict):
        raise ErrorConfig(f'{donde}: "fuente" tiene que ser un objeto con "carpeta" o "spotify"')
    if len(valor) != 1:
        raise ErrorConfig(f'{donde}: "fuente" tiene que tener una sola clave: "carpeta" o "spotify"')
    ((tipo, dato),) = valor.items()
    if tipo == "carpeta":
        if not isinstance(dato, str) or not dato.strip():
            raise ErrorConfig(f'{donde}: "carpeta" tiene que ser la ruta de una carpeta')
        try:
            ruta = Path(dato).expanduser()
        except RuntimeError:                     # "~Música/x": Python lo toma como el home de un usuario "Música"
            raise ErrorConfig(f'{donde}: no se puede expandir "{dato}" (¿faltó la barra después de ~?)') from None
        if not ruta.is_absolute():
            raise ErrorConfig(f'{donde}: "carpeta" tiene que ser una ruta absoluta (o empezar con ~): {dato}')
        return Fuente("carpeta", str(ruta))
    if tipo == "spotify":
        id_ = playlist_de(dato)
        if id_ is None:
            raise ErrorConfig(f'{donde}: "spotify" tiene que ser el link o la URI de una playlist')
        return Fuente("spotify", id_)
    raise ErrorConfig(f'{donde}: la fuente "{tipo}" no existe (tiene que ser "carpeta" o "spotify")')


def leer_emisoras(archivo: Path, general: ConfigDJ) -> list[DefEmisora]:
    """Lee y valida `estaciones.json`; cualquier problema es un ErrorConfig que nombra el archivo."""
    archivo = Path(archivo)
    try:
        datos = json.loads(archivo.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ErrorConfig(f"{archivo}: línea {e.lineno}, columna {e.colno}: {e.msg}") from None
    except (OSError, UnicodeDecodeError) as e:
        raise ErrorConfig(f"{archivo}: {e}") from None
    if not isinstance(datos, list):
        raise ErrorConfig(f"{archivo}: tiene que ser una lista de emisoras ([{{…}}, {{…}}])")
    emisoras, vistos = [], set()
    for i, item in enumerate(datos, 1):
        if not isinstance(item, dict):
            raise ErrorConfig(f"{archivo}: la emisora n.º {i} tiene que ser un objeto {{…}}")
        nombre = item.get("nombre")
        if not isinstance(nombre, str) or not nombre.strip():
            raise ErrorConfig(f'{archivo}: la emisora n.º {i} no tiene "nombre"')
        nombre = nombre.strip()
        sobrantes = set(item) - _CAMPOS
        if sobrantes:
            raise ErrorConfig(f'{archivo}: "{nombre}": campo desconocido: {", ".join(sorted(sobrantes))}')
        if _normalizar(nombre) in vistos:
            raise ErrorConfig(f'{archivo}: el nombre "{nombre}" está repetido')
        vistos.add(_normalizar(nombre))
        if "fuente" not in item:
            raise ErrorConfig(f'{archivo}: "{nombre}" no tiene "fuente"')
        fuente = _fuente(archivo, nombre, item["fuente"])
        crudo = item.get("dj", {})
        if not isinstance(crudo, dict):
            raise ErrorConfig(f'{archivo}: "{nombre}": "dj" tiene que ser un objeto con ajustes del DJ')
        dj = replace(general, **campos_dj(archivo, crudo, f'"{nombre}".dj.', general))
        emisoras.append(DefEmisora(nombre, fuente, dj, crudo))
    return emisoras


def _ajustes_del_toml(toml: Path) -> dict:
    try:
        with open(toml, "rb") as f:
            datos = tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError):
        return {}
    estaciones = (datos.get("dj") or {}).get("estaciones") if isinstance(datos.get("dj"), dict) else None
    return {k: v for k, v in estaciones.items() if isinstance(v, dict)} if isinstance(estaciones, dict) else {}


def migrar_emisoras(archivo: Path, raiz: Path, toml: Path) -> bool:
    """La primera vez: escribe `archivo` con las subcarpetas de `raiz` (como eran las estaciones hasta ahora) y los
    `[dj.estaciones."X"]` del `toml`. No pisa un archivo existente; sin carpetas no escribe nada."""
    archivo = Path(archivo)
    if archivo.exists():
        return False
    carpetas = biblioteca.carpetas_de_estaciones(raiz)
    if not carpetas:
        return False
    ajustes = _ajustes_del_toml(toml)
    emisoras = []
    for carpeta in carpetas:
        e = {"nombre": carpeta.name, "fuente": {"carpeta": str(carpeta)}}
        if carpeta.name in ajustes:
            e["dj"] = ajustes[carpeta.name]
        emisoras.append(e)
    for nombre in sorted(set(ajustes) - {c.name for c in carpetas}):
        _log.warning("los ajustes del DJ de %r no se migraron: no hay una carpeta con ese nombre en %s", nombre, raiz)
    archivo.parent.mkdir(parents=True, exist_ok=True)
    tmp = archivo.with_name(archivo.name + ".tmp")
    tmp.write_text(json.dumps(emisoras, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, archivo)
    _log.info("se migraron %d emisoras a %s", len(emisoras), archivo)
    return True


class Catalogo:
    """Las emisoras vigentes: relee `estaciones.json` en cada escaneo (lo migra la primera vez) y da los ajustes del
    DJ de cada una. Si el archivo está roto, el escaneo lanza ErrorConfig y lo anterior queda como estaba."""

    def __init__(self, config: Config, rutas: Rutas, spotify=None, reproduce_spotify: bool = False):
        self._config = config
        self._rutas = rutas
        self._spotify = spotify                    # CatalogoSpotify (o None: las emisoras de Spotify se omiten)
        self._reproduce_spotify = reproduce_spotify   # hasta la parte 4c no hay reproductor de Spotify
        self._dj: dict[str, ConfigDJ] = {}
        self._lock = threading.Lock()
        self._avisado_toml = False

    def escanear(self) -> list[Estacion]:
        archivo = self._rutas.emisoras
        existia = archivo.exists()
        if not existia and not migrar_emisoras(archivo, self._config.raiz_musica, self._rutas.config):
            return []
        emisoras = leer_emisoras(archivo, self._config.dj)
        if existia and self._config.estaciones_dj and not self._avisado_toml:
            self._avisado_toml = True
            _log.warning("[dj.estaciones] del config.toml se ignora: los ajustes de cada emisora están en %s",
                         archivo)
        locales = {e.nombre: e for e in biblioteca.escanear_carpetas(
            [(e.nombre, Path(e.fuente.valor)) for e in emisoras if e.fuente.tipo == "carpeta"], self._rutas.cache)}
        estaciones = []
        for e in emisoras:
            if e.fuente.tipo == "carpeta":
                if e.nombre in locales:
                    estaciones.append(locales[e.nombre])
                continue
            estacion = self._de_spotify(e)
            if estacion is None:
                continue
            if self._reproduce_spotify:
                estaciones.append(estacion)
            else:
                _log.info("la emisora %r tiene %d temas de Spotify listos; la reproducción llega en la parte 4c",
                          e.nombre, len(estacion.pistas))
        with self._lock:
            self._dj = {e.nombre: e.dj for e in emisoras}
        return estaciones

    def _de_spotify(self, e: DefEmisora) -> Estacion | None:
        from cassette_fm.spotify.api import ErrorSpotify
        if self._spotify is None:
            _log.warning("la emisora %r es de Spotify y no hay catálogo de Spotify: se omite", e.nombre)
            return None
        try:
            pistas = self._spotify.pistas(e.fuente.valor)
        except ErrorSpotify as error:
            _log.warning("la emisora %r: %s", e.nombre, error)
            return None
        if not pistas:
            _log.warning("la playlist de %r no tiene temas que se puedan escuchar", e.nombre)
            return None
        return Estacion(e.nombre, tuple(pistas), fuente="spotify")

    def configuracion_dj(self, nombre: str) -> ConfigDJ:
        with self._lock:
            return self._dj.get(nombre, self._config.dj)

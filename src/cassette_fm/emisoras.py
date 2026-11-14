"""Las emisoras de la radio: `estaciones.json` (nombre, fuente y ajustes del DJ de cada una)."""
import json
import re
import unicodedata
from dataclasses import dataclass, field, replace
from pathlib import Path

from cassette_fm.config import ConfigDJ, ErrorConfig, campos_dj

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
        ruta = Path(dato).expanduser()
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

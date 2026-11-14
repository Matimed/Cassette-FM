import os
import re
from collections.abc import Mapping
import tomllib
import zoneinfo
from dataclasses import dataclass, field, fields, replace
from pathlib import Path

from cassette_fm.config import ErrorConfig


@dataclass(frozen=True)
class ConfigServicioDJ:
    host: str = "127.0.0.1"
    puerto: int = 7720
    trabajadores: int = 1
    retencion_minutos: float = 60.0          # cuánto se conserva un resultado terminado
    descargar_tras_minutos: float = 5.0      # Kokoro se descarga tras este tiempo sin trabajo
    modelos_dir: Path = Path.home() / ".local/share/cassette-dj/modelos"
    palabras_maximas: int = 45
    velocidad: float = 1.05
    pausa_oracion_segundos: float = 0.25     # `sentence_pause` de Kokoro
    pausa_coma_segundos: float = 0.1         # `clause_pause` de Kokoro
    continuo: bool = False                   # `continuous` de Kokoro
    zona_horaria: str = "America/Argentina/Buenos_Aires"
    piper_pausa_coma_segundos: float = 0.15     # silencio en cada coma (Piper no hace pausas por sí solo)
    piper_pausa_oracion_segundos: float = 0.4   # silencio entre oraciones
    voces: Mapping[str, str] = field(default_factory=dict)   # voces con nombre: alias -> voz o mezcla ("em_alex+em_santa")


@dataclass(frozen=True)
class RutasDJ:
    config: Path      # archivo de configuración
    estado: Path      # directorio de estado
    clips: Path       # directorio de clips

    @property
    def guiones(self) -> Path:
        return self.estado / "guiones.jsonl"

    @property
    def lexico(self) -> Path:
        return self.config.parent / "lexico.toml"


def _xdg(variable: str, por_defecto: Path) -> Path:
    valor = os.environ.get(variable)
    return Path(valor) if valor else por_defecto


def rutas_dj() -> RutasDJ:
    home = Path.home()
    return RutasDJ(
        config=_xdg("XDG_CONFIG_HOME", home / ".config") / "cassette-dj" / "config.toml",
        estado=_xdg("XDG_STATE_HOME", home / ".local" / "state") / "cassette-dj",
        clips=_xdg("XDG_CACHE_HOME", home / ".cache") / "cassette-dj" / "clips",
    )


_TIPOS = {c.name: {"host": str, "modelos_dir": str, "zona_horaria": str, "continuo": bool,
                   "puerto": int, "trabajadores": int, "palabras_maximas": int}.get(c.name, float)
          for c in fields(ConfigServicioDJ)}
_NOMBRE_TIPO = {str: "un texto", int: "un número entero", float: "un número", bool: "true o false"}


def cargar_config_dj(archivo: Path) -> ConfigServicioDJ:
    try:
        with open(archivo, "rb") as f:
            datos = tomllib.load(f)
    except FileNotFoundError:
        return ConfigServicioDJ()
    except (tomllib.TOMLDecodeError, OSError) as e:
        raise ErrorConfig(f"{archivo}: {e}")
    voces = _leer_voces(archivo, datos.pop("voces", {}))
    campos = {}
    for clave, valor in datos.items():
        tipo = _TIPOS.get(clave)
        if tipo is None:
            continue   # clave desconocida: se ignora
        if tipo is float:
            ok = isinstance(valor, (int, float)) and not isinstance(valor, bool)
        elif tipo is int:
            ok = isinstance(valor, int) and not isinstance(valor, bool)
        else:
            ok = isinstance(valor, tipo)
        if not ok:
            raise ErrorConfig(f"{archivo}: '{clave}' tiene que ser {_NOMBRE_TIPO[tipo]}")
        campos[clave] = float(valor) if tipo is float else valor
    _validar(archivo, campos)
    if "modelos_dir" in campos:
        campos["modelos_dir"] = Path(campos["modelos_dir"]).expanduser()
    return replace(ConfigServicioDJ(), voces=voces, **campos)


_NOMBRE_VOZ = re.compile(r"[A-Za-z0-9_.-]+")
_ESPECIFICACION_VOZ = re.compile(r"[A-Za-z0-9_+.:-]+")


def _leer_voces(archivo: Path, tabla) -> dict[str, str]:
    if not isinstance(tabla, dict):
        raise ErrorConfig(f"{archivo}: 'voces' tiene que ser una tabla de nombre = voz")
    for nombre, voz in tabla.items():
        if not _NOMBRE_VOZ.fullmatch(nombre):
            raise ErrorConfig(f"{archivo}: el nombre de voz {nombre!r} solo puede tener letras, números, _ . -")
        if not isinstance(voz, str) or not _ESPECIFICACION_VOZ.fullmatch(voz) or ".." in voz:
            raise ErrorConfig(f"{archivo}: la voz {nombre!r} tiene que ser una voz de Kokoro, una mezcla (a+b) "
                              f"o piper:<modelo>")
        if any(parte in tabla for parte in voz.split("+")):
            raise ErrorConfig(f"{archivo}: la voz {nombre!r} no puede apuntar a otra voz con nombre")
    return dict(tabla)


def _validar(archivo: Path, c: dict) -> None:
    def error(clave, motivo):
        raise ErrorConfig(f"{archivo}: '{clave}' {motivo}")

    if "puerto" in c and not 1 <= c["puerto"] <= 65535:
        error("puerto", "tiene que estar entre 1 y 65535")
    if "trabajadores" in c and c["trabajadores"] < 1:
        error("trabajadores", "tiene que ser al menos 1")
    if "palabras_maximas" in c and c["palabras_maximas"] < 5:
        error("palabras_maximas", "tiene que ser al menos 5")
    if "velocidad" in c and not 0.5 <= c["velocidad"] <= 2.0:
        error("velocidad", "tiene que estar entre 0,5 y 2")
    if "retencion_minutos" in c and c["retencion_minutos"] <= 0:
        error("retencion_minutos", "tiene que ser mayor que 0")
    for clave in ("pausa_oracion_segundos", "pausa_coma_segundos", "descargar_tras_minutos",
                  "piper_pausa_coma_segundos", "piper_pausa_oracion_segundos"):
        if clave in c and c[clave] < 0:
            error(clave, "no puede ser negativo")
    if "modelos_dir" in c:
        ruta = Path(c["modelos_dir"]).expanduser()
        if not c["modelos_dir"].strip() or not ruta.is_absolute():
            error("modelos_dir", "tiene que ser una ruta absoluta (o empezar con ~)")
    if "host" in c and not c["host"].strip():
        error("host", "no puede estar vacío")
    if "zona_horaria" in c:
        try:
            zoneinfo.ZoneInfo(c["zona_horaria"])
        except (zoneinfo.ZoneInfoNotFoundError, ValueError):
            error("zona_horaria", "no es una zona horaria conocida")

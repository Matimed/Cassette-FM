import os
import re
from collections.abc import Mapping
import tomllib
import zoneinfo
from dataclasses import dataclass, field, fields, replace
from pathlib import Path

from cassette_fm.config import ErrorConfig


PESOS_POR_DEFECTO: Mapping[str, float] = {"estacion": 0.5, "hora": 0.35, "momento": 0.3, "album": 0.3,
                                          "anterior": 0.3, "clima": 0.12, "dato": 0.25}


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
    contacto: str = ""                      # va en el User-Agent de MusicBrainz; vacío = no se consulta
    musicbrainz_url: str = "https://musicbrainz.org/ws/2"
    open_meteo_url: str = "https://api.open-meteo.com/v1/forecast"
    latitud: float = -34.6037               # Buenos Aires
    longitud: float = -58.3816
    timeout_hechos_segundos: float = 5.0
    cache_clima_minutos: float = 15.0
    cache_datos_dias: float = 90.0          # dato encontrado
    cache_sin_dato_dias: float = 14.0       # la consulta funcionó y no dio nada
    cache_error_minutos: float = 10.0       # la red falló: no reintentar enseguida
    ingredientes_max: int = 3               # cuántos ingredientes combina una frase (el tema cuenta)
    penalizacion_reciente: float = 0.3      # cada aparición en `recientes` multiplica el peso por esto
    pesos_ingredientes: Mapping[str, float] = field(default_factory=lambda: dict(PESOS_POR_DEFECTO))
    modo: str = "plantillas"                           # "plantillas" | "llm": modo al arrancar
    llm_url: str = "http://127.0.0.1:11434/v1"         # API compatible con OpenAI (Ollama)
    llm_modelo: str = "gemma3:4b"
    llm_timeout_segundos: float = 240.0                # tope por llamada al LLM
    llm_intentos: int = 2                              # cuántas veces se pide una frase antes de usar la plantilla
    llm_temperatura: float = 0.8
    llm_margen_segundos: float = 45.0                  # lo que se reserva antes de la voz para sintetizar y registrar
    wikipedia_dias: float = 90.0                       # vigencia en caché de un resumen encontrado
    wikipedia_palabras_maximas: int = 120              # el resumen se recorta (en un fin de oración) a esto
    wikipedia_url: str = "https://{idioma}.wikipedia.org"
    wikidata_url: str = "https://www.wikidata.org/w/api.php"
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
    def hechos(self) -> Path:
        return self.estado / "hechos.sqlite"

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
                   "puerto": int, "trabajadores": int, "palabras_maximas": int,
                   "contacto": str, "musicbrainz_url": str, "open_meteo_url": str, "ingredientes_max": int,
                   "modo": str, "llm_url": str, "llm_modelo": str, "llm_intentos": int,
                   "wikipedia_palabras_maximas": int, "wikipedia_url": str, "wikidata_url": str}.get(c.name, float)
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
    pesos = _leer_pesos(archivo, datos.pop("ingredientes", {}))
    datos.pop("pesos_ingredientes", None)
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
    return replace(ConfigServicioDJ(), voces=voces, pesos_ingredientes=pesos, **campos)


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


def _leer_pesos(archivo: Path, tabla) -> dict[str, float]:
    if not isinstance(tabla, dict):
        raise ErrorConfig(f"{archivo}: 'ingredientes' tiene que ser una tabla de ingrediente = peso")
    pesos = dict(PESOS_POR_DEFECTO)
    for nombre, peso in tabla.items():
        if nombre not in PESOS_POR_DEFECTO:
            raise ErrorConfig(f"{archivo}: ingrediente desconocido {nombre!r} (los válidos son: "
                              f"{', '.join(PESOS_POR_DEFECTO)}; la canción siempre va)")
        if isinstance(peso, bool) or not isinstance(peso, (int, float)) or not 0 <= peso <= 1:
            raise ErrorConfig(f"{archivo}: el peso de {nombre!r} tiene que ser un número entre 0 y 1")
        pesos[nombre] = float(peso)
    return pesos


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
    if "timeout_hechos_segundos" in c and c["timeout_hechos_segundos"] <= 0:
        error("timeout_hechos_segundos", "tiene que ser mayor que 0")
    if "ingredientes_max" in c and c["ingredientes_max"] < 1:
        error("ingredientes_max", "tiene que ser al menos 1")
    if "penalizacion_reciente" in c and not 0 <= c["penalizacion_reciente"] <= 1:
        error("penalizacion_reciente", "tiene que estar entre 0 y 1")
    if "latitud" in c and not -90 <= c["latitud"] <= 90:
        error("latitud", "tiene que estar entre -90 y 90")
    if "longitud" in c and not -180 <= c["longitud"] <= 180:
        error("longitud", "tiene que estar entre -180 y 180")
    for clave in ("cache_clima_minutos", "cache_datos_dias", "cache_sin_dato_dias", "cache_error_minutos"):
        if clave in c and c[clave] < 0:
            error(clave, "no puede ser negativo")
    if "modo" in c and c["modo"] not in ("plantillas", "llm"):
        error("modo", 'tiene que ser "plantillas" o "llm"')
    if "llm_modelo" in c and not re.fullmatch(r"\S{1,100}", c["llm_modelo"]):
        error("llm_modelo", "tiene que ser el nombre de un modelo (sin espacios, hasta 100 caracteres)")
    if "llm_timeout_segundos" in c and c["llm_timeout_segundos"] <= 0:
        error("llm_timeout_segundos", "tiene que ser mayor que 0")
    if "llm_intentos" in c and c["llm_intentos"] < 1:
        error("llm_intentos", "tiene que ser al menos 1")
    if "llm_temperatura" in c and not 0 <= c["llm_temperatura"] <= 2:
        error("llm_temperatura", "tiene que estar entre 0 y 2")
    if "wikipedia_dias" in c and c["wikipedia_dias"] < 0:
        error("wikipedia_dias", "no puede ser negativo")
    if "wikipedia_palabras_maximas" in c and c["wikipedia_palabras_maximas"] < 20:
        error("wikipedia_palabras_maximas", "tiene que ser al menos 20")
    if "llm_margen_segundos" in c and c["llm_margen_segundos"] < 0:
        error("llm_margen_segundos", "no puede ser negativo")
    if "wikipedia_url" in c:
        try:
            ok = "{idioma}" in c["wikipedia_url"] and bool(c["wikipedia_url"].format(idioma="es"))
        except (KeyError, IndexError, ValueError):
            ok = False
        if not ok:
            error("wikipedia_url", "tiene que llevar {idioma} y ningún otro marcador (por ejemplo "
                                   "https://{idioma}.wikipedia.org)")
    for clave in ("llm_url", "wikidata_url", "wikipedia_url"):
        if clave in c and not re.fullmatch(r"https?://\S+", c[clave]):
            error(clave, "tiene que empezar con http:// o https://")
    for clave in ("musicbrainz_url", "open_meteo_url"):
        if clave in c and not re.fullmatch(r"https?://\S+", c[clave]):
            error(clave, "tiene que empezar con http:// o https://")
    if "host" in c and not c["host"].strip():
        error("host", "no puede estar vacío")
    if "zona_horaria" in c:
        try:
            zoneinfo.ZoneInfo(c["zona_horaria"])
        except (zoneinfo.ZoneInfoNotFoundError, ValueError):
            error("zona_horaria", "no es una zona horaria conocida")

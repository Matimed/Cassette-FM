import json
import os
import re
import tomllib
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field, fields, replace
from pathlib import Path


class ErrorConfig(Exception):
    pass


@dataclass(frozen=True)
class Frecuencia:
    """Cada cuánto habla el DJ: entre `min` y `max` temas (o minutos) desde la última intervención."""
    modo: str = "temas"   # "temas" | "minutos"
    min: float = 2.0
    max: float = 3.0


@dataclass(frozen=True)
class ConfigDJ:
    """Parámetros del DJ; todos se pueden pisar por estación (`[dj.estaciones."X"]`)."""
    activo: bool = False
    duracion_maxima_segundos: float = 15.0
    retraso_voz_segundos: float = 1.0
    nivel_musica_con_voz: float = 0.35
    rampa_bajada_segundos: float = 0.4
    rampa_subida_segundos: float = 1.0
    minimo_restante_segundos: float = 1.5
    tolerancia_desfase_segundos: float = 60.0
    desfase_aviso_segundos: float = 5.0
    margen_seguridad_voz_segundos: float = 2.0   # el temporizador que restaura la música espera esto de más
    url: str = ""   # servicio DJ (cassette-dj); vacío = la radio no planifica intervenciones
    margen_minutos: float = 6.0   # antes de esto no se agenda nada (da tiempo a generar el clip)
    frecuencia: Frecuencia = Frecuencia()
    voz: str = "em_santa"
    idioma: str = "es"
    personalidad: str = ""
    timeout_http_segundos: float = 10.0
    espera_reintento_segundos: float = 5.0   # primera espera tras un fallo del servicio
    espera_reintento_maxima_segundos: float = 300.0   # tope de la espera creciente
    espera_trabajo_maxima_segundos: float = 600.0   # un trabajo que tarda más que esto se cancela
    recientes_cantidad: int = 6   # cuántos ingredientes recordar por estación


@dataclass(frozen=True)
class Config:
    raiz_musica: Path = Path.home() / "Música"
    puerto: int = 7710
    avisos: bool = True
    normalizar: bool = True   # filtro dynaudnorm de mpv: parejiza el volumen entre temas
    dj: ConfigDJ = ConfigDJ()
    estaciones_dj: Mapping[str, ConfigDJ] = field(default_factory=dict)   # overrides ya fusionados


def configuracion_dj(config: Config, estacion: str) -> ConfigDJ:
    return config.estaciones_dj.get(estacion, config.dj)


@dataclass
class Estado:
    estacion: str | None = None
    volumen: int = 70


@dataclass(frozen=True)
class Rutas:
    config: Path
    estado: Path
    cache: Path
    runtime: Path

    @property
    def intervenciones(self) -> Path:
        return self.estado.parent / "intervenciones.json"

    @property
    def clips(self) -> Path:
        return self.cache.parent / "dj"

    @property
    def planificador(self) -> Path:
        return self.estado.parent / "planificador.json"


def _xdg(variable: str, por_defecto: Path) -> Path:
    valor = os.environ.get(variable)
    return Path(valor) if valor else por_defecto


def rutas() -> Rutas:
    home = Path.home()
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    return Rutas(
        config=_xdg("XDG_CONFIG_HOME", home / ".config") / "cassette-fm" / "config.toml",
        estado=_xdg("XDG_STATE_HOME", home / ".local" / "state") / "cassette-fm" / "estado.json",
        cache=_xdg("XDG_CACHE_HOME", home / ".cache") / "cassette-fm" / "duraciones.json",
        runtime=(Path(runtime) / "cassette-fm" if runtime
                 else Path(f"/tmp/cassette-fm-{os.getuid()}")),
    )


_NOMBRE_TIPO = {str: "un texto", int: "un número entero", bool: "true o false"}


def cargar_config(archivo: Path) -> Config:
    try:
        with open(archivo, "rb") as f:
            datos = tomllib.load(f)
    except FileNotFoundError:
        return Config()
    except (tomllib.TOMLDecodeError, OSError) as e:
        raise ErrorConfig(f"{archivo}: {e}")
    tabla_dj = datos.pop("dj", None)
    conocidas = {"raiz_musica", "puerto", "avisos", "normalizar"}
    datos = {k: v for k, v in datos.items() if k in conocidas}
    for clave, valor in datos.items():
        tipo = {"raiz_musica": str, "puerto": int, "avisos": bool, "normalizar": bool}[clave]
        if not isinstance(valor, tipo) or (tipo is int and isinstance(valor, bool)):
            raise ErrorConfig(f"{archivo}: '{clave}' tiene que ser {_NOMBRE_TIPO[tipo]}")
    if "puerto" in datos and not 1 <= datos["puerto"] <= 65535:
        raise ErrorConfig(f"{archivo}: 'puerto' tiene que estar entre 1 y 65535")
    if "raiz_musica" in datos:
        datos["raiz_musica"] = Path(datos["raiz_musica"]).expanduser()
    dj, por_estacion = _leer_dj(archivo, tabla_dj)
    return Config(**datos, dj=dj, estaciones_dj=por_estacion)


_CAMPOS_NUMERICOS_DJ = {c.name for c in fields(ConfigDJ)
                        if c.type in (float, "float") and c.name != "frecuencia"}
_POSITIVOS = {"duracion_maxima_segundos", "tolerancia_desfase_segundos", "desfase_aviso_segundos",
              "timeout_http_segundos", "espera_reintento_segundos", "espera_reintento_maxima_segundos",
              "espera_trabajo_maxima_segundos"}
_IDIOMAS = ("es", "en", "en-us", "en-gb")
_VOZ = re.compile(r"^[A-Za-z0-9_+.-]+$")
_PERSONALIDAD_MAXIMA = 300


def _numero(archivo: Path, clave: str, valor) -> float:
    if isinstance(valor, bool) or not isinstance(valor, (int, float)):
        raise ErrorConfig(f"{archivo}: '{clave}' tiene que ser un número")
    return float(valor)


def _texto(archivo: Path, clave: str, valor) -> str:
    if not isinstance(valor, str):
        raise ErrorConfig(f"{archivo}: '{clave}' tiene que ser un texto")
    return valor


def _frecuencia(archivo: Path, base: Frecuencia, tabla, donde: str) -> Frecuencia:
    clave = f"{donde}frecuencia"
    if not isinstance(tabla, dict):
        raise ErrorConfig(f"{archivo}: '{clave}' tiene que ser una tabla (modo, min, max)")
    campos = {}
    if "modo" in tabla:
        modo = _texto(archivo, f"{clave}.modo", tabla["modo"])
        if modo not in ("temas", "minutos"):
            raise ErrorConfig(f"{archivo}: '{clave}.modo' tiene que ser \"temas\" o \"minutos\"")
        campos["modo"] = modo
    for nombre in ("min", "max"):
        if nombre in tabla:
            campos[nombre] = _numero(archivo, f"{clave}.{nombre}", tabla[nombre])
    f = replace(base, **campos)
    for nombre in ("min", "max"):
        if getattr(f, nombre) <= 0:
            raise ErrorConfig(f"{archivo}: '{clave}.{nombre}' tiene que ser mayor que 0")
        if f.modo == "temas" and (getattr(f, nombre) != int(getattr(f, nombre))):
            raise ErrorConfig(f"{archivo}: '{clave}.{nombre}' tiene que ser un número entero (cantidad de temas)")
    if f.min > f.max:
        raise ErrorConfig(f"{archivo}: '{clave}.min' no puede ser mayor que 'max'")
    return f


def _campos_dj(archivo: Path, tabla: dict, donde: str, base: ConfigDJ) -> dict:
    campos = {}
    for clave, valor in tabla.items():
        nombre = f"{donde}{clave}"
        if clave == "activo":
            if not isinstance(valor, bool):
                raise ErrorConfig(f"{archivo}: '{nombre}' tiene que ser true o false")
            campos[clave] = valor
        elif clave in _CAMPOS_NUMERICOS_DJ:
            valor = _numero(archivo, nombre, valor)
            if clave == "nivel_musica_con_voz" and not 0 < valor <= 1:
                raise ErrorConfig(f"{archivo}: '{nombre}' tiene que estar entre 0 (sin incluir) y 1")
            if clave in _POSITIVOS and valor <= 0:
                raise ErrorConfig(f"{archivo}: '{nombre}' tiene que ser mayor que 0")
            if valor < 0:
                raise ErrorConfig(f"{archivo}: '{nombre}' no puede ser negativo")
            campos[clave] = valor
        elif clave == "recientes_cantidad":
            if isinstance(valor, bool) or not isinstance(valor, int) or valor < 0:
                raise ErrorConfig(f"{archivo}: '{nombre}' tiene que ser un número entero, 0 o más")
            campos[clave] = valor
        elif clave == "url":
            valor = _texto(archivo, nombre, valor)
            if valor and not re.match(r"^https?://\S+$", valor):
                raise ErrorConfig(f"{archivo}: '{nombre}' tiene que empezar con http:// o https:// (o quedar vacía)")
            campos[clave] = valor
        elif clave == "voz":
            valor = _texto(archivo, nombre, valor)
            if not _VOZ.match(valor):
                raise ErrorConfig(f"{archivo}: '{nombre}' solo puede tener letras, números y _ + . -")
            campos[clave] = valor
        elif clave == "idioma":
            valor = _texto(archivo, nombre, valor)
            if valor not in _IDIOMAS:
                raise ErrorConfig(f"{archivo}: '{nombre}' tiene que ser uno de: {', '.join(_IDIOMAS)}")
            campos[clave] = valor
        elif clave == "personalidad":
            valor = _texto(archivo, nombre, valor)
            if len(valor) > _PERSONALIDAD_MAXIMA:
                raise ErrorConfig(f"{archivo}: '{nombre}' admite hasta {_PERSONALIDAD_MAXIMA} caracteres")
            campos[clave] = valor
        elif clave == "frecuencia":
            campos[clave] = _frecuencia(archivo, base.frecuencia, valor, donde)
        # el resto (palabras_maximas, claves de partes siguientes) se ignora
    if {"espera_reintento_segundos", "espera_reintento_maxima_segundos"} & campos.keys():
        f = replace(base, **campos)
        if f.espera_reintento_segundos > f.espera_reintento_maxima_segundos:
            raise ErrorConfig(f"{archivo}: '{donde}espera_reintento_segundos' no puede superar "
                              f"'espera_reintento_maxima_segundos'")
    return campos


def _leer_dj(archivo: Path, tabla) -> tuple[ConfigDJ, dict[str, ConfigDJ]]:
    if tabla is None:
        return ConfigDJ(), {}
    if not isinstance(tabla, dict):
        raise ErrorConfig(f"{archivo}: 'dj' tiene que ser una tabla")
    estaciones = tabla.get("estaciones", {})
    if not isinstance(estaciones, dict):
        raise ErrorConfig(f"{archivo}: 'dj.estaciones' tiene que ser una tabla con una tabla por estación")
    general = replace(ConfigDJ(), **_campos_dj(archivo, tabla, "dj.", ConfigDJ()))
    por_estacion = {}
    for nombre, t in estaciones.items():
        if not isinstance(t, dict):
            raise ErrorConfig(f"{archivo}: 'dj.estaciones.{nombre}' tiene que ser una tabla")
        por_estacion[nombre] = replace(general, **_campos_dj(archivo, t, f"dj.estaciones.{nombre}.", general))
    return general, por_estacion


def cargar_estado(archivo: Path) -> Estado:
    try:
        datos = json.loads(Path(archivo).read_text(encoding="utf-8"))
        return Estado(estacion=datos.get("estacion"), volumen=int(datos.get("volumen", 70)))
    except (OSError, ValueError, AttributeError, TypeError):
        return Estado()


def guardar_estado(archivo: Path, estado: Estado) -> None:
    archivo = Path(archivo)
    archivo.parent.mkdir(parents=True, exist_ok=True)
    tmp = archivo.with_suffix(archivo.suffix + ".tmp")
    tmp.write_text(json.dumps(asdict(estado), ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, archivo)

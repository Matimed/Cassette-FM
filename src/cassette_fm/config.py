import json
import os
import tomllib
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field, fields, replace
from pathlib import Path


class ErrorConfig(Exception):
    pass


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


_TIPOS_DJ = {c.name: (bool if c.type in (bool, "bool") else float) for c in fields(ConfigDJ)}
_POSITIVOS = {"duracion_maxima_segundos", "tolerancia_desfase_segundos", "desfase_aviso_segundos"}


def _campos_dj(archivo: Path, tabla: dict, donde: str) -> dict:
    campos = {}
    for clave, valor in tabla.items():
        tipo = _TIPOS_DJ.get(clave)
        if tipo is None:
            continue   # claves de las partes siguientes (url, frecuencia, voz…): se ignoran
        if tipo is bool:
            if not isinstance(valor, bool):
                raise ErrorConfig(f"{archivo}: '{donde}{clave}' tiene que ser true o false")
            campos[clave] = valor
            continue
        if isinstance(valor, bool) or not isinstance(valor, (int, float)):
            raise ErrorConfig(f"{archivo}: '{donde}{clave}' tiene que ser un número")
        valor = float(valor)
        if clave == "nivel_musica_con_voz" and not 0 < valor <= 1:
            raise ErrorConfig(f"{archivo}: '{donde}{clave}' tiene que estar entre 0 (sin incluir) y 1")
        if clave in _POSITIVOS and valor <= 0:
            raise ErrorConfig(f"{archivo}: '{donde}{clave}' tiene que ser mayor que 0")
        if valor < 0:
            raise ErrorConfig(f"{archivo}: '{donde}{clave}' no puede ser negativo")
        campos[clave] = valor
    return campos


def _leer_dj(archivo: Path, tabla) -> tuple[ConfigDJ, dict[str, ConfigDJ]]:
    if tabla is None:
        return ConfigDJ(), {}
    if not isinstance(tabla, dict):
        raise ErrorConfig(f"{archivo}: 'dj' tiene que ser una tabla")
    estaciones = tabla.get("estaciones", {})
    if not isinstance(estaciones, dict):
        raise ErrorConfig(f"{archivo}: 'dj.estaciones' tiene que ser una tabla con una tabla por estación")
    general = replace(ConfigDJ(), **_campos_dj(archivo, tabla, "dj."))
    por_estacion = {}
    for nombre, t in estaciones.items():
        if not isinstance(t, dict):
            raise ErrorConfig(f"{archivo}: 'dj.estaciones.{nombre}' tiene que ser una tabla")
        por_estacion[nombre] = replace(general, **_campos_dj(archivo, t, f"dj.estaciones.{nombre}."))
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

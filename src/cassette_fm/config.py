import json
import os
import tomllib
from dataclasses import asdict, dataclass, fields
from pathlib import Path


@dataclass(frozen=True)
class Config:
    raiz_musica: Path = Path.home() / "Música"
    puerto: int = 7710
    avisos: bool = True
    normalizar: bool = True   # filtro dynaudnorm de mpv: parejiza el volumen entre temas


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


def cargar_config(archivo: Path) -> Config:
    try:
        with open(archivo, "rb") as f:
            datos = tomllib.load(f)
    except FileNotFoundError:
        return Config()
    conocidas = {c.name for c in fields(Config)}
    datos = {k: v for k, v in datos.items() if k in conocidas}
    if "raiz_musica" in datos:
        datos["raiz_musica"] = Path(datos["raiz_musica"]).expanduser()
    return Config(**datos)


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

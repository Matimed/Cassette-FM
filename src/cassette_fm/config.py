import json
import os
import urllib.parse
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
    nivel_musica_con_voz: float = 0.6   # en la escala del volumen de mpv (cúbica): 0.6 ≈ 13 dB más bajo
    rampa_bajada_segundos: float = 0.4
    rampa_subida_segundos: float = 1.0
    minimo_restante_segundos: float = 1.5
    tolerancia_desfase_segundos: float = 60.0
    desfase_aviso_segundos: float = 5.0
    margen_seguridad_voz_segundos: float = 2.0   # el temporizador que restaura la música espera esto de más
    url: str = ""   # servicio DJ (cassette-dj); vacío = la radio no planifica intervenciones
    margen_minutos: float = 6.0   # antes de esto no se agenda nada (da tiempo a generar el clip)
    frecuencia: Frecuencia = Frecuencia()
    voz: str = "af_heart"
    idioma: str = "en"
    personalidad: str = ""
    timeout_http_segundos: float = 10.0
    espera_reintento_segundos: float = 5.0   # primera espera tras un fallo del servicio
    espera_reintento_maxima_segundos: float = 300.0   # tope de la espera creciente
    espera_trabajo_maxima_segundos: float = 600.0   # un trabajo que tarda más que esto se cancela
    velocidad: float | None = None   # velocidad de la voz de la estación (0,5 a 2); None = la del servicio
    ganancia_voz_db: float = 10.0   # sube y comprime la voz de Kokoro (sale mucho más baja que la música); 0 = sin filtro
    recientes_cantidad: int = 6   # cuántos ingredientes recordar por estación
    peticion_margen_segundos: float = 30.0   # con menos que esto hasta el pedido, se anuncia después (no antes)


@dataclass(frozen=True)
class ConfigSpotify:
    """La app de desarrollador de Spotify (PKCE, sin secreto) y adónde hablarle."""
    client_id: str = "c8f7703801e64bc890d65527fc620248"
    puerto_login: int = 8888        # redirect http://127.0.0.1:<puerto>/callback (registrado en la app)
    timeout_segundos: float = 10.0
    cuentas_url: str = "https://accounts.spotify.com"
    api_url: str = "https://api.spotify.com/v1"
    activo: bool = True                       # false: las emisoras de Spotify se ignoran y Soloist no se usa
    soloist_ws: str = "ws://127.0.0.1:9787"   # WebSocket local de Soloist (servicio cassette-soloist)
    soloist_bin: Path = Path.home() / ".local/share/cassette-fm/soloist/bin/soloist"
    nombre_dispositivo: str = "cassette-fm"   # nombre de Soloist como dispositivo de Spotify
    ajuste_volumen_db: float = 0.0            # para que Spotify suene tan fuerte como las locales (scripts/calibrar-spotify.py)
    uris_por_pedido: int = 100                # temas que se le mandan a Spotify de una vez (no se usa la cola)
    tolerancia_resync_segundos: float = 3.0   # desfase con el reloj que hace re-sintonizar al empezar un tema


@dataclass(frozen=True)
class ConfigLan:
    """Escuchar la radio desde otra PC propia (lan_server.py): apagado por defecto."""
    activo: bool = False
    puerto: int = 8765
    escuchar: str = "auto"      # "auto" = la IP de Tailscale si existe, si no todas las interfaces; o una IP concreta
    max_oyentes: int = 4


@dataclass(frozen=True)
class ConfigNube:
    """Escuchar y manejar la radio desde cualquier lado a través de un relay (puente_nube.py): apagado por defecto."""
    activo: bool = False
    url: str | None = None      # base del relay: wss://host[:puerto] (ws:// solo contra localhost)


@dataclass(frozen=True)
class Config:
    raiz_musica: Path = Path.home() / "Música"
    puerto: int = 7710
    avisos: bool = False                   # notificación al cambiar de emisora (el applet ya la muestra)
    bus_audio: bool = True                 # todo el audio sale a un sink virtual (radio_virtual); ver audio_router.py
    normalizar: bool = True   # filtro dynaudnorm de mpv: parejiza el volumen entre temas
    ajuste_volumen_db: float = 0.0   # nivel de las emisoras locales (y la estática) frente a la voz y Spotify, en el bus
    dj: ConfigDJ = ConfigDJ()
    estaciones_dj: Mapping[str, ConfigDJ] = field(default_factory=dict)   # overrides ya fusionados
    spotify: ConfigSpotify = ConfigSpotify()
    lan: ConfigLan = ConfigLan()
    nube: ConfigNube = ConfigNube()


def configuracion_dj(config: Config, estacion: str) -> ConfigDJ:
    return config.estaciones_dj.get(estacion, config.dj)


@dataclass
class Estado:
    estacion: str | None = None
    volumen: int = 70
    monitor_local: bool = True    # con el bus de audio: si la radio se escucha en los parlantes de esta PC
    # por emisora: {"corrimiento": s, "pedidos": [{"inicio", "uri", "ruta", "duracion", "titulo", ...}]}
    agendas: dict[str, dict] = field(default_factory=dict)


def _es_numero(valor) -> bool:
    return isinstance(valor, (int, float)) and not isinstance(valor, bool) and valor == valor


def _agenda_valida(datos) -> bool:
    if not isinstance(datos, dict) or not _es_numero(datos.get("corrimiento")):
        return False
    pedidos = datos.get("pedidos", [])
    return isinstance(pedidos, list) and all(
        isinstance(p, dict) and _es_numero(p.get("inicio")) and _es_numero(p.get("duracion")) and p["duracion"] > 0
        and isinstance(p.get("titulo"), str) for p in pedidos)


@dataclass(frozen=True)
class Rutas:
    config: Path
    estado: Path
    cache: Path
    runtime: Path

    @property
    def emisoras(self) -> Path:
        return self.config.with_name("estaciones.json")

    @property
    def spotify_token(self) -> Path:
        return self.estado.with_name("spotify-token.json")

    @property
    def spotify_cache(self) -> Path:
        return self.cache.with_name("spotify.json")

    @property
    def intervenciones(self) -> Path:
        return self.estado.parent / "intervenciones.json"

    @property
    def clips(self) -> Path:
        return self.cache.parent / "dj"

    @property
    def lan_token(self) -> Path:
        return self.config.with_name("lan.token")

    @property
    def nube_token(self) -> Path:
        return self.config.with_name("nube.token")

    @property
    def claves(self) -> Path:
        return self.config.with_name("claves.json")

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
    spotify = _leer_spotify(archivo, datos.pop("spotify", None))
    lan = _leer_lan(archivo, datos.pop("lan", None))
    nube = _leer_nube(archivo, datos.pop("nube", None))
    conocidas = {"raiz_musica", "puerto", "avisos", "normalizar", "bus_audio", "ajuste_volumen_db"}
    datos = {k: v for k, v in datos.items() if k in conocidas}
    if "ajuste_volumen_db" in datos:
        datos["ajuste_volumen_db"] = _numero(archivo, "ajuste_volumen_db", datos["ajuste_volumen_db"])
        if not -30 <= datos["ajuste_volumen_db"] <= 30:
            raise ErrorConfig(f"{archivo}: 'ajuste_volumen_db' tiene que estar entre -30 y 30")
    for clave, valor in datos.items():
        tipo = {"raiz_musica": str, "puerto": int, "avisos": bool, "normalizar": bool,
                "bus_audio": bool, "ajuste_volumen_db": float}[clave]
        if not isinstance(valor, tipo) or (tipo is int and isinstance(valor, bool)):
            raise ErrorConfig(f"{archivo}: '{clave}' tiene que ser {_NOMBRE_TIPO[tipo]}")
    if "puerto" in datos and not 1 <= datos["puerto"] <= 65535:
        raise ErrorConfig(f"{archivo}: 'puerto' tiene que estar entre 1 y 65535")
    if "raiz_musica" in datos:
        datos["raiz_musica"] = Path(datos["raiz_musica"]).expanduser()
    dj, por_estacion = _leer_dj(archivo, tabla_dj)
    return Config(**datos, dj=dj, estaciones_dj=por_estacion, spotify=spotify, lan=lan, nube=nube)


def _leer_lan(archivo: Path, tabla) -> ConfigLan:
    if tabla is None:
        return ConfigLan()
    if not isinstance(tabla, dict):
        raise ErrorConfig(f"{archivo}: 'lan' tiene que ser una tabla")
    campos = {}
    if "activo" in tabla:
        if not isinstance(tabla["activo"], bool):
            raise ErrorConfig(f"{archivo}: 'lan.activo' tiene que ser true o false")
        campos["activo"] = tabla["activo"]
    for clave, maximo in (("puerto", 65535), ("max_oyentes", 100)):
        if clave in tabla:
            valor = tabla[clave]
            if isinstance(valor, bool) or not isinstance(valor, int) or not 1 <= valor <= maximo:
                raise ErrorConfig(f"{archivo}: 'lan.{clave}' tiene que ser un número entero entre 1 y {maximo}")
            campos[clave] = valor
    if "escuchar" in tabla:
        valor = _texto(archivo, "lan.escuchar", tabla["escuchar"]).strip()
        if not valor:
            raise ErrorConfig(f"{archivo}: 'lan.escuchar' no puede quedar vacío (\"auto\" o una IP)")
        campos["escuchar"] = valor
    return ConfigLan(**campos)


_HOSTS_LOCALES = ("127.0.0.1", "localhost", "::1")


def _leer_nube(archivo: Path, tabla) -> ConfigNube:
    if tabla is None:
        return ConfigNube()
    if not isinstance(tabla, dict):
        raise ErrorConfig(f"{archivo}: 'nube' tiene que ser una tabla")
    campos = {}
    if "activo" in tabla:
        if not isinstance(tabla["activo"], bool):
            raise ErrorConfig(f"{archivo}: 'nube.activo' tiene que ser true o false")
        campos["activo"] = tabla["activo"]
    if "url" in tabla:
        campos["url"] = _url_relay(archivo, _texto(archivo, "nube.url", tabla["url"]).strip())
    if campos.get("activo") and not campos.get("url"):
        raise ErrorConfig(f"{archivo}: 'nube.url' hace falta con la nube activa (p. ej. \"wss://relay.ejemplo.com\")")
    return ConfigNube(**campos)


def _url_relay(archivo: Path, valor: str) -> str:
    """wss://host[:puerto], o ws:// contra esta misma PC: la clave no viaja en claro por internet."""
    error = ErrorConfig(f"{archivo}: 'nube.url' tiene que ser wss://host[:puerto] (sin ruta, consulta ni usuario; "
                        f"ws:// solo contra localhost)")
    try:
        partes = urllib.parse.urlsplit(valor)
        partes.port
    except ValueError:
        raise error from None
    if (partes.scheme not in ("wss", "ws") or not partes.hostname or partes.path not in ("", "/") or partes.query
            or partes.fragment or partes.username or partes.password):
        raise error
    if partes.scheme == "ws" and partes.hostname not in _HOSTS_LOCALES:
        raise error
    return f"{partes.scheme}://{partes.netloc}"


def _leer_spotify(archivo: Path, tabla) -> "ConfigSpotify":
    if tabla is None:
        return ConfigSpotify()
    if not isinstance(tabla, dict):
        raise ErrorConfig(f"{archivo}: 'spotify' tiene que ser una tabla")
    campos = {}
    for clave in ("client_id", "cuentas_url", "api_url", "soloist_ws", "nombre_dispositivo", "soloist_bin"):
        if clave in tabla:
            valor = _texto(archivo, f"spotify.{clave}", tabla[clave]).strip()
            if not valor:
                raise ErrorConfig(f"{archivo}: 'spotify.{clave}' no puede quedar vacío")
            if clave in ("cuentas_url", "api_url") and not re.match(r"^https?://\S+$", valor):
                raise ErrorConfig(f"{archivo}: 'spotify.{clave}' tiene que empezar con http:// o https://")
            if clave == "soloist_ws" and not re.match(r"^ws://\S+$", valor):
                raise ErrorConfig(f"{archivo}: 'spotify.soloist_ws' tiene que empezar con ws://")
            campos[clave] = Path(valor).expanduser() if clave == "soloist_bin" else valor.rstrip("/")
    if "activo" in tabla:
        if not isinstance(tabla["activo"], bool):
            raise ErrorConfig(f"{archivo}: 'spotify.activo' tiene que ser true o false")
        campos["activo"] = tabla["activo"]
    if "ajuste_volumen_db" in tabla:
        valor = _numero(archivo, "spotify.ajuste_volumen_db", tabla["ajuste_volumen_db"])
        if not -30 <= valor <= 30:
            raise ErrorConfig(f"{archivo}: 'spotify.ajuste_volumen_db' tiene que estar entre -30 y 30")
        campos["ajuste_volumen_db"] = valor
    if "uris_por_pedido" in tabla:
        valor = tabla["uris_por_pedido"]
        if isinstance(valor, bool) or not isinstance(valor, int) or not 1 <= valor <= 500:
            raise ErrorConfig(f"{archivo}: 'spotify.uris_por_pedido' tiene que ser un entero entre 1 y 500")
        campos["uris_por_pedido"] = valor
    if "tolerancia_resync_segundos" in tabla:
        valor = _numero(archivo, "spotify.tolerancia_resync_segundos", tabla["tolerancia_resync_segundos"])
        if valor <= 0:
            raise ErrorConfig(f"{archivo}: 'spotify.tolerancia_resync_segundos' tiene que ser mayor que 0")
        campos["tolerancia_resync_segundos"] = valor
    if "puerto_login" in tabla:
        valor = tabla["puerto_login"]
        if isinstance(valor, bool) or not isinstance(valor, int) or not 1 <= valor <= 65535:
            raise ErrorConfig(f"{archivo}: 'spotify.puerto_login' tiene que ser un entero entre 1 y 65535")
        campos["puerto_login"] = valor
    if "timeout_segundos" in tabla:
        valor = _numero(archivo, "spotify.timeout_segundos", tabla["timeout_segundos"])
        if valor <= 0:
            raise ErrorConfig(f"{archivo}: 'spotify.timeout_segundos' tiene que ser mayor que 0")
        campos["timeout_segundos"] = valor
    return ConfigSpotify(**campos)


_CAMPOS_NUMERICOS_DJ = {c.name for c in fields(ConfigDJ)
                        if c.type in (float, "float") and c.name != "frecuencia"}
_POSITIVOS = {"peticion_margen_segundos", "duracion_maxima_segundos", "tolerancia_desfase_segundos", "desfase_aviso_segundos",
              "timeout_http_segundos", "espera_reintento_segundos", "espera_reintento_maxima_segundos",
              "espera_trabajo_maxima_segundos"}
_IDIOMAS = ("es", "en", "en-us", "en-gb")
_VOZ = re.compile(r"^[A-Za-z0-9_+.:-]+$")
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


def campos_dj(archivo: Path, tabla: dict, donde: str, base: ConfigDJ) -> dict:
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
            if clave == "ganancia_voz_db" and valor > 30:
                raise ErrorConfig(f"{archivo}: '{nombre}' no puede pasar de 30 dB")
            if clave in _POSITIVOS and valor <= 0:
                raise ErrorConfig(f"{archivo}: '{nombre}' tiene que ser mayor que 0")
            if valor < 0:
                raise ErrorConfig(f"{archivo}: '{nombre}' no puede ser negativo")
            campos[clave] = valor
        elif clave == "velocidad":
            valor = _numero(archivo, nombre, valor)
            if not 0.5 <= valor <= 2.0:
                raise ErrorConfig(f"{archivo}: '{nombre}' tiene que estar entre 0,5 y 2")
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
                raise ErrorConfig(f"{archivo}: '{nombre}' solo puede tener letras, números y _ + . : -")
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
    general = replace(ConfigDJ(), **campos_dj(archivo, tabla, "dj.", ConfigDJ()))
    por_estacion = {}
    for nombre, t in estaciones.items():
        if not isinstance(t, dict):
            raise ErrorConfig(f"{archivo}: 'dj.estaciones.{nombre}' tiene que ser una tabla")
        por_estacion[nombre] = replace(general, **campos_dj(archivo, t, f"dj.estaciones.{nombre}.", general))
    return general, por_estacion


def cargar_estado(archivo: Path) -> Estado:
    try:
        datos = json.loads(Path(archivo).read_text(encoding="utf-8"))
        agendas = datos.get("agendas")
        agendas = {str(n): {"corrimiento": float(a["corrimiento"]), "pedidos": list(a.get("pedidos", []))}
                   for n, a in (agendas.items() if isinstance(agendas, dict) else ()) if _agenda_valida(a)}
        return Estado(estacion=datos.get("estacion"), volumen=int(datos.get("volumen", 70)),
                      monitor_local=datos.get("monitor_local", True) is not False, agendas=agendas)
    except (OSError, ValueError, AttributeError, TypeError):
        return Estado()


def guardar_estado(archivo: Path, estado: Estado) -> None:
    archivo = Path(archivo)
    archivo.parent.mkdir(parents=True, exist_ok=True)
    tmp = archivo.with_suffix(archivo.suffix + ".tmp")
    tmp.write_text(json.dumps(asdict(estado), ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, archivo)

import logging
import signal
import threading
import time
from collections.abc import Callable, Sequence

from cassette_fm.api import crear_servidor
from cassette_fm.audio_router import AudioRouter, AudioRouterError
from cassette_fm.avisos import Notificador
from cassette_fm.cliente_dj import ClienteDJ
from cassette_fm.config import Config, Rutas, cargar_estado, guardar_estado
from cassette_fm.emisoras import Catalogo
from cassette_fm.intervenciones import RegistroIntervenciones
from cassette_fm import lan_acceso
from cassette_fm.lan_server import crear_servidor_lan
from cassette_fm.lan_stream import FUENTE_ESTATICA, FUENTE_MONITOR, Difusor
from cassette_fm.locutor import Locutor
from cassette_fm.mpris import ServicioMpris
from cassette_fm.mpv import ClienteMpv
from cassette_fm.planificador import Planificador
from cassette_fm.radio import Radio
from cassette_fm.clips import generar_estatica
from cassette_fm.reproductor import Reproductor
from cassette_fm.reproductores import Reproductores


_log = logging.getLogger("cassette_fm")


def argumentos_voz(dj, extra: Sequence[str] = ()) -> list[str]:
    """Argumentos del mpv de la voz: compresor + ganancia + limitador, para que se oiga a la par de la música."""
    args = list(extra)
    if dj.ganancia_voz_db > 0:
        args.append(f"--af=lavfi=[acompressor=threshold=-26dB:ratio=3:attack=5:release=80:makeup=2,"
                    f"volume={dj.ganancia_voz_db:g}dB,alimiter=limit=0.95]")
    return args


def cliente_spotify(config: Config, rutas: Rutas):
    """Un solo cliente (y una sola sesión) de Spotify para el catálogo y el reproductor."""
    from cassette_fm.spotify.api import ClienteSpotify
    from cassette_fm.spotify.sesion import Sesion
    return ClienteSpotify(Sesion(rutas.spotify_token, config.spotify), config.spotify)


def catalogo_spotify(config: Config, rutas: Rutas, cliente=None):
    from cassette_fm.spotify.catalogo import CatalogoSpotify
    return CatalogoSpotify(cliente or cliente_spotify(config, rutas), rutas.spotify_cache)


def reproductor_spotify(config: Config, rutas: Rutas, cliente):
    """El reproductor de Spotify con su WebSocket de Soloist (que se conecta en segundo plano)."""
    from cassette_fm.reproductor_spotify import ReproductorSpotify
    from cassette_fm.spotify.control import ControlSpotify
    from cassette_fm.spotify.soloist import ClienteSoloist
    c = config.spotify
    rep: list = []
    soloist = ClienteSoloist(c.soloist_ws, al_evento=lambda e: rep[0].manejar_evento(e) if rep else None,
                             al_desconectar=lambda: rep[0].soloist_desconectado() if rep else None,
                             al_reconectar=lambda: rep[0].soloist_reconectado() if rep else None)
    rep.append(ReproductorSpotify(ControlSpotify(cliente, c.nombre_dispositivo), soloist,
                                  uris_por_pedido=c.uris_por_pedido, ajuste_volumen_db=c.ajuste_volumen_db,
                                  tolerancia_resync_segundos=c.tolerancia_resync_segundos))
    soloist.iniciar()
    return rep[0], soloist


def iniciar_lan(config: Config, rutas: Rutas, radio, router, crear_difusor=Difusor, ip_ts=None,
                tailscale_instalado=None, intervalo_reintento: float = 30.0,
                intervalo_revision: float = 1.0) -> Callable[[], None] | None:
    """Levanta el servidor de la radio por la red (`[lan] activo`). Devuelve la función que lo cierra, o None si no
    corresponde (apagado o sin bus de audio). Si la IP de Tailscale todavía no está o el puerto no se puede abrir,
    reintenta en segundo plano en vez de caerse."""
    lan = config.lan
    if not lan.activo:
        return None
    if router is None:
        _log.error("[lan] necesita el bus de audio: el servidor de la red no se abre (poné `bus_audio = true`)")
        return None
    lan_acceso.leer_o_crear_token(rutas.lan_token)          # crea el archivo si falta
    difusor = crear_difusor(lambda: FUENTE_MONITOR if radio.encendida else FUENTE_ESTATICA,
                            max_oyentes=lan.max_oyentes)
    token = lan_acceso.TokenVivo(rutas.lan_token, al_cambiar=difusor.cortar_oyentes)
    token()
    parar = threading.Event()
    actual: list = []
    direccion = lambda: lan_acceso.direccion_de_escucha(
        lan.escuchar, ip_ts or lan_acceso.ip_tailscale, tailscale_instalado or lan_acceso.tailscale_instalado)

    def servir_lan():
        while not parar.is_set():
            host = direccion()
            if host is None:
                _log.info("la radio por la red espera la IP de Tailscale")
            else:
                try:
                    servidor = crear_servidor_lan(radio, difusor, token, host, lan.puerto)
                except OSError as e:
                    _log.warning("la radio por la red no pudo abrir %s:%d (%s); se reintenta", host, lan.puerto, e)
                else:
                    actual.append(servidor)
                    _log.info("la radio por la red escucha en %s:%d", host, lan.puerto)
                    servidor.serve_forever(poll_interval=0.05)
                    return
            parar.wait(intervalo_reintento)

    def revisar():
        while not parar.wait(intervalo_revision):
            try:
                token()                       # una clave regenerada corta a los oyentes en un segundo
                difusor.revisar_fuente()
            except Exception:
                _log.exception("error al revisar el stream de la red")

    threading.Thread(target=servir_lan, daemon=True, name="lan-servidor").start()
    threading.Thread(target=revisar, daemon=True, name="lan-revision").start()

    def cerrar() -> None:
        parar.set()
        for servidor in actual:
            servidor.shutdown()
            servidor.server_close()
        difusor.cerrar()

    return cerrar


def servir(config: Config, rutas: Rutas, avisar: Callable[[str, str], None] | None = None,
           parar: threading.Event | None = None, extra_args_mpv: Sequence[str] = (),
           bus_mpris: str | None = None) -> None:
    """Arma la radio y sirve la API hasta SIGTERM/SIGINT o hasta que se setee `parar`.

    `bus_mpris`: dirección del bus donde anunciarse por MPRIS (None = el bus de sesión)."""
    parar = parar or threading.Event()
    if avisar is None and config.avisos:
        avisar = Notificador()
    if threading.current_thread() is threading.main_thread():
        for senal in (signal.SIGTERM, signal.SIGINT):
            signal.signal(senal, lambda *_: parar.set())

    cliente = cliente_spotify(config, rutas) if config.spotify.activo else None
    catalogo = Catalogo(config, rutas, spotify=catalogo_spotify(config, rutas, cliente) if cliente else None,
                        reproduce_spotify=config.spotify.activo)
    escanear = catalogo.escanear

    router = env_audio = None
    if config.bus_audio:
        try:
            router = AudioRouter()
            router.create_bus()
            env_audio = router.env()
            # mpv en PipeWire usa por defecto su salida nativa, que ignora PULSE_SINK; los args del usuario van después
            extra_args_mpv = ["--ao=pulse", *extra_args_mpv]
        except AudioRouterError as e:
            _log.error("no se pudo crear el bus de audio (%s); la radio suena sin él. Si no lo necesitás, poné "
                       "`bus_audio = false` en config.toml (y corré scripts/instalar-bus.sh quitar)", e)
            router = env_audio = None

    estado = cargar_estado(rutas.estado)
    args_mpv = (["--af=dynaudnorm"] if config.normalizar else []) + list(extra_args_mpv)
    mpv = ClienteMpv(rutas.runtime / "mpv.sock", extra_args=args_mpv, env=env_audio)
    estaciones = escanear()
    _log.info("%d estaciones (de %s)", len(estaciones), rutas.emisoras)
    spotify = soloist = estatica = None
    if cliente is not None:
        spotify, soloist = reproductor_spotify(config, rutas, cliente)
        estatica = generar_estatica(rutas.runtime / "estatica.wav")
    reproductor = Reproductores(Reproductor(mpv, ajuste_volumen_db=config.ajuste_volumen_db), spotify, estatica)
    locutor = None
    planificador = None
    extra_radio = {}
    if config.dj.activo:
        # el segundo mpv (la voz) no arranca hasta el primer clip y no lleva el filtro de volumen
        voz = ClienteMpv(rutas.runtime / "voz.sock", extra_args=argumentos_voz(config.dj, extra_args_mpv), env=env_audio)
        registro = RegistroIntervenciones(rutas.intervenciones, rutas.clips,
                                          gracia_segundos=config.dj.tolerancia_desfase_segundos)
        locutor = Locutor(voz, reproductor, registro, catalogo.configuracion_dj)
        extra_radio = dict(dj=locutor, configuracion_dj=catalogo.configuracion_dj,
                           dir_clips=rutas.clips)
        if config.dj.url:
            # sin `url` la radio no intenta conectarse a ningún servicio DJ (solo clips de prueba)
            planificador = Planificador(ClienteDJ(config.dj.url, config.dj.timeout_http_segundos), locutor,
                                        registro, catalogo.configuracion_dj,
                                        rutas.planificador, rutas.clips,
                                        gracia_segundos=config.dj.tolerancia_desfase_segundos)
            extra_radio["planificador"] = planificador
    radio = Radio(reproductor, estaciones, estado,
                  guardar=lambda e: guardar_estado(rutas.estado, e),
                  escanear=escanear, avisar=avisar, iconos=catalogo.iconos, router=router, **extra_radio)
    # teclas multimedia y botones del parlante; sin bus de sesión la radio anda igual
    mpris = ServicioMpris(radio, direccion=bus_mpris)
    radio.al_cambiar = mpris.cambio
    mpris.iniciar()
    if planificador is not None:
        planificador.iniciar()
        _log.info("planificador del DJ activo (servicio en %s)", config.dj.url)
    try:
        cerrar_lan = iniciar_lan(config, rutas, radio, router)
    except Exception:
        _log.exception("la radio por la red no arrancó; la radio local sigue andando")
        cerrar_lan = None
    servidor = crear_servidor(radio, "127.0.0.1", config.puerto, emisoras=rutas.emisoras)
    hilo = threading.Thread(target=lambda: servidor.serve_forever(poll_interval=0.05), daemon=True)
    hilo.start()
    _log.info("escuchando en 127.0.0.1:%d", servidor.server_address[1])
    try:
        parar.wait()
    finally:
        pasos = [servidor.shutdown, servidor.server_close, mpris.cerrar]
        if cerrar_lan is not None:
            pasos.insert(0, cerrar_lan)
        if planificador is not None:
            pasos.append(planificador.cerrar)     # antes de apagar la radio y de cerrar el locutor y mpv
        pasos.append(radio.apagar)
        if locutor is not None:
            pasos.append(locutor.cerrar)
        if soloist is not None:
            pasos.append(soloist.cerrar)
        pasos.append(mpv.cerrar)
        if router is not None:
            pasos.append(router.close)     # al final: con el bus ya vacío
        for paso in pasos:
            try:
                paso()
            except Exception:
                _log.exception("error al apagar (%s)", getattr(paso, "__qualname__", paso))

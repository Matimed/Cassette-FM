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
from cassette_fm import claves, lan_acceso, recuperacion
from cassette_fm.lan_server import crear_servidor_lan
from cassette_fm.lan_stream import FUENTE_ESTATICA, FUENTE_MONITOR, Difusor, Difusores
from cassette_fm.locutor import Locutor
from cassette_fm.mpris import ServicioMpris
from cassette_fm.mpv import ClienteMpv
from cassette_fm.planificador import Planificador
from cassette_fm.radio import Radio
from cassette_fm.clips import generar_estatica
from cassette_fm.reproductor import Reproductor
from cassette_fm.reproductores import Reproductores
from cassette_fm.vigilante import Vigilante


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


def iniciar_lan(config: Config, rutas: Rutas, radio, router, difusores: Difusores | None = None,
                crear_difusor=Difusor, ip_ts=None,
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
    propios = difusores is None          # sin registro compartido (tests): la LAN crea, revisa y cierra el suyo
    if propios:
        difusores = Difusores(lambda: FUENTE_MONITOR if radio.encendida else FUENTE_ESTATICA, crear=crear_difusor,
                              max_oyentes=lan.max_oyentes)
    difusor = difusores.de(160)
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
                if propios:
                    difusores.revisar_fuente()
            except Exception:
                _log.exception("error al revisar el stream de la red")

    threading.Thread(target=servir_lan, daemon=True, name="lan-servidor").start()
    threading.Thread(target=revisar, daemon=True, name="lan-revision").start()

    def cerrar() -> None:
        parar.set()
        for servidor in actual:
            servidor.shutdown()
            servidor.server_close()
        if propios:
            difusores.cerrar()

    return cerrar


def iniciar_nube(config: Config, rutas: Rutas, radio, router, difusores, crear_puente=None,
                 intervalo_revision: float = 1.0) -> tuple[Callable[[], None], Callable[[], dict]] | None:
    """Conecta con el relay de la nube (`[nube] activo`). Devuelve (cerrar, info), o None si no corresponde (apagado
    o sin bus de audio). Una clave regenerada con `cassette nube regenerar` rige sin reiniciar."""
    nube = config.nube
    if not nube.activo:
        return None
    if router is None or difusores is None:
        _log.error("[nube] necesita el bus de audio: el puente a la nube no arranca (poné `bus_audio = true`)")
        return None
    if crear_puente is None:
        from cassette_fm.puente_nube import PuenteNube
        crear_puente = PuenteNube
    lan_acceso.leer_o_crear_token(rutas.nube_token)          # crea el archivo si falta
    puente: list = []
    token = lan_acceso.TokenVivo(rutas.nube_token, al_cambiar=lambda: puente[0].reconectar() if puente else None)
    token()
    puente.append(crear_puente(radio, difusores, nube.url, token))
    estado_claves = {"mandada": None, "roto": False}

    def sincronizar_claves() -> None:
        """Pasa al puente la lista de `claves.json` cuando cambia; con el archivo roto rige la última buena."""
        try:
            lista = claves.para_relay(claves.leer(rutas.claves))
        except claves.ErrorClaves as e:
            if not estado_claves["roto"]:
                _log.error("claves.json no se puede leer: %s; sigue rigiendo la última lista", e)
                estado_claves["roto"] = True
            if estado_claves["mandada"] is None:       # nunca hubo una buena: vacía (solo la maestra entra)
                estado_claves["mandada"] = []
                puente[0].poner_claves([])
            return
        estado_claves["roto"] = False
        if lista != estado_claves["mandada"]:
            estado_claves["mandada"] = lista
            puente[0].poner_claves(lista)

    sincronizar_claves()                      # antes de iniciar: sale con el primer hola
    puente[0].iniciar()
    parar = threading.Event()

    def revisar():
        while not parar.wait(intervalo_revision):
            try:
                token()                       # una clave regenerada reconecta en un segundo
                sincronizar_claves()          # claves nuevas o borradas rigen en un segundo
            except Exception:
                _log.exception("error al revisar la clave de la nube")

    threading.Thread(target=revisar, daemon=True, name="nube-revision").start()

    def cerrar() -> None:
        parar.set()
        puente[0].cerrar()

    def info() -> dict:
        datos = puente[0].info()
        return {clave: datos[clave] for clave in ("conectado", "conectado_hace", "error", "subiendo")}

    return cerrar, info


def preparar_recuperacion(radio, rutas: Rutas, soloist) -> threading.Thread | None:
    """El último recurso de la radio cuando una emisora no logra sonar (reiniciar el servicio en vez de apagarse) y, si este
    arranque es el de ese reinicio, el hilo que retoma la emisora en cuanto Soloist se conecta."""
    radio.ultimo_recurso = lambda estacion, motivo: (recuperacion.merece_reinicio(estacion, motivo)
                                                      and recuperacion.pedir_reinicio(rutas.reinicio, estacion.nombre, motivo))
    if recuperacion.a_retomar(rutas.reinicio) is None:
        return None
    hilo = threading.Thread(target=recuperacion.retomar, daemon=True, name="retomar-tras-reinicio",
                            args=(rutas.reinicio, radio, lambda: soloist is None or soloist.conectado))
    hilo.start()
    return hilo


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
    if recuperacion.a_retomar(rutas.reinicio) is None:
        estado.monitor_local = False       # el servicio arranca sin oyente local; solo el reinicio de recuperación lo conserva
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
    preparar_recuperacion(radio, rutas, soloist)
    if planificador is not None:
        planificador.iniciar()
        _log.info("planificador del DJ activo (servicio en %s)", config.dj.url)
    difusores = None
    if router is not None and (config.lan.activo or config.nube.activo):
        # un codificador por calidad, compartido por la LAN y la nube
        difusores = Difusores(lambda: FUENTE_MONITOR if radio.encendida else FUENTE_ESTATICA,
                              max_oyentes=config.lan.max_oyentes, al_conectarse=radio.despertar_para_red)
    radio.oyentes_red = difusores.total_oyentes if difusores is not None else (lambda: 0)
    try:
        cerrar_lan = iniciar_lan(config, rutas, radio, router, difusores=difusores)
    except Exception:
        _log.exception("la radio por la red no arrancó; la radio local sigue andando")
        cerrar_lan = None
    try:
        nube = iniciar_nube(config, rutas, radio, router, difusores)
    except Exception:
        _log.exception("el puente a la nube no arrancó; la radio local sigue andando")
        nube = None
    parar_difusores = threading.Event()
    if difusores is not None:
        def revisar_difusores():
            while not parar_difusores.wait(1.0):
                try:
                    difusores.revisar_fuente()
                except Exception:
                    _log.exception("error al revisar el stream de la red")

        threading.Thread(target=revisar_difusores, daemon=True, name="difusores-revision").start()
    vigilante = None
    if router is not None:            # sin bus no hay cómo contar oyentes: no hay sueño automático
        vigilante = Vigilante(radio, config.segundos_hasta_dormir)
        vigilante.iniciar()
        _log.info("la radio se duerme sola tras %g s sin oyentes", config.segundos_hasta_dormir)
    servidor = crear_servidor(radio, "127.0.0.1", config.puerto, emisoras=rutas.emisoras,
                              extra_estado=(lambda: {"nube": nube[1]()}) if nube is not None else None)
    hilo = threading.Thread(target=lambda: servidor.serve_forever(poll_interval=0.05), daemon=True)
    hilo.start()
    _log.info("escuchando en 127.0.0.1:%d", servidor.server_address[1])
    try:
        parar.wait()
    finally:
        pasos = [paso for paso in (nube[0] if nube is not None else None, cerrar_lan) if paso is not None]
        if difusores is not None:               # después de la nube y la LAN, que son sus oyentes
            pasos.append(lambda: (parar_difusores.set(), difusores.cerrar()))
        pasos += [servidor.shutdown, servidor.server_close, mpris.cerrar]
        if vigilante is not None:
            pasos.append(vigilante.cerrar)        # antes de apagar la radio: que no la duerma él mientras se cierra
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

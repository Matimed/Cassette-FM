import logging
import signal
import threading
import time
from collections.abc import Callable, Sequence

from cassette_fm.api import crear_servidor
from cassette_fm.avisos import Notificador
from cassette_fm.cliente_dj import ClienteDJ
from cassette_fm.config import Config, Rutas, cargar_estado, guardar_estado
from cassette_fm.emisoras import Catalogo
from cassette_fm.intervenciones import RegistroIntervenciones
from cassette_fm.locutor import Locutor
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


def servir(config: Config, rutas: Rutas, avisar: Callable[[str, str], None] | None = None,
           parar: threading.Event | None = None, extra_args_mpv: Sequence[str] = ()) -> None:
    """Arma la radio y sirve la API hasta SIGTERM/SIGINT o hasta que se setee `parar`."""
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

    estado = cargar_estado(rutas.estado)
    args_mpv = (["--af=dynaudnorm"] if config.normalizar else []) + list(extra_args_mpv)
    mpv = ClienteMpv(rutas.runtime / "mpv.sock", extra_args=args_mpv)
    estaciones = escanear()
    _log.info("%d estaciones (de %s)", len(estaciones), rutas.emisoras)
    spotify = soloist = estatica = None
    if cliente is not None:
        spotify, soloist = reproductor_spotify(config, rutas, cliente)
        estatica = generar_estatica(rutas.runtime / "estatica.wav")
    reproductor = Reproductores(Reproductor(mpv), spotify, estatica)
    locutor = None
    planificador = None
    extra_radio = {}
    if config.dj.activo:
        # el segundo mpv (la voz) no arranca hasta el primer clip y no lleva el filtro de volumen
        voz = ClienteMpv(rutas.runtime / "voz.sock", extra_args=argumentos_voz(config.dj, extra_args_mpv))
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
                  escanear=escanear, avisar=avisar, **extra_radio)
    if planificador is not None:
        planificador.iniciar()
        _log.info("planificador del DJ activo (servicio en %s)", config.dj.url)
    servidor = crear_servidor(radio, "127.0.0.1", config.puerto, emisoras=rutas.emisoras)
    hilo = threading.Thread(target=lambda: servidor.serve_forever(poll_interval=0.05), daemon=True)
    hilo.start()
    _log.info("escuchando en 127.0.0.1:%d", servidor.server_address[1])
    try:
        parar.wait()
    finally:
        pasos = [servidor.shutdown, servidor.server_close]
        if planificador is not None:
            pasos.append(planificador.cerrar)     # antes de apagar la radio y de cerrar el locutor y mpv
        pasos.append(radio.apagar)
        if locutor is not None:
            pasos.append(locutor.cerrar)
        if soloist is not None:
            pasos.append(soloist.cerrar)
        pasos.append(mpv.cerrar)
        for paso in pasos:
            try:
                paso()
            except Exception:
                _log.exception("error al apagar (%s)", getattr(paso, "__qualname__", paso))

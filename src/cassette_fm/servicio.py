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
from cassette_fm.reproductor import Reproductor


_log = logging.getLogger("cassette_fm")


def argumentos_voz(dj, extra: Sequence[str] = ()) -> list[str]:
    """Argumentos del mpv de la voz: compresor + ganancia + limitador, para que se oiga a la par de la música."""
    args = list(extra)
    if dj.ganancia_voz_db > 0:
        args.append(f"--af=lavfi=[acompressor=threshold=-26dB:ratio=3:attack=5:release=80:makeup=2,"
                    f"volume={dj.ganancia_voz_db:g}dB,alimiter=limit=0.95]")
    return args


def catalogo_spotify(config: Config, rutas: Rutas):
    from cassette_fm.spotify.api import ClienteSpotify
    from cassette_fm.spotify.catalogo import CatalogoSpotify
    from cassette_fm.spotify.sesion import Sesion
    return CatalogoSpotify(ClienteSpotify(Sesion(rutas.spotify_token, config.spotify), config.spotify),
                           rutas.spotify_cache)


def servir(config: Config, rutas: Rutas, avisar: Callable[[str, str], None] | None = None,
           parar: threading.Event | None = None, extra_args_mpv: Sequence[str] = ()) -> None:
    """Arma la radio y sirve la API hasta SIGTERM/SIGINT o hasta que se setee `parar`."""
    parar = parar or threading.Event()
    if avisar is None and config.avisos:
        avisar = Notificador()
    if threading.current_thread() is threading.main_thread():
        for senal in (signal.SIGTERM, signal.SIGINT):
            signal.signal(senal, lambda *_: parar.set())

    catalogo = Catalogo(config, rutas, spotify=catalogo_spotify(config, rutas))
    escanear = catalogo.escanear

    estado = cargar_estado(rutas.estado)
    args_mpv = (["--af=dynaudnorm"] if config.normalizar else []) + list(extra_args_mpv)
    mpv = ClienteMpv(rutas.runtime / "mpv.sock", extra_args=args_mpv)
    estaciones = escanear()
    _log.info("%d estaciones (de %s)", len(estaciones), rutas.emisoras)
    reproductor = Reproductor(mpv)
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
        pasos.append(mpv.cerrar)
        for paso in pasos:
            try:
                paso()
            except Exception:
                _log.exception("error al apagar (%s)", getattr(paso, "__qualname__", paso))

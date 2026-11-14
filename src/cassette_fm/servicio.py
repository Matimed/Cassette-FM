import logging
import signal
import threading
import time
from collections.abc import Callable, Sequence

from cassette_fm import biblioteca
from cassette_fm.api import crear_servidor
from cassette_fm.avisos import Notificador
from cassette_fm.config import Config, Rutas, cargar_estado, configuracion_dj, guardar_estado
from cassette_fm.intervenciones import RegistroIntervenciones
from cassette_fm.locutor import Locutor
from cassette_fm.mpv import ClienteMpv
from cassette_fm.radio import Radio
from cassette_fm.reproductor import Reproductor


_log = logging.getLogger("cassette_fm")


def servir(config: Config, rutas: Rutas, avisar: Callable[[str, str], None] | None = None,
           parar: threading.Event | None = None, extra_args_mpv: Sequence[str] = ()) -> None:
    """Arma la radio y sirve la API hasta SIGTERM/SIGINT o hasta que se setee `parar`."""
    parar = parar or threading.Event()
    if avisar is None and config.avisos:
        avisar = Notificador()
    if threading.current_thread() is threading.main_thread():
        for senal in (signal.SIGTERM, signal.SIGINT):
            signal.signal(senal, lambda *_: parar.set())

    def escanear():
        return biblioteca.escanear(config.raiz_musica, rutas.cache)

    estado = cargar_estado(rutas.estado)
    args_mpv = (["--af=dynaudnorm"] if config.normalizar else []) + list(extra_args_mpv)
    mpv = ClienteMpv(rutas.runtime / "mpv.sock", extra_args=args_mpv)
    estaciones = escanear()
    _log.info("%d estaciones en %s", len(estaciones), config.raiz_musica)
    reproductor = Reproductor(mpv)
    locutor = None
    extra_radio = {}
    if config.dj.activo:
        # el segundo mpv (la voz) no arranca hasta el primer clip y no lleva el filtro de volumen
        voz = ClienteMpv(rutas.runtime / "voz.sock", extra_args=list(extra_args_mpv))
        locutor = Locutor(voz, reproductor, RegistroIntervenciones(rutas.intervenciones, rutas.clips),
                          lambda nombre: configuracion_dj(config, nombre))
        extra_radio = dict(dj=locutor, configuracion_dj=lambda nombre: configuracion_dj(config, nombre),
                           dir_clips=rutas.clips)
    radio = Radio(reproductor, estaciones, estado,
                  guardar=lambda e: guardar_estado(rutas.estado, e),
                  escanear=escanear, avisar=avisar, **extra_radio)
    servidor = crear_servidor(radio, "127.0.0.1", config.puerto, raiz=config.raiz_musica)
    hilo = threading.Thread(target=lambda: servidor.serve_forever(poll_interval=0.05), daemon=True)
    hilo.start()
    _log.info("escuchando en 127.0.0.1:%d", servidor.server_address[1])
    try:
        parar.wait()
    finally:
        pasos = [servidor.shutdown, servidor.server_close, radio.apagar]
        if locutor is not None:
            pasos.append(locutor.cerrar)
        pasos.append(mpv.cerrar)
        for paso in pasos:
            try:
                paso()
            except Exception:
                _log.exception("error al apagar (%s)", getattr(paso, "__qualname__", paso))

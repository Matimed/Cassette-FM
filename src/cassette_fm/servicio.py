import signal
import threading
import time
from collections.abc import Callable, Sequence

from cassette_fm import biblioteca
from cassette_fm.api import crear_servidor
from cassette_fm.config import Config, Rutas, cargar_estado, guardar_estado
from cassette_fm.mpv import ClienteMpv
from cassette_fm.radio import Radio
from cassette_fm.reproductor import Reproductor


def servir(config: Config, rutas: Rutas, avisar: Callable[[str, str], None] | None = None,
           parar: threading.Event | None = None, extra_args_mpv: Sequence[str] = ()) -> None:
    """Arma la radio y sirve la API hasta SIGTERM/SIGINT o hasta que se setee `parar`."""
    parar = parar or threading.Event()
    if threading.current_thread() is threading.main_thread():
        for senal in (signal.SIGTERM, signal.SIGINT):
            signal.signal(senal, lambda *_: parar.set())

    def escanear():
        return biblioteca.escanear(config.raiz_musica, rutas.cache)

    estado = cargar_estado(rutas.estado)
    mpv = ClienteMpv(rutas.runtime / "mpv.sock", extra_args=extra_args_mpv)
    radio = Radio(Reproductor(mpv), escanear(), estado,
                  guardar=lambda e: guardar_estado(rutas.estado, e),
                  escanear=escanear, avisar=avisar)
    servidor = crear_servidor(radio, "127.0.0.1", config.puerto, raiz=config.raiz_musica)
    hilo = threading.Thread(target=lambda: servidor.serve_forever(poll_interval=0.05), daemon=True)
    hilo.start()
    try:
        parar.wait()
    finally:
        servidor.shutdown()
        servidor.server_close()
        radio.apagar()
        mpv.cerrar()

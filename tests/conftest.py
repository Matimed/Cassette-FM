import math
import os
import shutil
import subprocess
import tempfile
from types import SimpleNamespace
from pathlib import Path

import pytest
from mutagen.easyid3 import EasyID3

# Frame MPEG-1 Layer III, 128 kbps, 44,1 kHz, sin CRC: 417 bytes, 1152 muestras.
_FRAME = b"\xff\xfb\x90\x64" + b"\x00" * 413
_MUESTRAS_POR_FRAME = 1152
_FRECUENCIA = 44100


@pytest.fixture
def crear_mp3():
    def crear(ruta: Path, segundos: float = 3.0, titulo: str | None = None,
              artista: str | None = None, album: str | None = None,
              isrc: str | None = None) -> Path:
        ruta = Path(ruta)
        ruta.parent.mkdir(parents=True, exist_ok=True)
        frames = math.ceil(segundos * _FRECUENCIA / _MUESTRAS_POR_FRAME)
        ruta.write_bytes(_FRAME * frames)
        if titulo or artista or album or isrc:
            tags = EasyID3()
            if titulo:
                tags["title"] = titulo
            if artista:
                tags["artist"] = artista
            if album:
                tags["album"] = album
            if isrc:
                tags["isrc"] = isrc
            tags.save(ruta)
        return ruta

    return crear


@pytest.fixture
def dir_corto():
    """Directorio de ruta corta (los sockets Unix admiten ~108 caracteres)."""
    base = os.environ.get("XDG_RUNTIME_DIR", "/tmp")
    ruta = Path(tempfile.mkdtemp(prefix="cfm.", dir=base))
    yield ruta
    shutil.rmtree(ruta, ignore_errors=True)


@pytest.fixture
def crear_wav():
    from cassette_fm.clips import generar_clip_de_prueba

    def crear(ruta: Path, segundos: float = 4.0) -> Path:
        return generar_clip_de_prueba(Path(ruta), segundos)

    return crear


class SintetizadorFalso:
    """Imita al Sintetizador del servicio DJ: escribe un WAV de `duracion` segundos; puede bloquearse con `puerta`."""

    def __init__(self, duracion: float = 3.0):
        self.duracion = duracion
        self.puerta = None      # threading.Event: si está, sintetizar espera a que se setee
        self.cargado = False
        self.llamadas = []

    def sintetizar(self, fonemas, voz, lang, salida, velocidad=None, texto=None):
        import wave
        if self.puerta is not None:
            assert self.puerta.wait(10), "el sintetizador falso quedó bloqueado"
        self.llamadas.append((fonemas, voz, lang))
        salida = Path(salida)
        salida.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(salida), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(8000)
            w.writeframes(b"\x01\x00" * int(8000 * self.duracion))
        return self.duracion

    def voces(self):
        return ["am_michael", "em_santa"]


@pytest.fixture
def servicio_dj(tmp_path):
    """Fábrica del servicio DJ real (parte 2a) en un hilo, con un sintetizador falso: `servicio_dj(duracion=3.0)`."""
    import random
    import threading

    from cassette_fm.dj.cola import Cola
    from cassette_fm.dj.config import ConfigServicioDJ, RutasDJ
    from cassette_fm.dj.guiones import RegistroGuiones
    from cassette_fm.dj.lexico import Lexico
    from cassette_fm.dj.modo import ModoDJ
    from cassette_fm.dj.produccion import Productor
    from cassette_fm.dj.servidor import crear_servidor

    creados = []

    def crear(duracion: float = 3.0):
        base = tmp_path / f"dj{len(creados)}"
        s = SimpleNamespace()
        s.rutas = RutasDJ(config=base / "cfg" / "config.toml", estado=base / "estado", clips=base / "clips")
        config = ConfigServicioDJ(modelos_dir=base / "sin-modelos")
        s.sintetizador = SintetizadorFalso(duracion)
        s.guiones = RegistroGuiones(s.rutas.guiones)
        productor = Productor(config, s.rutas, s.sintetizador, lambda t, lang: t, Lexico(), s.guiones,
                              azar=random.Random(1))
        s.cola = Cola(productor, trabajadores=1)
        s.modo = ModoDJ()
        s.servidor = crear_servidor(s.cola, s.sintetizador, "127.0.0.1", 0, config.modelos_dir, modo=s.modo,
                                    probar_llm=lambda: True)
        threading.Thread(target=lambda: s.servidor.serve_forever(poll_interval=0.02), daemon=True,
                         name="dj-http-test").start()
        s.url = f"http://127.0.0.1:{s.servidor.server_address[1]}"
        creados.append(s)
        return s

    yield crear
    for s in creados:
        if s.sintetizador.puerta is not None:
            s.sintetizador.puerta.set()
        s.servidor.shutdown()
        s.servidor.server_close()
        s.cola.detener(2)


@pytest.fixture
def servidor_http():
    """Servidor HTTP de pruebas: `s.responder(prefijo, cuerpo, codigo=200, tipo="application/json", demora=0)`
    (cuerpo: str/bytes/objeto JSON/callable(ruta_con_query) -> lo mismo o (código, cuerpo)). `s.pedidos`: [(ruta_con_query, headers)];
    `s.cuerpos`: [(ruta, cuerpo)] de los POST y PUT."""
    import json
    import threading
    import time
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class S:
        def __init__(self):
            self.reglas = []
            self.pedidos = []
            self.cuerpos = []          # (ruta, cuerpo) de cada POST
            self.lock = threading.Lock()

        def responder(self, prefijo, cuerpo, codigo=200, tipo="application/json", demora=0.0, encabezados=None):
            self.reglas.append((prefijo, cuerpo, codigo, tipo, demora, encabezados or {}))

    s = S()

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            largo = int(self.headers.get("Content-Length") or 0)
            datos = self.rfile.read(largo) if largo else b""
            with s.lock:
                s.cuerpos.append((self.path, datos))
            self.do_GET()

        do_PUT = do_POST

        def do_GET(self):
            with s.lock:
                s.pedidos.append((self.path, dict(self.headers)))
            for prefijo, cuerpo, codigo, tipo, demora, *resto in s.reglas:   # hay tests que insertan reglas sin encabezados
                encabezados = resto[0] if resto else {}
                if self.path.startswith(prefijo):
                    if demora:
                        time.sleep(demora)
                    if callable(cuerpo):
                        cuerpo = cuerpo(self.path)
                        if isinstance(cuerpo, tuple):        # (código, cuerpo): respuestas que cambian
                            codigo, cuerpo = cuerpo
                    if not isinstance(cuerpo, (str, bytes)):
                        cuerpo = json.dumps(cuerpo)
                    datos = cuerpo.encode() if isinstance(cuerpo, str) else cuerpo
                    try:
                        self.send_response(codigo)
                        self.send_header("Content-Type", tipo)
                        self.send_header("Content-Length", str(len(datos)))
                        for clave, valor in encabezados.items():
                            self.send_header(clave, valor)
                        self.end_headers()
                        self.wfile.write(datos)
                    except OSError:
                        pass
                    return
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    srv.daemon_threads = True
    threading.Thread(target=lambda: srv.serve_forever(poll_interval=0.02), daemon=True).start()
    s.url = f"http://127.0.0.1:{srv.server_address[1]}"
    yield s
    srv.shutdown()
    srv.server_close()


@pytest.fixture(autouse=True)
def _sin_bus_de_sesion(monkeypatch, tmp_path):
    """Ningún test toca el bus de sesión real: la radio aparecería en el applet y le robaría las teclas al usuario."""
    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", f"unix:path={tmp_path}/sin-bus")


@pytest.fixture
def bus_privado(dir_corto):
    """Un dbus-daemon propio para el test; devuelve su dirección."""
    config = dir_corto / "bus.conf"
    config.write_text(
        "<!DOCTYPE busconfig PUBLIC \"-//freedesktop//DTD D-Bus Bus Configuration 1.0//EN\" "
        "\"http://www.freedesktop.org/standards/dbus/1.0/busconfig.dtd\">"
        f"<busconfig><type>session</type><listen>unix:path={dir_corto}/bus</listen>"
        "<policy context=\"default\"><allow send_destination=\"*\" eavesdrop=\"true\"/>"
        "<allow eavesdrop=\"true\"/><allow own=\"*\"/></policy></busconfig>")
    proceso = subprocess.Popen(["dbus-daemon", f"--config-file={config}", "--nofork", "--print-address"],
                               stdout=subprocess.PIPE, text=True)
    direccion = proceso.stdout.readline().strip()
    yield direccion
    proceso.terminate()
    proceso.wait(5)


class _AudioRouterInerte:
    """Con `bus_audio` prendido por defecto, ningún test debe tocar el audio real de quien lo corre."""
    local_monitor_enabled = False

    def create_bus(self): pass
    def env(self): return None
    def set_local_volume(self, percent): pass
    def enable_local_monitor(self): self.local_monitor_enabled = True
    def disable_local_monitor(self): self.local_monitor_enabled = False
    def close(self): pass


@pytest.fixture(autouse=True)
def _sin_audio_real(monkeypatch):
    monkeypatch.setattr("cassette_fm.servicio.AudioRouter", _AudioRouterInerte)

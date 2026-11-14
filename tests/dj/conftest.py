import os
from pathlib import Path
from types import SimpleNamespace

import pytest


class KokoroFalso:
    """Imita lo que usa el Sintetizador de kokoro_onnx.Kokoro."""

    def __init__(self, estado):
        self.estado = estado

    def create(self, text, voice, speed=1.0, lang="en-us", is_phonemes=False, trim=True,
               sentence_pause=0.25, clause_pause=0.1, continuous=False):
        self.estado.llamadas.append(dict(text=text, voice=voice, speed=speed, lang=lang, is_phonemes=is_phonemes,
                                         sentence_pause=sentence_pause, clause_pause=clause_pause,
                                         continuous=continuous))
        import numpy as np
        return np.zeros(12000, dtype=np.float32), 24000        # 0,5 s de silencio

    def get_voices(self):
        return ["am_michael", "em_alex", "em_santa"]

    def get_voice_style(self, nombre):
        import numpy as np
        return np.full((4, 1, 3), float({"am_michael": 1, "em_alex": 3, "em_santa": 5}[nombre]), dtype=np.float32)


@pytest.fixture
def fabrica_falsa():
    estado = SimpleNamespace(cargas=0, llamadas=[])

    def fabrica():
        estado.cargas += 1
        return KokoroFalso(estado)

    fabrica.estado = estado
    return fabrica


@pytest.fixture
def modelos_reales() -> Path:
    """Directorio con los modelos reales de Kokoro (CASSETTE_DJ_MODELOS o el default); si faltan, se saltea el test."""
    from cassette_fm.dj.sintetizador import faltan_modelos
    ruta = Path(os.environ.get("CASSETTE_DJ_MODELOS", Path.home() / ".local/share/cassette-dj/modelos"))
    if faltan_modelos(ruta):
        pytest.skip("faltan los modelos de Kokoro (cassette-dj modelos o CASSETTE_DJ_MODELOS)")
    return ruta


@pytest.fixture
def hacer_pedido():
    """Fábrica de pedidos válidos: hacer_pedido("id1", idioma="en", voz="am_michael", ...)."""
    from cassette_fm.dj.pedido import leer_pedido

    def hacer(id_="p1", **cambios):
        datos = {
            "id": id_, "estacion": "Lentos", "idioma": "es", "voz": "em_santa",
            "momento": "2026-11-13T21:47:00-03:00",
            "anterior": {"artista": "Whitesnake", "titulo": "Is This Love", "album": "Slip of the Tongue"},
            "siguiente": {"artista": "Foreigner", "titulo": "Waiting for a Girl Like You"},
            "recientes": [],
        }
        datos.update(cambios)
        return leer_pedido(datos)

    return hacer


@pytest.fixture
def servidor_http():
    """Servidor HTTP de pruebas: `s.responder(prefijo, cuerpo, codigo=200, tipo="application/json", demora=0)`
    (cuerpo: str/bytes/objeto JSON/callable(ruta_con_query) -> lo mismo). `s.pedidos`: [(ruta_con_query, headers)]."""
    import json
    import threading
    import time
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class S:
        def __init__(self):
            self.reglas = []
            self.pedidos = []
            self.lock = threading.Lock()

        def responder(self, prefijo, cuerpo, codigo=200, tipo="application/json", demora=0.0):
            self.reglas.append((prefijo, cuerpo, codigo, tipo, demora))

    s = S()

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            with s.lock:
                s.pedidos.append((self.path, dict(self.headers)))
            for prefijo, cuerpo, codigo, tipo, demora in s.reglas:
                if self.path.startswith(prefijo):
                    if demora:
                        time.sleep(demora)
                    if callable(cuerpo):
                        cuerpo = cuerpo(self.path)
                    if not isinstance(cuerpo, (str, bytes)):
                        cuerpo = json.dumps(cuerpo)
                    datos = cuerpo.encode() if isinstance(cuerpo, str) else cuerpo
                    try:
                        self.send_response(codigo)
                        self.send_header("Content-Type", tipo)
                        self.send_header("Content-Length", str(len(datos)))
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


@pytest.fixture
def llm_falso():
    """Servidor que imita la API de OpenAI de Ollama: `POST /v1/chat/completions` y `GET /v1/models`.

    `l.respuestas`: lista de textos o callables(pedido) -> texto (se consumen en orden; la última se repite).
    `l.cuerpo_crudo` / `l.codigo` / `l.demora`: pisan lo que se contesta. `l.pedidos`: los JSON recibidos."""
    import json
    import threading
    import time
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class L:
        def __init__(self):
            self.respuestas = ["Ahora suena Gasolina de Daddy Yankee."]
            self.cuerpo_crudo = None
            self.codigo = 200
            self.demora = 0.0
            self.modelos = [{"id": "gemma3:4b"}]
            self.codigo_modelos = 200
            self.pedidos = []
            self.lock = threading.Lock()

        def _siguiente(self, pedido):
            with self.lock:
                r = self.respuestas.pop(0) if len(self.respuestas) > 1 else self.respuestas[0]
            return r(pedido) if callable(r) else r

    l = L()

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _responder(self, codigo, datos, tipo="application/json"):
            cuerpo = datos if isinstance(datos, bytes) else (datos if isinstance(datos, str) else json.dumps(datos)).encode()
            try:
                self.send_response(codigo)
                self.send_header("Content-Type", tipo)
                self.send_header("Content-Length", str(len(cuerpo)))
                self.end_headers()
                self.wfile.write(cuerpo)
            except OSError:
                pass

        def do_GET(self):
            if self.path == "/v1/models":
                return self._responder(l.codigo_modelos, {"data": l.modelos})
            self._responder(404, "no")

        def do_POST(self):
            if self.path != "/v1/chat/completions":
                return self._responder(404, "no")
            largo = int(self.headers.get("Content-Length") or 0)
            pedido = json.loads(self.rfile.read(largo).decode("utf-8"))
            with l.lock:
                l.pedidos.append(pedido)
            if l.demora:
                time.sleep(l.demora)
            if l.cuerpo_crudo is not None:
                return self._responder(l.codigo, l.cuerpo_crudo, "text/html" if isinstance(l.cuerpo_crudo, str) else
                                       "application/json")
            texto = l._siguiente(pedido)
            if isinstance(texto, Exception):
                return self._responder(500, "boom")
            self._responder(l.codigo, {"choices": [{"index": 0, "message": {"role": "assistant", "content": texto}}]})

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    srv.daemon_threads = True
    threading.Thread(target=lambda: srv.serve_forever(poll_interval=0.02), daemon=True).start()
    l.url = f"http://127.0.0.1:{srv.server_address[1]}/v1"
    yield l
    srv.shutdown()
    srv.server_close()

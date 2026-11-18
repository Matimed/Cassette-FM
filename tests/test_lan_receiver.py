import importlib.util
import json
import os
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

RUTA = Path(__file__).resolve().parents[1] / "applet" / "cassette-fm@cassette-fm" / "lan_receiver.py"
TOKEN = "clave-del-receptor-123"


def _cargar():
    spec = importlib.util.spec_from_file_location("lan_receiver", RUTA)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


lan_receiver = _cargar()


def _wav_cabecera():
    import struct
    return (b"RIFF" + struct.pack("<I", 0x7FFFFFF0) + b"WAVEfmt " + struct.pack("<IHHIIHH", 16, 1, 1, 8000, 16000, 2, 16)
            + b"data" + struct.pack("<I", 0x7FFFFF00))


class ServidorFalso:
    def __init__(self):
        self.pedidos_stream = []
        self.stream_ok = True
        self.token = TOKEN
        servidor = self

        class Manejador(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.0"

            def log_message(self, *a):
                pass

            def _autorizado(self):
                return self.headers.get("Authorization") == f"Bearer {servidor.token}"

            def do_GET(self):
                if not self._autorizado():
                    self.send_response(401)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                if self.path == "/status":
                    cuerpo = json.dumps({"encendida": True, "estaciones": []}).encode()
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(cuerpo)))
                    self.end_headers()
                    self.wfile.write(cuerpo)
                elif self.path == "/stream":
                    servidor.pedidos_stream.append(self.headers.get("Authorization"))
                    if not servidor.stream_ok:
                        self.send_response(503)
                        self.send_header("Content-Length", "0")
                        self.end_headers()
                        return
                    self.send_response(200)
                    self.send_header("Content-Type", "audio/x-wav")
                    self.end_headers()
                    try:
                        self.wfile.write(_wav_cabecera())
                        while True:
                            self.wfile.write(b"\0" * 1600)      # 0,1 s de silencio a 8 kHz
                            time.sleep(0.1)
                    except OSError:
                        pass

        self.http = ThreadingHTTPServer(("127.0.0.1", 0), Manejador)
        self.http.daemon_threads = True
        self.puerto = self.http.server_address[1]
        threading.Thread(target=self.http.serve_forever, daemon=True).start()

    @property
    def url(self):
        return f"http://127.0.0.1:{self.puerto}"

    def cerrar(self):
        self.http.shutdown()
        self.http.server_close()


@pytest.fixture
def servidor():
    s = ServidorFalso()
    yield s
    s.cerrar()


@pytest.fixture
def entorno(dir_corto, servidor):
    env = {"PATH": os.environ["PATH"], "HOME": os.environ.get("HOME", "/"), "CASSETTE_LAN_URL": servidor.url,
           "CASSETTE_LAN_TOKEN": TOKEN, "CASSETTE_LAN_RUNTIME": str(dir_corto / "lan"),
           "CASSETTE_LAN_MPV_ARGS": "--ao=null"}
    yield env
    lan_receiver.main(["off"], env)


def esperar(condicion, timeout=8.0):
    fin = time.monotonic() + timeout
    while time.monotonic() < fin:
        if condicion():
            return True
        time.sleep(0.05)
    return False


def estado(env, capsys):
    capsys.readouterr()
    assert lan_receiver.main(["status", "--json"], env) == 0
    return json.loads(capsys.readouterr().out)


def procesos_mpv(env):
    socket_ipc = str(Path(env["CASSETTE_LAN_RUNTIME"]) / "mpv.sock")
    encontrados = []
    for pid in os.listdir("/proc"):
        if pid.isdigit():
            try:
                linea = Path(f"/proc/{pid}/cmdline").read_bytes().decode(errors="replace")
            except OSError:
                continue
            if socket_ipc in linea:
                encontrados.append((int(pid), linea))
    return encontrados


def test_on_deja_un_mpv_sonando_y_status_lo_ve(entorno, servidor, capsys):
    assert lan_receiver.main(["on"], entorno) == 0
    assert esperar(lambda: servidor.pedidos_stream)
    assert servidor.pedidos_stream[0] == f"Bearer {TOKEN}"
    assert esperar(lambda: estado(entorno, capsys)["escuchando"] is True)
    assert estado(entorno, capsys)["error"] is None


def test_dos_on_seguidos_dejan_un_solo_mpv(entorno, servidor):
    assert lan_receiver.main(["on"], entorno) == 0
    assert lan_receiver.main(["on"], entorno) == 0
    assert len(procesos_mpv(entorno)) == 1


def test_dos_on_a_la_vez_dejan_un_solo_mpv(entorno):
    resultados = []
    hilos = [threading.Thread(target=lambda: resultados.append(lan_receiver.main(["on"], entorno))) for _ in range(3)]
    [h.start() for h in hilos]
    [h.join(15) for h in hilos]
    assert resultados == [0, 0, 0] and len(procesos_mpv(entorno)) == 1


def test_on_con_socket_viejo_sin_mpv_lo_recrea(entorno):
    runtime = Path(entorno["CASSETTE_LAN_RUNTIME"])
    runtime.mkdir(parents=True, exist_ok=True)
    viejo = socket.socket(socket.AF_UNIX)
    viejo.bind(str(runtime / "mpv.sock"))            # un socket que nadie atiende
    viejo.close()
    assert lan_receiver.main(["on"], entorno) == 0
    assert len(procesos_mpv(entorno)) == 1


def test_off_cierra_el_mpv_y_es_idempotente(entorno, capsys):
    lan_receiver.main(["on"], entorno)
    assert lan_receiver.main(["off"], entorno) == 0
    assert esperar(lambda: not procesos_mpv(entorno))
    assert lan_receiver.main(["off"], entorno) == 0
    assert estado(entorno, capsys)["escuchando"] is False


def test_off_sin_haber_prendido_no_falla(entorno):
    assert lan_receiver.main(["off"], entorno) == 0


def test_volume_se_aplica_se_recuerda_y_se_reaplica_en_el_proximo_on(entorno, capsys):
    assert lan_receiver.main(["volume", "40"], entorno) == 0
    assert estado(entorno, capsys)["volumen"] == 40          # sin mpv, solo se recuerda
    lan_receiver.main(["on"], entorno)
    ruta = Path(entorno["CASSETTE_LAN_RUNTIME"]) / "mpv.sock"
    assert lan_receiver.ipc(ruta, ["get_property", "volume"])["data"] == 40
    lan_receiver.main(["volume", "+10"], entorno)
    assert lan_receiver.ipc(ruta, ["get_property", "volume"])["data"] == 50
    lan_receiver.main(["off"], entorno)
    lan_receiver.main(["on"], entorno)
    assert lan_receiver.ipc(ruta, ["get_property", "volume"])["data"] == 50


@pytest.mark.parametrize("pedido, esperado", [("-100", 0), ("500", 100), ("+500", 100), ("0", 0)])
def test_volume_se_acota_a_0_100(entorno, capsys, pedido, esperado):
    assert lan_receiver.main(["volume", pedido], entorno) == 0
    assert estado(entorno, capsys)["volumen"] == esperado


def test_volume_invalido_falla_sin_cambiar_nada(entorno, capsys):
    lan_receiver.main(["volume", "30"], entorno)
    assert lan_receiver.main(["volume", "abc"], entorno) == 2
    assert estado(entorno, capsys)["volumen"] == 30


def test_la_clave_no_esta_en_la_linea_de_comandos_de_mpv(entorno, servidor):
    lan_receiver.main(["on"], entorno)
    assert esperar(lambda: servidor.pedidos_stream)
    (pid, linea), = procesos_mpv(entorno)
    assert TOKEN not in linea and "Bearer" not in linea


def test_status_con_clave_rechazada(entorno, capsys):
    entorno["CASSETTE_LAN_TOKEN"] = "mala"
    lan_receiver.main(["on"], entorno)
    assert esperar(lambda: estado(entorno, capsys)["error"] == "clave rechazada")
    assert estado(entorno, capsys)["escuchando"] is False


def test_status_con_servidor_caido(entorno, servidor, capsys):
    entorno["CASSETTE_LAN_URL"] = "http://127.0.0.1:1"
    lan_receiver.main(["on"], entorno)
    assert esperar(lambda: estado(entorno, capsys)["error"] == "sin conexión")


def test_status_con_mpv_ocioso_y_servidor_ok_vuelve_a_cargar_el_stream(entorno, servidor, capsys):
    servidor.stream_ok = False
    lan_receiver.main(["on"], entorno)
    assert esperar(lambda: len(servidor.pedidos_stream) >= 1)
    time.sleep(0.5)
    servidor.stream_ok = True
    # el applet consulta `status` cada tanto: una consulta que cae con la carga fallida todavía en curso no recarga, la
    # siguiente sí
    assert esperar(lambda: estado(entorno, capsys) is not None and len(servidor.pedidos_stream) >= 2)
    assert esperar(lambda: estado(entorno, capsys)["escuchando"] is True)


def test_sin_variables_de_entorno_falla_con_un_mensaje_claro(entorno, capsys):
    vacio = {k: v for k, v in entorno.items() if not k.startswith("CASSETTE_LAN_URL") and k != "CASSETTE_LAN_TOKEN"}
    capsys.readouterr()
    assert lan_receiver.main(["on"], vacio) == 1
    err = capsys.readouterr().err
    assert "CASSETTE_LAN_URL" in err and "CASSETTE_LAN_TOKEN" in err

import importlib.util
import json
import os
import socket
import threading
import time
import urllib.parse
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
        self.pedidos_icono = []
        self.con_logo = ["Pop Hits F.M.", "A"]
        self.version = "v1"
        self.stream_ok = True
        self.motivo = None
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
                if self.path.startswith("/icon/"):
                    servidor.pedidos_icono.append(self.path)
                    cuerpo = b"\x89PNG" + servidor.version.encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "image/png")
                    self.send_header("Content-Length", str(len(cuerpo)))
                    self.end_headers()
                    self.wfile.write(cuerpo)
                elif self.path == "/status":
                    iconos = {n: f"/icon/{urllib.parse.quote(n, safe='')}?v={servidor.version}" for n in servidor.con_logo}
                    cuerpo = json.dumps({"encendida": True, "estaciones": [], "iconos": iconos}).encode()
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(cuerpo)))
                    self.end_headers()
                    self.wfile.write(cuerpo)
                elif self.path == "/stream":
                    servidor.pedidos_stream.append(self.headers.get("Authorization"))
                    if not servidor.stream_ok:
                        cuerpo = json.dumps({"error": servidor.motivo}).encode() if servidor.motivo else b""
                        self.send_response(503)
                        self.send_header("Content-Length", str(len(cuerpo)))
                        self.end_headers()
                        self.wfile.write(cuerpo)
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
           "CASSETTE_LAN_CACHE": str(dir_corto / "cache"),
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


def iconos(env, capsys):
    capsys.readouterr()
    codigo = lan_receiver.main(["icons"], env)
    return codigo, capsys.readouterr().out


def test_icons_baja_los_logos_y_devuelve_las_rutas_locales(entorno, servidor, capsys):
    codigo, salida = iconos(entorno, capsys)
    mapa = json.loads(salida)
    assert codigo == 0 and set(mapa) == {"Pop Hits F.M.", "A"}
    for ruta in mapa.values():
        assert Path(ruta).is_file() and Path(ruta).read_bytes().startswith(b"\x89PNG") and ruta.endswith(".png")
    assert len(servidor.pedidos_icono) == 2


def test_icons_no_vuelve_a_bajar_los_que_no_cambiaron(entorno, servidor, capsys):
    iconos(entorno, capsys)
    codigo, salida = iconos(entorno, capsys)
    assert codigo == 0 and len(servidor.pedidos_icono) == 2 and len(json.loads(salida)) == 2


def test_icons_baja_de_nuevo_solo_los_que_cambiaron_y_borra_la_version_vieja(entorno, servidor, capsys):
    primero = json.loads(iconos(entorno, capsys)[1])
    servidor.version = "v2"
    segundo = json.loads(iconos(entorno, capsys)[1])
    assert len(servidor.pedidos_icono) == 4 and segundo != primero
    assert not Path(primero["A"]).exists() and Path(segundo["A"]).is_file()


def test_icons_con_el_logo_sacado_del_servidor_lo_quita_del_mapa_y_de_la_cache(entorno, servidor, capsys):
    primero = json.loads(iconos(entorno, capsys)[1])
    servidor.con_logo = ["A"]
    segundo = json.loads(iconos(entorno, capsys)[1])
    assert set(segundo) == {"A"} and not Path(primero["Pop Hits F.M."]).exists()


def test_icons_sin_logos_devuelve_un_mapa_vacio(entorno, servidor, capsys):
    servidor.con_logo = []
    assert iconos(entorno, capsys) == (0, "{}\n")


def test_icons_con_clave_mala_o_servidor_caido_falla_sin_imprimir_un_mapa(entorno, capsys):
    entorno["CASSETTE_LAN_TOKEN"] = "mala"
    codigo, salida = iconos(entorno, capsys)
    assert codigo == 1 and salida == ""
    entorno["CASSETTE_LAN_URL"] = "http://127.0.0.1:1"
    assert iconos(entorno, capsys)[0] == 1


def test_icons_tolera_nombres_con_caracteres_raros_y_no_escribe_fuera_de_la_cache(entorno, servidor, capsys):
    servidor.con_logo = ["../../../etc/x", "¿Qué?"]
    mapa = json.loads(iconos(entorno, capsys)[1])
    cache = Path(entorno["CASSETTE_LAN_CACHE"]).resolve()
    assert len(mapa) == 2 and all(Path(r).resolve().parent == cache for r in mapa.values())


def test_status_no_dice_escuchando_si_el_stream_es_rechazado_y_cuenta_el_motivo(entorno, servidor, capsys):
    servidor.stream_ok, servidor.motivo = False, "ya hay 4 oyentes"
    lan_receiver.main(["on"], entorno)
    assert esperar(lambda: len(servidor.pedidos_stream) >= 1)
    assert esperar(lambda: "ya hay 4 oyentes" in (estado(entorno, capsys)["error"] or ""))
    assert estado(entorno, capsys)["escuchando"] is False


def test_status_con_stream_rechazado_sin_motivo_dice_que_el_servidor_lo_rechazo(entorno, servidor, capsys):
    servidor.stream_ok = False
    lan_receiver.main(["on"], entorno)
    assert esperar(lambda: (estado(entorno, capsys)["error"] or "").startswith("stream"))
    assert estado(entorno, capsys)["escuchando"] is False


def test_on_con_un_mpv_colgado_lo_corta_y_deja_uno_solo(entorno):
    import subprocess
    import sys
    runtime = Path(entorno["CASSETTE_LAN_RUNTIME"])
    runtime.mkdir(parents=True, exist_ok=True)
    socket_ipc = runtime / "mpv.sock"
    colgado = subprocess.Popen([sys.executable, "-c",
                                "import socket,sys,time;s=socket.socket(socket.AF_UNIX);s.bind(sys.argv[1]);s.listen();"
                                "time.sleep(600)", str(socket_ipc)])
    try:
        assert esperar(lambda: socket_ipc.exists())
        (runtime / "pid").write_text(str(colgado.pid))
        assert lan_receiver.main(["on"], entorno) == 0
        assert colgado.wait(timeout=5) is not None            # el viejo ya no existe
        assert len(procesos_mpv(entorno)) == 1
    finally:
        colgado.kill()
        colgado.wait()


def test_on_con_otra_direccion_vuelve_a_cargar_el_stream_del_servidor_nuevo(entorno, servidor):
    otro = ServidorFalso()
    try:
        assert lan_receiver.main(["on"], entorno) == 0
        assert esperar(lambda: servidor.pedidos_stream)
        entorno2 = dict(entorno, CASSETTE_LAN_URL=otro.url)
        assert lan_receiver.main(["on"], entorno2) == 0
        assert esperar(lambda: otro.pedidos_stream)
        assert len(procesos_mpv(entorno)) == 1
    finally:
        otro.cerrar()

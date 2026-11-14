import socket
import threading
import time
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from cassette_fm.cliente_dj import ClienteDJ, ErrorDJ


def pedido(id_="p1", **cambios):
    d = {"id": id_, "estacion": "Lentos", "idioma": "es", "voz": "em_santa", "momento": "2026-11-13T21:47:00-03:00",
         "anterior": {"artista": "Whitesnake", "titulo": "Is This Love"},
         "siguiente": {"artista": "Foreigner", "titulo": "Waiting for a Girl Like You"}, "recientes": []}
    d.update(cambios)
    return d


def esperar(cliente, id_, estados=("listo", "error", "cancelado"), timeout=5.0):
    fin = time.monotonic() + timeout
    while time.monotonic() < fin:
        e = cliente.estado(id_)
        if e and e["estado"] in estados:
            return e
        time.sleep(0.02)
    raise AssertionError("el trabajo no terminó")


def servidor_a_mano(manejador):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), manejador)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


def test_enviar_y_consultar_hasta_listo(servicio_dj):
    s = servicio_dj()
    c = ClienteDJ(s.url)
    id_ = c.enviar(pedido())
    assert id_ == "p1"
    e = esperar(c, id_)
    assert e["estado"] == "listo" and e["duracion"] == pytest.approx(3.0, abs=0.01) and e["texto"]


def test_estado_de_un_id_desconocido_es_None(servicio_dj):
    assert ClienteDJ(servicio_dj().url).estado("nada") is None


def test_descargar_audio_escribe_un_wav_valido(servicio_dj, tmp_path):
    c = ClienteDJ(servicio_dj().url)
    id_ = c.enviar(pedido())
    esperar(c, id_)
    destino = tmp_path / "bajados" / "p1.wav"
    assert c.descargar_audio(id_, destino) == destino
    with wave.open(str(destino)) as w:
        assert w.getnframes() / w.getframerate() == pytest.approx(3.0, abs=0.01)
    assert not list(destino.parent.glob("*.part"))


def test_descargar_un_trabajo_no_listo_da_ErrorDJ(servicio_dj, tmp_path):
    s = servicio_dj()
    s.sintetizador.puerta = threading.Event()
    c = ClienteDJ(s.url)
    id_ = c.enviar(pedido())
    with pytest.raises(ErrorDJ, match="todavía no está listo"):
        c.descargar_audio(id_, tmp_path / "x.wav")
    assert not (tmp_path / "x.wav").exists()
    with pytest.raises(ErrorDJ):
        c.descargar_audio("no-existe", tmp_path / "y.wav")


def test_cancelar_pendiente_si_y_desconocido_no(servicio_dj):
    s = servicio_dj()
    s.sintetizador.puerta = threading.Event()
    c = ClienteDJ(s.url)
    c.enviar(pedido("uno"))          # ocupa al único trabajador
    time.sleep(0.2)
    c.enviar(pedido("dos"))          # queda pendiente
    assert c.cancelar("dos") is True
    assert c.cancelar("desconocido") is False


def test_pedido_invalido_da_ErrorDJ_con_el_mensaje_del_servicio(servicio_dj):
    c = ClienteDJ(servicio_dj().url)
    malo = pedido()
    del malo["siguiente"]
    with pytest.raises(ErrorDJ, match="siguiente"):
        c.enviar(malo)


def test_servicio_caido_da_ErrorDJ_claro():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        puerto = s.getsockname()[1]
    url = f"http://127.0.0.1:{puerto}"
    with pytest.raises(ErrorDJ) as e:
        ClienteDJ(url, timeout=1).salud()
    assert "no responde" in str(e.value) and url in str(e.value)


def test_servicio_que_no_contesta_da_ErrorDJ_por_timeout():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        s.listen(5)
        t0 = time.monotonic()
        with pytest.raises(ErrorDJ, match="no responde"):
            ClienteDJ(f"http://127.0.0.1:{s.getsockname()[1]}", timeout=0.3).salud()
        assert time.monotonic() - t0 < 3


def test_respuesta_que_no_es_json_da_ErrorDJ():
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            cuerpo = b"<html>hola</html>"
            self.send_response(200)
            self.send_header("Content-Length", str(len(cuerpo)))
            self.end_headers()
            self.wfile.write(cuerpo)

    srv, url = servidor_a_mano(H)
    try:
        with pytest.raises(ErrorDJ, match="ilegible"):
            ClienteDJ(url).salud()
        with pytest.raises(ErrorDJ, match="ilegible"):
            ClienteDJ(url).estado("p1")
    finally:
        srv.shutdown()
        srv.server_close()


@pytest.mark.parametrize("cuerpo, largo_extra", [(b"RIFF" + b"\0" * 20, 100), (b"<html>no soy wav</html>", 0)])
def test_audio_truncado_o_que_no_es_wav_da_ErrorDJ_y_no_deja_archivo(tmp_path, cuerpo, largo_extra):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Length", str(len(cuerpo) + largo_extra))
            self.end_headers()
            self.wfile.write(cuerpo)
            self.close_connection = True

    srv, url = servidor_a_mano(H)
    try:
        with pytest.raises(ErrorDJ):
            ClienteDJ(url, timeout=2).descargar_audio("p1", tmp_path / "a.wav")
    finally:
        srv.shutdown()
        srv.server_close()
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("id_", ["../x", "a/b", "", "a" * 65, "x y"])
def test_id_peligroso_da_ValueError(id_, tmp_path):
    c = ClienteDJ("http://127.0.0.1:9")
    for llamada in (c.estado, c.cancelar, lambda i: c.descargar_audio(i, tmp_path / "x.wav")):
        with pytest.raises(ValueError):
            llamada(id_)


def test_salud(servicio_dj):
    s = ClienteDJ(servicio_dj().url).salud()
    assert s["ok"] is True and "trabajos" in s


def test_modo_y_poner_modo(servicio_dj):
    s = servicio_dj()
    c = ClienteDJ(s.url)
    assert c.modo() == "plantillas"
    assert c.poner_modo("llm") == {"modo": "llm", "llm": "ok"} and c.modo() == "llm" and s.modo.actual() == "llm"
    assert c.poner_modo("plantillas") == {"modo": "plantillas"}


def test_poner_un_modo_invalido_da_ErrorDJ_con_el_mensaje(servicio_dj):
    c = ClienteDJ(servicio_dj().url)
    with pytest.raises(ErrorDJ, match="modo"):
        c.poner_modo("otro")
    assert c.modo() == "plantillas"


def test_modo_con_el_servicio_caido_da_ErrorDJ():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        puerto = s.getsockname()[1]
    c = ClienteDJ(f"http://127.0.0.1:{puerto}", timeout=1)
    for llamada in (c.modo, lambda: c.poner_modo("llm")):
        with pytest.raises(ErrorDJ, match="no responde"):
            llamada()


def test_modo_con_respuesta_ilegible_da_ErrorDJ():
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _r(self):
            cuerpo = b'{"otra": "cosa"}'
            self.send_response(200)
            self.send_header("Content-Length", str(len(cuerpo)))
            self.end_headers()
            self.wfile.write(cuerpo)

        do_GET = do_POST = _r

    srv, url = servidor_a_mano(H)
    try:
        with pytest.raises(ErrorDJ, match="ilegible"):
            ClienteDJ(url).modo()
        with pytest.raises(ErrorDJ, match="ilegible"):
            ClienteDJ(url).poner_modo("llm")
    finally:
        srv.shutdown()
        srv.server_close()

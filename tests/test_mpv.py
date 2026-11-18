import os
import signal
import time

import pytest

from cassette_fm.mpv import ClienteMpv, ErrorMpv


def esperar(condicion, timeout=5.0):
    fin = time.monotonic() + timeout
    while time.monotonic() < fin:
        if condicion():
            return True
        time.sleep(0.02)
    return False


@pytest.fixture
def mpv(dir_corto):
    cliente = ClienteMpv(dir_corto / "mpv.sock", extra_args=["--ao=null"])
    cliente.iniciar()
    yield cliente
    cliente.cerrar()


def test_propiedad_idle(mpv):
    assert mpv.comando("get_property", "idle-active") is True


def test_loadfile_con_start_y_eventos(mpv, crear_mp3, tmp_path):
    p = crear_mp3(tmp_path / "t.mp3", 5)
    eventos = []
    mpv.al_evento = lambda e: eventos.append(e["event"])
    mpv.comando("loadfile", url=str(p), flags="replace", options={"start": "1.5"})
    assert esperar(lambda: "file-loaded" in eventos)
    assert "start-file" in eventos
    assert esperar(lambda: (mpv.comando("get_property", "time-pos") or 0) >= 1.5)


def test_callback_puede_mandar_comandos(mpv, crear_mp3, tmp_path):
    p = crear_mp3(tmp_path / "t.mp3", 5)
    resultado = []

    def al_evento(e):
        if e["event"] == "file-loaded":
            resultado.append(mpv.comando("get_property", "path"))

    mpv.al_evento = al_evento
    mpv.comando("loadfile", url=str(p), flags="replace")
    assert esperar(lambda: resultado)
    assert resultado == [str(p)]


def test_error_de_mpv(mpv):
    with pytest.raises(ErrorMpv):
        mpv.comando("get_property", "no-existe")


def test_relanza_si_mpv_murio(mpv):
    pid = mpv._proceso.pid
    os.kill(pid, signal.SIGKILL)
    esperar(lambda: mpv._proceso.poll() is not None)
    assert mpv.comando("get_property", "idle-active") is True
    assert mpv._proceso.pid != pid


def test_cerrar_termina_el_proceso(dir_corto):
    cliente = ClienteMpv(dir_corto / "mpv.sock", extra_args=["--ao=null"])
    cliente.iniciar()
    proceso = cliente._proceso
    cliente.cerrar()
    assert proceso.poll() is not None


def test_generacion_sube_al_relanzar(mpv):
    g = mpv.generacion
    os.kill(mpv._proceso.pid, signal.SIGKILL)
    esperar(lambda: mpv._proceso.poll() is not None)
    mpv.asegurar()
    assert mpv.generacion == g + 1
    mpv.asegurar()
    assert mpv.generacion == g + 1


def test_al_perder_avisa_si_mpv_muere(mpv):
    avisos = []
    mpv.al_perder = lambda: avisos.append(1)
    os.kill(mpv._proceso.pid, signal.SIGKILL)
    assert esperar(lambda: avisos, 3)


def test_al_perder_no_avisa_al_cerrar(dir_corto):
    avisos = []
    cliente = ClienteMpv(dir_corto / "mpv.sock", extra_args=["--ao=null"])
    cliente.al_perder = lambda: avisos.append(1)
    cliente.iniciar()
    cliente.cerrar()
    time.sleep(0.3)
    assert avisos == []


def test_ignora_la_configuracion_del_usuario(dir_corto, monkeypatch, tmp_path):
    (tmp_path / "mpv").mkdir()
    (tmp_path / "mpv" / "mpv.conf").write_text("volume=33\n")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    cliente = ClienteMpv(dir_corto / "mpv.sock", extra_args=["--ao=null"])
    cliente.iniciar()
    try:
        assert cliente.comando("get_property", "volume") != 33
    finally:
        cliente.cerrar()


def test_conexion_vieja_no_entrega_eventos():
    import socket as sk
    from cassette_fm.mpv import _Conexion
    recibidos = []
    a, b = sk.socketpair()
    vigente = {"si": False}
    conexion = _Conexion(a, lambda: recibidos.append, vigente=lambda c: vigente["si"])
    b.sendall(b'{"event": "viejo"}\n')
    time.sleep(0.2)
    assert recibidos == []
    vigente["si"] = True
    b.sendall(b'{"event": "nuevo"}\n')
    assert esperar(lambda: recibidos == [{"event": "nuevo"}], 2)
    conexion.cerrar()
    b.close()


def test_excepcion_en_el_manejador_se_loguea(mpv, caplog):
    import logging
    caplog.set_level(logging.ERROR, logger="cassette_fm")

    def malo(e):
        raise RuntimeError("boom")

    mpv.al_evento = malo
    mpv.comando("loadfile", url="/no/existe.mp3", flags="replace")
    assert esperar(lambda: "boom" in caplog.text or "manejador" in caplog.text, 3)


def test_el_entorno_se_pasa_al_proceso_de_mpv(dir_corto, monkeypatch):
    capturado = {}

    def popen_falso(comando, **kw):
        capturado.update(kw)
        raise OSError("no se lanza de verdad")

    monkeypatch.setattr("cassette_fm.mpv.subprocess.Popen", popen_falso)
    entorno = {"PULSE_SINK": "radio_virtual"}
    with pytest.raises(OSError):
        ClienteMpv(dir_corto / "mpv.sock", env=entorno).iniciar()
    assert capturado["env"] == entorno


def test_sin_entorno_mpv_hereda_el_del_servicio(dir_corto, monkeypatch):
    capturado = {}

    def popen_falso(comando, **kw):
        capturado.update(kw)
        raise OSError("no se lanza de verdad")

    monkeypatch.setattr("cassette_fm.mpv.subprocess.Popen", popen_falso)
    with pytest.raises(OSError):
        ClienteMpv(dir_corto / "mpv.sock").iniciar()
    assert capturado["env"] is None

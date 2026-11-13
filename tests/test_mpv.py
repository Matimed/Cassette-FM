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

import stat
import threading
import time

import pytest

from cassette_fm import servicio
from cassette_fm.avisos import Notificador
from cassette_fm.config import Config, Rutas


@pytest.fixture
def notify_send_falso(tmp_path, monkeypatch):
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    log = tmp_path / "llamadas.log"
    script = bin_ / "notify-send"
    script.write_text(f'#!/bin/sh\nprintf "%s|" "$@" >> {log}\necho >> {log}\necho 42\n')
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", str(bin_))
    return log


def test_primer_aviso_sin_replace_y_luego_reemplaza(notify_send_falso):
    n = Notificador()
    n("Lentos", "10cc - I'm Not In Love")
    n.esperar()
    n("Lentos", "Otro tema")
    n.esperar()
    primera, segunda = notify_send_falso.read_text().splitlines()
    assert primera == "--app-name=cassette-fm|-p|Lentos|10cc - I'm Not In Love|"
    assert segunda == "--app-name=cassette-fm|--replace-id=42|-p|Lentos|Otro tema|"


def test_sin_notify_send_no_falla(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path))
    n = Notificador()
    n("A", "t")
    n.esperar()


def _servir_un_instante(tmp_path, dir_corto, monkeypatch, avisos):
    capturado = {}
    real = servicio.Radio

    class RadioEspia(real):
        def __init__(self, *a, **kw):
            capturado["avisar"] = kw.get("avisar")
            super().__init__(*a, **kw)

    monkeypatch.setattr(servicio, "Radio", RadioEspia)
    parar = threading.Event()
    parar.set()
    rutas = Rutas(tmp_path / "c.toml", tmp_path / "e.json", tmp_path / "d.json", dir_corto)
    servicio.servir(Config(raiz_musica=tmp_path / "x", puerto=0, avisos=avisos), rutas,
                    parar=parar, extra_args_mpv=["--ao=null"])
    return capturado["avisar"]


def test_servir_sin_avisos_si_config_lo_desactiva(tmp_path, dir_corto, monkeypatch):
    assert _servir_un_instante(tmp_path, dir_corto, monkeypatch, avisos=False) is None


def test_servir_con_avisos_usa_notificador(tmp_path, dir_corto, monkeypatch):
    assert isinstance(_servir_un_instante(tmp_path, dir_corto, monkeypatch, avisos=True), Notificador)


def _args_de_mpv(tmp_path, dir_corto, monkeypatch, **config):
    capturado = {}
    real = servicio.ClienteMpv

    class MpvEspia(real):
        def __init__(self, socket, extra_args=(), **kw):
            capturado["extra_args"] = list(extra_args)
            super().__init__(socket, extra_args, **kw)

    monkeypatch.setattr(servicio, "ClienteMpv", MpvEspia)
    parar = threading.Event()
    parar.set()
    rutas = Rutas(tmp_path / "c.toml", tmp_path / "e.json", tmp_path / "d.json", dir_corto)
    servicio.servir(Config(raiz_musica=tmp_path / "x", puerto=0, avisos=False, **config), rutas,
                    parar=parar, extra_args_mpv=["--ao=null"])
    return capturado["extra_args"]


def test_servir_normaliza_el_volumen_con_dynaudnorm(tmp_path, dir_corto, monkeypatch):
    args = _args_de_mpv(tmp_path, dir_corto, monkeypatch)
    assert "--af=dynaudnorm" in args and "--ao=null" in args


def test_servir_sin_normalizar_si_la_config_lo_desactiva(tmp_path, dir_corto, monkeypatch):
    assert "--af=dynaudnorm" not in _args_de_mpv(tmp_path, dir_corto, monkeypatch, normalizar=False)

import socket
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from cassette_fm.api import crear_servidor
from cassette_fm.cli import main
from cassette_fm.radio import EstacionInexistente


class RadioFalsa:
    def __init__(self):
        self.llamadas = []
        self.encendida = True
        self.error = None

    def _hacer(self, nombre, *args, **kw):
        self.llamadas.append((nombre, args, kw))
        if self.error:
            raise self.error

    def estado(self):
        return {"encendida": self.encendida, "estacion": "Regueton 2000",
                "pista": "Daddy Yankee - Gasolina" if self.encendida else None,
                "volumen": 70, "estaciones": ["Lentos", "Regueton 2000"]}

    def estaciones(self):
        return [SimpleNamespace(nombre="Lentos", pistas=(1,) * 37),
                SimpleNamespace(nombre="Regueton 2000", pistas=(1,) * 91)]

    def sintonizar(self, nombre): self._hacer("sintonizar", nombre)
    def siguiente(self): self._hacer("siguiente")
    def anterior(self): self._hacer("anterior")
    def encender(self): self._hacer("encender")
    def apagar(self): self._hacer("apagar")
    def alternar(self): self._hacer("alternar")
    def rescan(self): self._hacer("rescan")

    def volumen(self, valor=None, delta=None):
        self._hacer("volumen", valor=valor, delta=delta)


@pytest.fixture
def servicio(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    radio = RadioFalsa()
    srv = crear_servidor(radio, "127.0.0.1", 0, raiz=Path("/m"))
    threading.Thread(target=lambda: srv.serve_forever(poll_interval=0.02), daemon=True).start()
    srv.radio = radio
    srv.puerto = str(srv.server_address[1])
    yield srv
    srv.shutdown()
    srv.server_close()


def test_status_encendida(servicio, capsys):
    assert main(["status", "--puerto", servicio.puerto]) == 0
    assert capsys.readouterr().out.strip() == "▶ Regueton 2000 — Daddy Yankee - Gasolina (vol 70)"


def test_status_apagada(servicio, capsys):
    servicio.radio.encendida = False
    assert main(["status", "--puerto", servicio.puerto]) == 0
    assert capsys.readouterr().out.strip() == "⏹ apagada (vol 70)"


def test_puerto_antes_del_subcomando(servicio, capsys):
    assert main(["--puerto", servicio.puerto, "status"]) == 0


def test_puerto_sale_de_la_config(servicio, tmp_path, capsys):
    d = tmp_path / "cassette-fm"
    d.mkdir()
    (d / "config.toml").write_text(f"puerto = {servicio.puerto}\n")
    assert main(["status"]) == 0


def test_tune_con_espacios_sin_comillas(servicio):
    assert main(["tune", "Regueton", "2000", "--puerto", servicio.puerto]) == 0
    assert servicio.radio.llamadas == [("sintonizar", ("Regueton 2000",), {})]


def test_tune_con_acentos(servicio):
    assert main(["tune", "Música", "Ñandú", "--puerto", servicio.puerto]) == 0
    assert servicio.radio.llamadas == [("sintonizar", ("Música Ñandú",), {})]


@pytest.mark.parametrize("arg,esperado", [
    ("+5", {"valor": None, "delta": 5}),
    ("-5", {"valor": None, "delta": -5}),
    ("70", {"valor": 70, "delta": None}),
])
def test_vol_relativo_y_absoluto(servicio, arg, esperado):
    assert main(["vol", arg, "--puerto", servicio.puerto]) == 0
    assert servicio.radio.llamadas == [("volumen", (), esperado)]


def test_list_marca_la_actual(servicio, capsys):
    assert main(["list", "--puerto", servicio.puerto]) == 0
    assert capsys.readouterr().out.splitlines() == [
        "  Lentos (37 temas)", "▶ Regueton 2000 (91 temas)"]


@pytest.mark.parametrize("comando,ruta", [
    ("next", "siguiente"), ("prev", "anterior"), ("on", "encender"),
    ("off", "apagar"), ("toggle", "alternar"), ("rescan", "rescan")])
def test_acciones(servicio, capsys, comando, ruta):
    assert main([comando, "--puerto", servicio.puerto]) == 0
    assert servicio.radio.llamadas == [(ruta, (), {})]
    assert "Regueton 2000" in capsys.readouterr().out


def test_servicio_caido(capsys):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        libre = s.getsockname()[1]
    assert main(["status", "--puerto", str(libre)]) == 1
    err = capsys.readouterr().err
    assert "cassette-fm no está corriendo" in err and "systemctl --user start cassette-fm" in err


def test_error_de_api(servicio, capsys):
    servicio.radio.error = EstacionInexistente("la estación 'x' no existe")
    assert main(["tune", "x", "--puerto", servicio.puerto]) == 1
    assert "la estación 'x' no existe" in capsys.readouterr().err

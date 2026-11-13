import ast
import shutil

import pytest

from cassette_fm import atajos, cli
from cassette_fm.atajos import ATAJOS, RAIZ, instalar

EJE = "/home/u/.local/bin/cassette"
LISTA = "org.cinnamon.desktop.keybindings"
ENTRADA = "org.cinnamon.desktop.keybindings.custom-keybinding:" + RAIZ


class GsettingsFalso:
    """Imita `gsettings get/set` con los formatos de texto reales."""

    def __init__(self, lista="['custom0', 'custom1', '__dummy__']"):
        self.d = {(LISTA, "custom-list"): lista}
        self._entrada("custom0", "Albert", "albert toggle", "['Super_L']")
        self._entrada("custom1", "Diodon", "/usr/bin/diodon", "['<Super>v']")
        self.llamadas = []

    def _entrada(self, id_, nombre, comando, binding):
        base = f"{ENTRADA}{id_}/"
        self.d[(base, "name")] = repr(nombre)
        self.d[(base, "command")] = repr(comando)
        self.d[(base, "binding")] = binding

    def __call__(self, args):
        self.llamadas.append(args)
        accion, esquema, clave, *resto = args
        if accion == "get":
            defecto = "@as []" if clave == "binding" else "''"
            return self.d.get((esquema, clave), defecto)
        assert accion == "set"
        self.d[(esquema, clave)] = resto[0]
        return ""

    def lista(self):
        return ast.literal_eval(self.d[(LISTA, "custom-list")].removeprefix("@as "))

    def campo(self, id_, clave):
        v = self.d[(f"{ENTRADA}{id_}/", clave)]
        return ast.literal_eval(v.removeprefix("@as "))


def test_instala_los_cuatro_atajos_con_su_comando():
    gs = GsettingsFalso()
    instalar(EJE, gs)
    esperado = {
        "cassette-fm-siguiente": ("next", ["<Super><Alt>Right"]),
        "cassette-fm-anterior": ("prev", ["<Super><Alt>Left"]),
        "cassette-fm-volumen-mas": ("vol +10", ["<Super><Alt>Up"]),
        "cassette-fm-volumen-menos": ("vol -10", ["<Super><Alt>Down"]),
    }
    for id_, (accion, teclas) in esperado.items():
        assert gs.campo(id_, "command") == f"{EJE} {accion}"
        assert gs.campo(id_, "binding") == teclas
        assert gs.campo(id_, "name").startswith("cassette-fm")
    assert {a.id for a in ATAJOS} == set(esperado)


def test_conserva_la_lista_y_el_orden():
    gs = GsettingsFalso()
    instalar(EJE, gs)
    assert gs.lista() == ["custom0", "custom1", "cassette-fm-siguiente", "cassette-fm-anterior",
                          "cassette-fm-volumen-mas", "cassette-fm-volumen-menos", "__dummy__"]


def test_lista_vacia_con_formato_as():
    gs = GsettingsFalso(lista="@as []")
    instalar(EJE, gs)
    assert gs.lista() == [a.id for a in ATAJOS]


def test_es_idempotente():
    gs = GsettingsFalso()
    instalar(EJE, gs)
    antes = gs.lista()
    mensajes = instalar(EJE, gs)
    assert gs.lista() == antes
    assert all("actualizado" in m for m in mensajes)


def test_no_pisa_la_tecla_que_el_usuario_cambio():
    gs = GsettingsFalso()
    instalar(EJE, gs)
    gs.d[(f"{ENTRADA}cassette-fm-siguiente/", "binding")] = "['<Super>n']"
    instalar("/opt/otro/cassette", gs)
    assert gs.campo("cassette-fm-siguiente", "binding") == ["<Super>n"]
    assert gs.campo("cassette-fm-siguiente", "command") == "/opt/otro/cassette next"


def test_omite_tecla_ocupada_por_otro_atajo():
    gs = GsettingsFalso()
    gs._entrada("custom1", "Mi atajo", "xterm", "['<Super><Alt>Right']")
    mensajes = instalar(EJE, gs)
    assert "cassette-fm-siguiente" not in gs.lista()
    assert any("Mi atajo" in m and "omitido" in m for m in mensajes)
    assert {"cassette-fm-anterior", "cassette-fm-volumen-mas", "cassette-fm-volumen-menos"} <= set(gs.lista())


def test_los_valores_de_texto_se_escriben_como_gvariant():
    gs = GsettingsFalso()
    instalar(EJE, gs)
    sets = {tuple(a[1:4]) for a in gs.llamadas if a[0] == "set"}
    assert (f"{ENTRADA}cassette-fm-siguiente/", "command", repr(f"{EJE} next")) in sets


def test_cli_atajos_sin_cassette_en_el_path(monkeypatch, capsys):
    monkeypatch.setattr(shutil, "which", lambda nombre: None)
    assert cli.main(["atajos"]) == 1
    assert "instalá cassette en el PATH" in capsys.readouterr().err


def test_cli_atajos_imprime_los_mensajes(monkeypatch, capsys):
    monkeypatch.setattr(shutil, "which", lambda nombre: EJE)
    monkeypatch.setattr(atajos, "instalar", lambda eje, gs: [f"ok {eje}", "otro"])
    assert cli.main(["atajos"]) == 0
    assert capsys.readouterr().out.splitlines() == [f"ok {EJE}", "otro"]

import ast

import pytest

from cassette_fm import applet, cli
from cassette_fm.applet import UUID, instalar

CLAVE = ("org.cinnamon", "enabled-applets")
DE_ESTE_ESCRITORIO = [
    "panel1:left:1:xapp-status@cinnamon.org:4",
    "panel1:right:9:notifications@cinnamon.org:5",
    "panel1:right:16:user@cinnamon.org:15",
    "panel1:right:8:brightness-and-gamma-applet@cardsurf:16",
    "panel1:center:0:calendar@cinnamon.org:13",
    "panel1:right:2:multicore-sys-monitor@ccadeptic23:22",
]


class GsettingsFalso:
    def __init__(self, lista):
        self.valor = lista if isinstance(lista, str) else str(lista)
        self.llamadas = []

    def __call__(self, args):
        self.llamadas.append(args)
        accion, esquema, clave, *resto = args
        assert (esquema, clave) == CLAVE
        if accion == "get":
            return self.valor
        self.valor = resto[0]
        return ""

    def lista(self):
        return ast.literal_eval(self.valor.removeprefix("@as "))


@pytest.fixture
def entorno(tmp_path):
    origen = tmp_path / "repo" / "applet" / UUID
    origen.mkdir(parents=True)
    return origen, tmp_path / "applets"


def test_crea_el_enlace_y_habilita_el_applet(entorno):
    origen, applets = entorno
    gs = GsettingsFalso(DE_ESTE_ESCRITORIO)
    instalar(origen, applets, gs)
    assert (applets / UUID).is_symlink() and (applets / UUID).resolve() == origen.resolve()
    assert gs.lista() == DE_ESTE_ESCRITORIO + [f"panel1:right:17:{UUID}:23"]


def test_lista_vacia_con_formato_as(entorno):
    origen, applets = entorno
    gs = GsettingsFalso("@as []")
    instalar(origen, applets, gs)
    assert gs.lista() == [f"panel1:right:0:{UUID}:1"]


def test_es_idempotente(entorno):
    origen, applets = entorno
    gs = GsettingsFalso(DE_ESTE_ESCRITORIO)
    instalar(origen, applets, gs)
    antes = gs.lista()
    mensajes = instalar(origen, applets, gs)
    assert gs.lista() == antes and sum(UUID in e for e in antes) == 1
    assert any("ya estaba" in m for m in mensajes)
    assert (applets / UUID).resolve() == origen.resolve()


def test_no_pisa_algo_ajeno_en_la_carpeta_de_applets(entorno):
    origen, applets = entorno
    (applets / UUID).mkdir(parents=True)
    (applets / UUID / "mio.txt").write_text("importante")
    gs = GsettingsFalso(DE_ESTE_ESCRITORIO)
    mensajes = instalar(origen, applets, gs)
    assert (applets / UUID / "mio.txt").read_text() == "importante"
    assert gs.lista() == DE_ESTE_ESCRITORIO
    assert gs.llamadas == [] or all(a[0] == "get" for a in gs.llamadas)
    assert any("no se toca" in m for m in mensajes)


def test_reemplaza_un_enlace_roto_o_viejo(entorno, tmp_path):
    origen, applets = entorno
    applets.mkdir()
    (applets / UUID).symlink_to(tmp_path / "ya-no-existe")
    instalar(origen, applets, GsettingsFalso("@as []"))
    assert (applets / UUID).resolve() == origen.resolve()


def test_cli_applet_sin_la_carpeta_del_applet(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cli, "_origen_applet", lambda: tmp_path / "no-existe")
    assert cli.main(["applet"]) == 1
    assert "no se encuentra el applet" in capsys.readouterr().err


def test_cli_applet_imprime_los_mensajes(monkeypatch, tmp_path, capsys):
    origen = tmp_path / UUID
    origen.mkdir()
    monkeypatch.setattr(cli, "_origen_applet", lambda: origen)
    monkeypatch.setattr(applet, "instalar", lambda o, d, gs: ["uno", "dos"])
    assert cli.main(["applet"]) == 0
    assert capsys.readouterr().out.splitlines() == ["uno", "dos"]

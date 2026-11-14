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
        if args[0] == "reset-recursively":
            for k in [k for k in self.d if k[0] == args[1]]:
                del self.d[k]
            return ""
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


def por_nombre(gs, nombre):
    """Id de la entrada de custom-list cuyo `name` es `nombre` (o None)."""
    for id_ in gs.lista():
        if id_ != "__dummy__" and gs.campo(id_, "name") == nombre:
            return id_
    return None


ESPERADO = {
    "cassette-fm: siguiente estación": ("next", ["<Super><Alt>Right"]),
    "cassette-fm: estación anterior": ("prev", ["<Super><Alt>Left"]),
    "cassette-fm: subir volumen": ("vol +10", ["<Super><Alt>Up"]),
    "cassette-fm: bajar volumen": ("vol -10", ["<Super><Alt>Down"]),
}


def test_instala_los_cuatro_atajos_con_su_comando():
    gs = GsettingsFalso()
    instalar(EJE, gs)
    for nombre, (accion, teclas) in ESPERADO.items():
        id_ = por_nombre(gs, nombre)
        assert id_ is not None, nombre
        assert gs.campo(id_, "command") == f"{EJE} {accion}"
        assert gs.campo(id_, "binding") == teclas
    assert {a.nombre for a in ATAJOS} == set(ESPERADO)


def test_los_ids_son_customN_como_espera_la_configuracion_de_cinnamon():
    gs = GsettingsFalso()
    instalar(EJE, gs)
    for id_ in gs.lista():
        if id_ != "__dummy__":
            int(id_.replace("custom", ""))   # lo que hace cinnamon-settings con cada entrada
    assert gs.lista()[2:6] == ["custom2", "custom3", "custom4", "custom5"]


def test_conserva_la_lista_y_el_orden():
    gs = GsettingsFalso()
    instalar(EJE, gs)
    assert gs.lista() == ["custom0", "custom1", "custom2", "custom3", "custom4", "custom5", "__dummy__"]


def test_lista_vacia_con_formato_as():
    gs = GsettingsFalso(lista="@as []")
    instalar(EJE, gs)
    assert gs.lista() == ["custom0", "custom1", "custom2", "custom3"]


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
    id_ = por_nombre(gs, "cassette-fm: siguiente estación")
    gs.d[(f"{ENTRADA}{id_}/", "binding")] = "['<Super>n']"
    instalar("/opt/otro/cassette", gs)
    assert gs.campo(id_, "binding") == ["<Super>n"]
    assert gs.campo(id_, "command") == "/opt/otro/cassette next"


def test_omite_tecla_ocupada_por_otro_atajo():
    gs = GsettingsFalso()
    gs._entrada("custom1", "Mi atajo", "xterm", "['<Super><Alt>Right']")
    mensajes = instalar(EJE, gs)
    assert por_nombre(gs, "cassette-fm: siguiente estación") is None
    assert any("Mi atajo" in m and "omitido" in m for m in mensajes)
    for nombre in ESPERADO:
        if "siguiente" not in nombre:
            assert por_nombre(gs, nombre) is not None


def test_los_valores_de_texto_se_escriben_como_gvariant():
    gs = GsettingsFalso()
    instalar(EJE, gs)
    sets = {tuple(a[1:4]) for a in gs.llamadas if a[0] == "set"}
    assert (f"{ENTRADA}custom2/", "command", repr(f"{EJE} next")) in sets


def _instalar_a_la_antigua(gs):
    """Imita lo que dejó la primera versión: ids `cassette-fm-*` en vez de `customN`."""
    viejos = {
        "cassette-fm-siguiente": ("cassette-fm: siguiente estación", "next", "['<Super><Alt>Right']"),
        "cassette-fm-anterior": ("cassette-fm: estación anterior", "prev", "['<Super>n']"),
        "cassette-fm-volumen-mas": ("cassette-fm: subir volumen", "vol +10", "['<Super><Alt>Up']"),
        "cassette-fm-volumen-menos": ("cassette-fm: bajar volumen", "vol -10", "['<Super><Alt>Down']"),
    }
    for id_, (nombre, accion, binding) in viejos.items():
        gs._entrada(id_, nombre, f"/viejo/cassette {accion}", binding)
    gs.d[(LISTA, "custom-list")] = str(["custom0", "custom1", *viejos, "__dummy__"])
    return viejos


def test_migra_los_ids_viejos_a_customN_conservando_las_teclas():
    gs = GsettingsFalso()
    viejos = _instalar_a_la_antigua(gs)
    mensajes = instalar(EJE, gs)
    lista = gs.lista()
    assert not [i for i in lista if i in viejos]
    for id_ in lista:
        if id_ != "__dummy__":
            int(id_.replace("custom", ""))
    assert lista[-1] == "__dummy__" and len(lista) == 7
    anterior = por_nombre(gs, "cassette-fm: estación anterior")
    assert gs.campo(anterior, "binding") == ["<Super>n"]          # la tecla que el usuario cambió
    assert gs.campo(anterior, "command") == f"{EJE} prev"          # y el comando, actualizado
    assert gs.campo(por_nombre(gs, "cassette-fm: subir volumen"), "binding") == ["<Super><Alt>Up"]
    assert any("migrado" in m for m in mensajes)
    # lo viejo se borra de dconf y no queda nada colgado
    assert not [k for k in gs.d if any(k[0].endswith(f"/{v}/") for v in viejos)]


def test_migrar_es_idempotente():
    gs = GsettingsFalso()
    _instalar_a_la_antigua(gs)
    instalar(EJE, gs)
    antes = gs.lista()
    mensajes = instalar(EJE, gs)
    assert gs.lista() == antes and all("actualizado" in m for m in mensajes)


def test_cli_atajos_sin_cassette_en_el_path(monkeypatch, capsys):
    monkeypatch.setattr(shutil, "which", lambda nombre: None)
    assert cli.main(["atajos"]) == 1
    assert "instalá cassette en el PATH" in capsys.readouterr().err


def test_cli_atajos_imprime_los_mensajes(monkeypatch, capsys):
    monkeypatch.setattr(shutil, "which", lambda nombre: EJE)
    monkeypatch.setattr(atajos, "instalar", lambda eje, gs: [f"ok {eje}", "otro"])
    assert cli.main(["atajos"]) == 0
    assert capsys.readouterr().out.splitlines() == [f"ok {EJE}", "otro"]

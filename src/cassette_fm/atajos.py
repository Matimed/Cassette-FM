import ast
import subprocess
from collections.abc import Callable
from dataclasses import dataclass

RAIZ = "/org/cinnamon/desktop/keybindings/custom-keybindings/"
_ESQUEMA_LISTA = "org.cinnamon.desktop.keybindings"
_ESQUEMA_ENTRADA = "org.cinnamon.desktop.keybindings.custom-keybinding:" + RAIZ
_RELLENO = "__dummy__"   # entrada que Cinnamon deja para que la lista nunca quede vacía


@dataclass(frozen=True)
class Atajo:
    id: str       # nombre de la entrada en dconf
    nombre: str
    accion: str   # argumentos de la CLI
    tecla: str


ATAJOS = (
    Atajo("cassette-fm-siguiente", "cassette-fm: siguiente estación", "next", "<Super><Alt>Right"),
    Atajo("cassette-fm-anterior", "cassette-fm: estación anterior", "prev", "<Super><Alt>Left"),
    Atajo("cassette-fm-volumen-mas", "cassette-fm: subir volumen", "vol +10", "<Super><Alt>Up"),
    Atajo("cassette-fm-volumen-menos", "cassette-fm: bajar volumen", "vol -10", "<Super><Alt>Down"),
)


def gsettings(args: list[str]) -> str:
    return subprocess.run(["gsettings", *args], capture_output=True, text=True,
                          check=True).stdout.strip()


def _leer(texto: str):
    return ast.literal_eval(texto.strip().removeprefix("@as ").removeprefix("@as"))


def _entrada(id_: str) -> str:
    return f"{_ESQUEMA_ENTRADA}{id_}/"


def _texto(valor: str) -> str:
    return repr(valor)


def instalar(ejecutable: str, gs: Callable[[list[str]], str]) -> list[str]:
    lista = list(_leer(gs(["get", _ESQUEMA_LISTA, "custom-list"])))
    propios = {a.id for a in ATAJOS}
    ocupadas: dict[str, str] = {}
    for id_ in lista:
        if id_ == _RELLENO or id_ in propios:
            continue
        nombre = _leer(gs(["get", _entrada(id_), "name"]))
        for tecla in _leer(gs(["get", _entrada(id_), "binding"])):
            ocupadas[tecla] = nombre or id_

    mensajes = []
    nuevos = []
    for a in ATAJOS:
        existe = a.id in lista
        if not existe:
            if a.tecla in ocupadas:
                mensajes.append(f"{a.nombre}: omitido, la tecla {a.tecla} ya la usa "
                                f"'{ocupadas[a.tecla]}'")
                continue
            gs(["set", _entrada(a.id), "binding", str([a.tecla])])
            nuevos.append(a.id)
            mensajes.append(f"{a.nombre}: instalado ({a.tecla})")
        else:
            actual = _leer(gs(["get", _entrada(a.id), "binding"]))
            mensajes.append(f"{a.nombre}: actualizado (tecla {', '.join(actual) or 'ninguna'})")
        gs(["set", _entrada(a.id), "name", _texto(a.nombre)])
        gs(["set", _entrada(a.id), "command", _texto(f"{ejecutable} {a.accion}")])

    if nuevos:
        punto = lista.index(_RELLENO) if _RELLENO in lista else len(lista)
        lista[punto:punto] = nuevos
        gs(["set", _ESQUEMA_LISTA, "custom-list", str(lista)])
    return mensajes

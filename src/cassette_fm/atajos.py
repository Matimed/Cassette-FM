import ast
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass

RAIZ = "/org/cinnamon/desktop/keybindings/custom-keybindings/"
_ESQUEMA_LISTA = "org.cinnamon.desktop.keybindings"
_ESQUEMA_ENTRADA = "org.cinnamon.desktop.keybindings.custom-keybinding:" + RAIZ
_RELLENO = "__dummy__"   # entrada que Cinnamon deja para que la lista nunca quede vacía


@dataclass(frozen=True)
class Atajo:
    nombre: str   # también identifica nuestras entradas: los ids de dconf tienen que ser `customN`
    accion: str   # argumentos de la CLI
    tecla: str


ATAJOS = (
    Atajo("cassette-fm: siguiente estación", "next", "<Super><Alt>Right"),
    Atajo("cassette-fm: estación anterior", "prev", "<Super><Alt>Left"),
    Atajo("cassette-fm: subir volumen", "vol +10", "<Super><Alt>Up"),
    Atajo("cassette-fm: bajar volumen", "vol -10", "<Super><Alt>Down"),
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
    entradas = {}   # id -> (nombre, teclas)
    for id_ in lista:
        if id_ != _RELLENO:
            entradas[id_] = (_leer(gs(["get", _entrada(id_), "name"])),
                             _leer(gs(["get", _entrada(id_), "binding"])))
    por_nombre = {nombre: id_ for id_, (nombre, _) in entradas.items()}
    propios = {a.nombre for a in ATAJOS}
    ocupadas = {tecla: nombre or id_ for id_, (nombre, teclas) in entradas.items()
                if nombre not in propios for tecla in teclas}
    # cinnamon-settings hace int(id.replace("custom", "")) con cada entrada: los ids tienen que ser customN
    numeros = [int(m.group(1)) for id_ in lista if (m := re.fullmatch(r"custom(\d+)", id_))]
    siguiente = max(numeros, default=-1) + 1

    # la primera versión guardaba los atajos con ids `cassette-fm-*`: se migran a customN
    heredados = {i for i, (nombre, _) in entradas.items()
                 if nombre in propios and not re.fullmatch(r"custom\d+", i)}
    migrados = []
    mensajes = []
    nuevos = []
    for a in ATAJOS:
        id_ = por_nombre.get(a.nombre)
        if id_ in heredados:
            viejo, id_ = id_, f"custom{siguiente}"
            siguiente += 1
            teclas = entradas[viejo][1]
            gs(["set", _entrada(id_), "binding", str(teclas)])   # conserva la tecla elegida
            migrados.append(viejo)
            nuevos.append(id_)
            mensajes.append(f"{a.nombre}: migrado a {id_} (tecla {', '.join(teclas) or 'ninguna'})")
        elif id_ is None:
            if a.tecla in ocupadas:
                mensajes.append(f"{a.nombre}: omitido, la tecla {a.tecla} ya la usa "
                                f"'{ocupadas[a.tecla]}'")
                continue
            id_ = f"custom{siguiente}"
            siguiente += 1
            gs(["set", _entrada(id_), "binding", str([a.tecla])])
            nuevos.append(id_)
            mensajes.append(f"{a.nombre}: instalado ({a.tecla})")
        else:
            actual = entradas[id_][1]
            mensajes.append(f"{a.nombre}: actualizado (tecla {', '.join(actual) or 'ninguna'})")
        gs(["set", _entrada(id_), "name", _texto(a.nombre)])
        gs(["set", _entrada(id_), "command", _texto(f"{ejecutable} {a.accion}")])

    if nuevos:
        lista = [i for i in lista if i not in migrados]
        punto = lista.index(_RELLENO) if _RELLENO in lista else len(lista)
        lista[punto:punto] = nuevos
        gs(["set", _ESQUEMA_LISTA, "custom-list", str(lista)])
    for viejo in migrados:
        gs(["reset-recursively", _entrada(viejo)])
    return mensajes

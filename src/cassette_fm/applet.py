import ast
from collections.abc import Callable
from pathlib import Path

UUID = "cassette-fm@cassette-fm"
_ESQUEMA = "org.cinnamon"
_CLAVE = "enabled-applets"
_PANEL, _ZONA = "panel1", "right"


def _leer_lista(texto: str) -> list[str]:
    return list(ast.literal_eval(texto.strip().removeprefix("@as").strip()))


def _enlazar(origen: Path, applets_dir: Path) -> tuple[bool, str]:
    """Devuelve (se_puede_seguir, mensaje)."""
    destino = applets_dir / UUID
    if destino.is_symlink():
        if destino.resolve() == origen.resolve():
            return True, f"enlace del applet: ya estaba ({destino})"
        destino.unlink()
        destino.symlink_to(origen)
        return True, f"enlace del applet: actualizado ({destino})"
    if destino.exists():
        return False, (f"{destino} ya existe y no es un enlace: no se toca. "
                       "Borralo o movelo y volvé a correr el comando.")
    applets_dir.mkdir(parents=True, exist_ok=True)
    destino.symlink_to(origen)
    return True, f"enlace del applet: creado ({destino})"


def _habilitar(gs: Callable[[list[str]], str]) -> str:
    lista = _leer_lista(gs(["get", _ESQUEMA, _CLAVE]))
    entradas = [e.split(":") for e in lista]
    if any(len(e) >= 4 and e[3] == UUID for e in entradas):
        return "panel: el applet ya estaba habilitado"
    posiciones = [int(e[2]) for e in entradas
                  if len(e) >= 5 and e[0] == _PANEL and e[1] == _ZONA and e[2].isdigit()]
    ids = [int(e[4]) for e in entradas if len(e) >= 5 and e[4].isdigit()]
    posicion = max(posiciones) + 1 if posiciones else 0
    instancia = max(ids) + 1 if ids else 1
    lista.append(f"{_PANEL}:{_ZONA}:{posicion}:{UUID}:{instancia}")
    gs(["set", _ESQUEMA, _CLAVE, str(lista)])
    return f"panel: applet agregado a la derecha del panel (posición {posicion})"


def instalar(origen: Path, applets_dir: Path, gs: Callable[[list[str]], str]) -> list[str]:
    seguir, mensaje = _enlazar(Path(origen), Path(applets_dir))
    mensajes = [mensaje]
    if seguir:
        mensajes.append(_habilitar(gs))
    return mensajes

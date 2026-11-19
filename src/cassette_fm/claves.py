"""Las claves de acceso al relay (`claves.json`): se crean y se borran desde la PC y solo se guarda su huella.

El servicio le pasa la lista (`para_relay`) al relay por el puente a la nube. Docs:
docs/superpowers/specs/2026-11-19-claves-relay-design.md."""
import hashlib
import json
import os
import re
import secrets
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

PERMISOS = ("escucha", "completa")
_ALFABETO = "0123456789abcdefghjkmnpqrstvwxyz"      # base32 de Crockford en minúscula: sin i, l, o, u
_MAX_NOMBRE = 40
_ID = re.compile(r"[0-9a-f]{8}")
_HUELLA = re.compile(r"[0-9a-f]{64}")


class ErrorClaves(Exception):
    """Un problema con las claves. El mensaje nunca incluye una clave."""


def normalizar(clave: str) -> str:
    return "".join(clave.lower().split()).replace("-", "")


def huella(clave: str) -> str:
    return hashlib.sha256(normalizar(clave).encode()).hexdigest()


def generar_clave() -> str:
    letras = "".join(secrets.choice(_ALFABETO) for _ in range(16))
    return "-".join(letras[i:i + 4] for i in range(0, 16, 4))


def _clave_de_nombre(nombre: str) -> str:
    return nombre.strip().casefold()


def _es_registro(r) -> bool:
    return (isinstance(r, dict) and isinstance(r.get("id"), str) and _ID.fullmatch(r["id"]) is not None
            and isinstance(r.get("nombre"), str) and r["nombre"].strip() != ""
            and r.get("permiso") in PERMISOS
            and isinstance(r.get("huella"), str) and _HUELLA.fullmatch(r["huella"]) is not None
            and isinstance(r.get("creada"), str))


def leer(ruta: Path) -> list[dict]:
    try:
        crudo = Path(ruta).read_text()
    except FileNotFoundError:
        return []
    except OSError as e:
        raise ErrorClaves(f"{ruta}: no se pudo leer ({e.strerror})") from None
    try:
        datos = json.loads(crudo)
    except ValueError as e:
        raise ErrorClaves(f"{ruta}: JSON roto ({e})") from None
    lista = datos.get("claves") if isinstance(datos, dict) else None
    if not isinstance(lista, list) or not all(_es_registro(r) for r in lista):
        raise ErrorClaves(f"{ruta}: no tiene la forma de un archivo de claves")
    return lista


def _escribir(ruta: Path, lista: list[dict]) -> None:
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    tmp = ruta.with_name(ruta.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump({"claves": lista}, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, ruta)


def crear(ruta: Path, nombre: str, permiso: str,
          ahora: Callable[[], datetime] = lambda: datetime.now().astimezone()) -> tuple[str, dict]:
    """Crea una clave. Devuelve (la clave en claro, el registro): la clave no se guarda y no se vuelve a ver."""
    if permiso not in PERMISOS:
        raise ErrorClaves(f"el permiso tiene que ser uno de {', '.join(PERMISOS)}")
    nombre = nombre.strip()
    if not nombre or len(nombre) > _MAX_NOMBRE or "\n" in nombre or "\r" in nombre:
        raise ErrorClaves(f"el nombre tiene que tener entre 1 y {_MAX_NOMBRE} caracteres, en una sola línea")
    lista = leer(ruta)
    if any(_clave_de_nombre(r["nombre"]) == _clave_de_nombre(nombre) for r in lista):
        raise ErrorClaves(f"ya hay una clave con el nombre «{nombre}»")
    usados = {r["id"] for r in lista}
    ident = secrets.token_hex(4)
    while ident in usados:
        ident = secrets.token_hex(4)
    clave = generar_clave()
    registro = {"id": ident, "nombre": nombre, "permiso": permiso, "huella": huella(clave),
                "creada": ahora().isoformat(timespec="seconds")}
    _escribir(ruta, lista + [registro])
    return clave, registro


def borrar(ruta: Path, nombre: str) -> dict:
    lista = leer(ruta)
    for i, r in enumerate(lista):
        if _clave_de_nombre(r["nombre"]) == _clave_de_nombre(nombre):
            _escribir(ruta, lista[:i] + lista[i + 1:])
            return r
    raise ErrorClaves(f"no hay ninguna clave con el nombre «{nombre.strip()}»")


def para_relay(claves: list[dict]) -> list[dict]:
    """Lo único que el relay necesita saber de cada clave: sin nombres ni fechas."""
    return [{"id": r["id"], "permiso": r["permiso"], "huella": r["huella"]} for r in claves]

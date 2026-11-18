"""Acceso a la radio por la red: la clave de oyente y en qué dirección se escucha."""
import ipaddress
import json
import os
import secrets
import shutil
import socket
import subprocess
import threading
from collections.abc import Callable
from pathlib import Path

_TAILSCALE = ipaddress.ip_network("100.64.0.0/10")


def _escribir(ruta: Path, token: str) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    tmp = ruta.with_name(ruta.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(token + "\n")
    os.replace(tmp, ruta)


def leer_o_crear_token(ruta: Path) -> str:
    try:
        token = Path(ruta).read_text().strip()
        if token:
            return token
    except OSError:
        pass
    return regenerar_token(ruta)


def regenerar_token(ruta: Path) -> str:
    token = secrets.token_urlsafe(32)
    _escribir(Path(ruta), token)
    return token


class TokenVivo:
    """La clave de oyente siempre al día: se vuelve a leer del archivo cuando cambia (`cassette lan regenerar`), así
    la vieja deja de valer sin reiniciar el servicio. `al_cambiar` corre cuando cambia (no en la primera lectura)."""

    def __init__(self, ruta: Path, al_cambiar: Callable[[], None] | None = None):
        self._ruta = Path(ruta)
        self._al_cambiar = al_cambiar
        self._lock = threading.Lock()
        self._token: str | None = None

    def __call__(self) -> str:
        with self._lock:
            try:
                nuevo = self._ruta.read_text().strip()     # 44 bytes: se lee siempre (el mtime puede no distinguir dos cambios)
            except OSError:
                return self._token or ""                   # si no se puede leer, rige la última clave conocida
            if nuevo and nuevo != self._token:
                previo, self._token = self._token, nuevo
                if previo is not None and self._al_cambiar is not None:
                    self._al_cambiar()
            return self._token or ""


def ip_tailscale(ejecutar: Callable = subprocess.run) -> str | None:
    """La IP de Tailscale de esta PC (interfaz tailscale0, rango 100.64.0.0/10), o None."""
    try:
        salida = ejecutar(["ip", "-4", "-j", "addr", "show", "tailscale0"], capture_output=True, text=True,
                          timeout=3)
        if salida.returncode != 0:
            return None
        for interfaz in json.loads(salida.stdout):
            for info in interfaz.get("addr_info", []):
                if info.get("family") == "inet" and ipaddress.ip_address(info["local"]) in _TAILSCALE:
                    return info["local"]
    except (OSError, ValueError, KeyError, subprocess.SubprocessError):
        pass
    return None


def ip_ruta_por_defecto() -> str | None:
    """La IP de la interfaz por la que esta PC sale a la red (no manda nada: solo elige la ruta)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 9))
            return s.getsockname()[0]
    except OSError:
        return None


def tailscale_instalado() -> bool:
    return shutil.which("tailscale") is not None


def direccion_de_escucha(escuchar: str, ip_ts: Callable[[], str | None] = ip_tailscale,
                         instalado: Callable[[], bool] = tailscale_instalado) -> str | None:
    """Dónde escucha el servidor. "auto" = la IP de Tailscale; sin Tailscale instalado, todas las interfaces. Con
    Tailscale instalado pero sin IP todavía (arranque temprano) devuelve None: hay que esperar, no abrirse a la LAN."""
    if escuchar != "auto":
        return escuchar
    return ip_ts() or (None if instalado() else "0.0.0.0")


def direccion_para_mostrar(escuchar: str, ip_ts: Callable[[], str | None] | None = None,
                           ip_ruta: Callable[[], str | None] | None = None) -> str:
    """La dirección que se le da a la otra PC: la de Tailscale si existe (es fija), si no la de la ruta por defecto."""
    if escuchar not in ("auto", "0.0.0.0"):
        return escuchar
    return (ip_ts or ip_tailscale)() or (ip_ruta or ip_ruta_por_defecto)() or "127.0.0.1"

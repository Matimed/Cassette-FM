#!/usr/bin/env python3
"""Receptor de la radio por la red (PC secundaria): reproduce el stream de cassette-fm con mpv.

Sin demonio y sin depender de cassette_fm: el proceso que suena es un `mpv` con socket IPC; cada subcomando es un
programa corto que lo prende, lo apaga, le mueve el volumen o cuenta cómo está.

    lan_receiver.py on | off | volume N|+N|-N | status [--json] | icons

Entorno: CASSETTE_LAN_URL (por ejemplo http://100.104.222.41:8765) y CASSETTE_LAN_TOKEN (la clave de oyente; llega a
mpv por IPC, nunca por su línea de comandos). Para pruebas: CASSETTE_LAN_RUNTIME (dónde guardar socket y estado) y
CASSETTE_LAN_MPV_ARGS (argumentos extra para mpv) y CASSETTE_LAN_CACHE (dónde guardar los logos)."""
import argparse
import fcntl
import hashlib
import json
import os
import re
import shlex
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping
from pathlib import Path

VOLUMEN_INICIAL = 70
ESPERA_SOCKET_SEGUNDOS = 5.0


def _runtime(env: Mapping[str, str]) -> Path:
    if env.get("CASSETTE_LAN_RUNTIME"):
        return Path(env["CASSETTE_LAN_RUNTIME"])
    base = env.get("XDG_RUNTIME_DIR")
    return Path(base) / "cassette-fm-lan" if base else Path(f"/tmp/cassette-fm-lan-{os.getuid()}")


def ipc(ruta: Path, comando: list, timeout: float = 2.0) -> dict:
    """Un comando al IPC JSON de mpv; devuelve su respuesta. Levanta OSError si mpv no atiende."""
    with socket.socket(socket.AF_UNIX) as s:
        s.settimeout(timeout)
        s.connect(str(ruta))
        s.sendall(json.dumps({"command": comando, "request_id": 1}).encode() + b"\n")
        buffer = b""
        while True:
            while b"\n" in buffer:
                linea, buffer = buffer.split(b"\n", 1)
                try:
                    mensaje = json.loads(linea)
                except ValueError:
                    continue
                if mensaje.get("request_id") == 1:
                    return mensaje
            trozo = s.recv(65536)
            if not trozo:
                raise OSError("mpv cerró el socket")
            buffer += trozo


def _vivo(socket_ipc: Path) -> bool:
    try:
        return ipc(socket_ipc, ["get_property", "idle-active"]).get("error") == "success"
    except (OSError, ValueError):
        return False


def _ocioso(socket_ipc: Path) -> bool:
    try:
        return ipc(socket_ipc, ["get_property", "idle-active"]).get("data") is True
    except (OSError, ValueError):
        return False


def _credenciales(env: Mapping[str, str]) -> tuple[str, str] | None:
    url, token = env.get("CASSETTE_LAN_URL", "").strip().rstrip("/"), env.get("CASSETTE_LAN_TOKEN", "").strip()
    return (url, token) if url and token else None


def _cargar(socket_ipc: Path, url: str, token: str) -> None:
    """Le pasa la clave y el stream a mpv por IPC (así la clave no queda en su línea de comandos)."""
    ipc(socket_ipc, ["set_property", "http-header-fields", [f"Authorization: Bearer {token}"]])
    ipc(socket_ipc, ["loadfile", f"{url}/stream", "replace"])


def _probar(url: str, token: str) -> str:
    """'ok', 'clave rechazada' o 'sin conexión' según responda `/status` del servidor."""
    pedido = urllib.request.Request(f"{url}/status", headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(pedido, timeout=2):
            return "ok"
    except urllib.error.HTTPError as e:
        return "clave rechazada" if e.code in (401, 403) else "sin conexión"
    except (OSError, ValueError):
        return "sin conexión"


def _volumen_guardado(runtime: Path) -> int:
    try:
        return max(0, min(100, int((runtime / "volumen").read_text().strip())))
    except (OSError, ValueError):
        return VOLUMEN_INICIAL


class _Candado:
    """Un solo prender/apagar a la vez (dos `on` seguidos o simultáneos no dejan dos mpv)."""

    def __init__(self, runtime: Path):
        runtime.mkdir(parents=True, exist_ok=True)
        self._archivo = open(runtime / "candado", "w")

    def __enter__(self):
        fcntl.flock(self._archivo, fcntl.LOCK_EX)

    def __exit__(self, *_):
        fcntl.flock(self._archivo, fcntl.LOCK_UN)
        self._archivo.close()


def _error(mensaje: str) -> int:
    print(mensaje, file=sys.stderr)
    return 1


def _on(env: Mapping[str, str]) -> int:
    credenciales = _credenciales(env)
    if credenciales is None:
        return _error("faltan CASSETTE_LAN_URL y CASSETTE_LAN_TOKEN (la dirección y la clave de la radio)")
    url, token = credenciales
    runtime = _runtime(env)
    socket_ipc = runtime / "mpv.sock"
    with _Candado(runtime):
        if _vivo(socket_ipc):
            if _ocioso(socket_ipc):
                _cargar(socket_ipc, url, token)
            return 0
        socket_ipc.unlink(missing_ok=True)
        extra = shlex.split(env.get("CASSETTE_LAN_MPV_ARGS", ""))
        try:
            proceso = subprocess.Popen(
                ["mpv", "--no-config", "--idle=yes", "--no-video", "--no-terminal", f"--input-ipc-server={socket_ipc}",
                 f"--volume={_volumen_guardado(runtime)}", "--cache=no", "--audio-buffer=0.1",
                 "--stream-lavf-o=reconnect=1,reconnect_streamed=1,reconnect_delay_max=5", *extra],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                start_new_session=True, env=dict(env))
        except OSError as e:
            return _error(f"no pude lanzar mpv (¿está instalado?): {e}")
        (runtime / "pid").write_text(str(proceso.pid))
        fin = time.monotonic() + ESPERA_SOCKET_SEGUNDOS
        while not _vivo(socket_ipc):
            if proceso.poll() is not None or time.monotonic() > fin:
                return _error("mpv no arrancó")
            time.sleep(0.03)
        _cargar(socket_ipc, url, token)
    return 0


def _es_nuestro_mpv(pid: int, socket_ipc: Path) -> bool:
    try:
        return str(socket_ipc) in Path(f"/proc/{pid}/cmdline").read_bytes().decode(errors="replace")
    except OSError:
        return False


def _off(env: Mapping[str, str]) -> int:
    runtime = _runtime(env)
    socket_ipc = runtime / "mpv.sock"
    with _Candado(runtime):
        try:
            ipc(socket_ipc, ["quit"])
        except (OSError, ValueError):
            pass
        fin = time.monotonic() + 2.0
        while _vivo(socket_ipc) and time.monotonic() < fin:
            time.sleep(0.05)
        try:
            pid = int((runtime / "pid").read_text())
        except (OSError, ValueError):
            pid = None
        if pid is not None and _es_nuestro_mpv(pid, socket_ipc):       # colgado: se lo corta
            for senal in (signal.SIGTERM, signal.SIGKILL):
                try:
                    os.kill(pid, senal)
                except OSError:
                    break
                time.sleep(0.3)
                if not _es_nuestro_mpv(pid, socket_ipc):
                    break
        socket_ipc.unlink(missing_ok=True)
        (runtime / "pid").unlink(missing_ok=True)
    return 0


def _volume(env: Mapping[str, str], pedido: str) -> int:
    if not re.fullmatch(r"[+-]?\d+", pedido):
        print(f"volumen inválido: {pedido!r} (N, +N o -N)", file=sys.stderr)
        return 2
    runtime = _runtime(env)
    actual = _volumen_guardado(runtime)
    nuevo = max(0, min(100, actual + int(pedido) if pedido[0] in "+-" else int(pedido)))
    runtime.mkdir(parents=True, exist_ok=True)
    (runtime / "volumen").write_text(str(nuevo))
    try:
        ipc(runtime / "mpv.sock", ["set_property", "volume", nuevo])
    except (OSError, ValueError):
        pass                                  # sin mpv solo se recuerda para el próximo `on`
    print(nuevo)
    return 0


def _status(env: Mapping[str, str], como_json: bool) -> int:
    runtime = _runtime(env)
    socket_ipc = runtime / "mpv.sock"
    escuchando, error = False, None
    if _vivo(socket_ipc):
        if not _ocioso(socket_ipc):
            escuchando = True
        else:                                 # mpv vivo pero sin reproducir: se corta el stream o falló al cargar
            credenciales = _credenciales(env)
            if credenciales is None:
                error = "sin conexión"
            else:
                resultado = _probar(*credenciales)
                if resultado == "ok":         # el servidor volvió: se vuelve a cargar el stream
                    try:
                        _cargar(socket_ipc, *credenciales)
                        escuchando = True
                    except (OSError, ValueError):
                        error = "sin conexión"
                else:
                    error = resultado
    datos = {"escuchando": escuchando, "volumen": _volumen_guardado(runtime), "error": error}
    if como_json:
        print(json.dumps(datos, ensure_ascii=False))
    else:
        print(("Escuchando" if escuchando else "Apagado") + f" · volumen {datos['volumen']}"
              + (f" · {error}" if error else ""))
    return 0


_EXTENSIONES = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp", "image/gif": ".gif"}


def _cache(env: Mapping[str, str]) -> Path:
    if env.get("CASSETTE_LAN_CACHE"):
        return Path(env["CASSETTE_LAN_CACHE"])
    base = env.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "cassette-fm" / "lan-iconos"


def _pedir(url: str, token: str, ruta: str, timeout: float = 5.0):
    pedido = urllib.request.Request(url + ruta, headers={"Authorization": f"Bearer {token}"})
    return urllib.request.urlopen(pedido, timeout=timeout)


def _icons(env: Mapping[str, str]) -> int:
    """Baja a una caché local los logos que publica la radio y devuelve {emisora: ruta local} (JSON)."""
    credenciales = _credenciales(env)
    if credenciales is None:
        return _error("faltan CASSETTE_LAN_URL y CASSETTE_LAN_TOKEN (la dirección y la clave de la radio)")
    url, token = credenciales
    try:
        with _pedir(url, token, "/status") as r:
            publicados = json.load(r).get("iconos") or {}
    except (OSError, ValueError, AttributeError) as e:
        return _error(f"no pude consultar la radio: {type(e).__name__}")
    cache = _cache(env)
    cache.mkdir(parents=True, exist_ok=True)
    mapa, vigentes = {}, set()
    for nombre, relativa in publicados.items():
        if not isinstance(nombre, str) or not isinstance(relativa, str) or not relativa.startswith("/icon/"):
            continue
        base = hashlib.sha1(nombre.encode()).hexdigest()[:16]          # el nombre real nunca llega al disco
        version = urllib.parse.parse_qs(urllib.parse.urlsplit(relativa).query).get("v", [""])[0]
        version = re.sub(r"[^A-Za-z0-9]", "", version)[:32] or "0"
        vigentes.add(base)
        existente = next(iter(sorted(cache.glob(f"{base}-{version}.*"))), None)
        if existente is None:
            try:
                with _pedir(url, token, relativa) as r:
                    extension = _EXTENSIONES.get(r.headers.get_content_type())
                    datos = r.read(5 * 1024 * 1024)
            except (OSError, ValueError):
                print(f"no pude bajar el logo de una emisora", file=sys.stderr)
                continue
            if extension is None:
                continue
            existente = cache / f"{base}-{version}{extension}"
            tmp = existente.with_name(existente.name + ".tmp")
            tmp.write_bytes(datos)
            os.replace(tmp, existente)
        for viejo in cache.glob(f"{base}-*"):                           # versiones anteriores del mismo logo
            if viejo != existente:
                viejo.unlink(missing_ok=True)
        mapa[nombre] = str(existente)
    for archivo in cache.iterdir():                                      # logos que la radio ya no publica
        if archivo.name.split("-", 1)[0] not in vigentes:
            archivo.unlink(missing_ok=True)
    print(json.dumps(mapa, ensure_ascii=False))
    return 0


def main(argv: list[str] | None = None, env: Mapping[str, str] | None = None) -> int:
    env = os.environ if env is None else env
    parser = argparse.ArgumentParser(prog="lan_receiver", description="Receptor de la radio de cassette-fm por la red")
    sub = parser.add_subparsers(dest="comando", required=True)
    sub.add_parser("on", help="empieza a escuchar")
    sub.add_parser("off", help="deja de escuchar")
    vol = sub.add_parser("volume", help="volumen local: N, +N o -N")
    vol.add_argument("pedido")
    sub.add_parser("icons", help="baja los logos de las emisoras y devuelve sus rutas locales (JSON)")
    estado = sub.add_parser("status", help="cómo está")
    estado.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if args.comando == "on":
        return _on(env)
    if args.comando == "off":
        return _off(env)
    if args.comando == "volume":
        return _volume(env, args.pedido)
    if args.comando == "icons":
        return _icons(env)
    return _status(env, args.json)


if __name__ == "__main__":
    sys.exit(main())

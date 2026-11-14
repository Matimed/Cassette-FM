"""Sesión de Spotify: login con PKCE (sin client secret), token en disco y refresh automático.

Ningún token se loguea ni aparece en los mensajes de error."""
import base64
import hashlib
import http.client
import json
import os
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from cassette_fm.config import ConfigSpotify

ESCOPOS = ("user-read-playback-state user-modify-playback-state playlist-read-private "
           "playlist-read-collaborative")
_MARGEN_SEGUNDOS = 60       # se refresca si al token le queda menos que esto


class ErrorSesion(Exception):
    """Problema con la sesión de Spotify; el mensaje está listo para mostrarle al usuario."""


class Sesion:
    def __init__(self, archivo: Path, config: ConfigSpotify, reloj: Callable[[], float] = time.time):
        self._archivo = Path(archivo)
        self._config = config
        self._reloj = reloj
        self._lock = threading.Lock()

    def guardar(self, respuesta: dict) -> None:
        datos = {"access_token": respuesta["access_token"], "refresh_token": respuesta.get("refresh_token"),
                 "expira": self._reloj() + float(respuesta.get("expires_in", 3600))}
        self._archivo.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._archivo.with_name(self._archivo.name + ".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(datos, f)
        os.replace(tmp, self._archivo)

    def token(self, forzar: bool = False) -> str:
        """El access token vigente (lo refresca si está por vencer o si `forzar`)."""
        with self._lock:
            try:
                datos = json.loads(self._archivo.read_text(encoding="utf-8"))
                acceso, refresh, expira = datos["access_token"], datos.get("refresh_token"), float(datos["expira"])
            except (OSError, ValueError, KeyError, TypeError):
                raise ErrorSesion("no hay sesión de Spotify: corré cassette spotify login") from None
            if not forzar and self._reloj() < expira - _MARGEN_SEGUNDOS:
                return acceso
            if not refresh:
                raise ErrorSesion("la sesión de Spotify venció: corré cassette spotify login")
            nuevo = _pedir_token(self._config, {"grant_type": "refresh_token", "refresh_token": refresh,
                                                "client_id": self._config.client_id})
            if not nuevo.get("refresh_token"):
                nuevo["refresh_token"] = refresh      # Spotify no siempre rota el refresh token
            self.guardar(nuevo)
            return nuevo["access_token"]


def _pedir_token(config: ConfigSpotify, datos: dict) -> dict:
    req = urllib.request.Request(f"{config.cuentas_url}/api/token", data=urllib.parse.urlencode(datos).encode(),
                                 headers={"Content-Type": "application/x-www-form-urlencoded"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=config.timeout_segundos) as r:
            respuesta = json.loads(r.read())
    except urllib.error.HTTPError as e:
        if 400 <= e.code < 500:
            raise ErrorSesion("la sesión de Spotify venció o fue revocada: corré cassette spotify login") from None
        raise ErrorSesion(f"Spotify no responde (HTTP {e.code})") from None
    except (urllib.error.URLError, http.client.HTTPException, OSError, ValueError) as e:
        raise ErrorSesion(f"Spotify no responde ({getattr(e, 'reason', e)})") from None
    if not isinstance(respuesta, dict) or not isinstance(respuesta.get("access_token"), str):
        raise ErrorSesion("Spotify contestó algo raro al pedir el token")
    return respuesta


def login(sesion: Sesion, config: ConfigSpotify, abrir: Callable[[str], object] = webbrowser.open,
          timeout: float = 300) -> None:
    """Abre la autorización en el navegador, espera el callback en 127.0.0.1 y guarda el token."""
    verificador = secrets.token_urlsafe(64)
    desafio = base64.urlsafe_b64encode(hashlib.sha256(verificador.encode()).digest()).rstrip(b"=").decode()
    estado = secrets.token_urlsafe(16)
    redirect = f"http://127.0.0.1:{config.puerto_login}/callback"
    resultado: dict = {}
    listo = threading.Event()

    class Callback(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            url = urllib.parse.urlparse(self.path)
            q = urllib.parse.parse_qs(url.query)
            valido = url.path == "/callback" and q.get("state", [""])[0] == estado
            if valido and "code" in q:
                resultado["code"] = q["code"][0]
                texto = "Listo: ya podés cerrar esta pestaña y volver a la terminal."
            elif valido and "error" in q:
                resultado["error"] = q["error"][0]
                texto = "Cancelado: no se dio permiso a cassette-fm."
            else:
                texto = "Respuesta inesperada: se ignora."
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(texto.encode())
            if valido:
                listo.set()

    try:
        servidor = HTTPServer(("127.0.0.1", config.puerto_login), Callback)
    except OSError:
        raise ErrorSesion(f"el puerto {config.puerto_login} está ocupado: cerrá lo que lo use (¿otro login "
                          f"abierto?) y probá de nuevo") from None
    hilo = threading.Thread(target=lambda: servidor.serve_forever(poll_interval=0.05), daemon=True)
    hilo.start()
    try:
        abrir(f"{config.cuentas_url}/authorize?" + urllib.parse.urlencode({
            "client_id": config.client_id, "response_type": "code", "redirect_uri": redirect, "scope": ESCOPOS,
            "code_challenge_method": "S256", "code_challenge": desafio, "state": estado}))
        if not listo.wait(timeout):
            raise ErrorSesion(f"no llegó la respuesta de Spotify en {timeout:g} s: probá de nuevo")
    finally:
        servidor.shutdown()
        servidor.server_close()
    if "error" in resultado:
        raise ErrorSesion(f"cancelaste el permiso en Spotify ({resultado['error']})")
    sesion.guardar(_pedir_token(config, {"grant_type": "authorization_code", "code": resultado["code"],
                                         "redirect_uri": redirect, "client_id": config.client_id,
                                         "code_verifier": verificador}))

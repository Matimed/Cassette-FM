"""Cliente mínimo de la Web API de Spotify: token, un reintento por 401 o por un 429 corto, y paginación.

Los pedidos lentos y los 429 quedan en el log (solo método y ruta: ni parámetros ni token)."""
import http.client
import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterator

from cassette_fm.config import ConfigSpotify
from cassette_fm.spotify.sesion import ErrorSesion

_ESPERA_MAXIMA_429 = 5.0     # un Retry-After más largo no se espera (el rescan no se cuelga)
_LENTO_SEGUNDOS = 2.0        # un pedido que tarda más (reintentos incluidos) queda en el log

_log = logging.getLogger("cassette_fm")


class ErrorSpotify(Exception):
    """Spotify no dio lo pedido; `codigo` es el HTTP (None si no hubo respuesta). Sin tokens en el mensaje."""

    def __init__(self, mensaje: str, codigo: int | None = None):
        super().__init__(mensaje)
        self.codigo = codigo


class ClienteSpotify:
    def __init__(self, sesion, config: ConfigSpotify, dormir: Callable[[float], None] = time.sleep,
                 reloj: Callable[[], float] = time.monotonic):
        self._sesion = sesion
        self._config = config
        self._dormir = dormir
        self._reloj = reloj

    def get(self, ruta: str, params: dict | None = None) -> dict:
        """`ruta` relativa a la API ("/playlists/x") o una URL absoluta de la misma API (el `next` de una página)."""
        return self._llamar("GET", ruta, params, None)

    def put(self, ruta: str, params: dict | None = None, cuerpo: dict | None = None) -> None:
        self._llamar("PUT", ruta, params, cuerpo)

    def _llamar(self, metodo: str, ruta: str, params: dict | None, cuerpo: dict | None):
        url = ruta if ruta.startswith("http") else self._config.api_url + ruta
        if params:
            url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
        base = urllib.parse.urlsplit(self._config.api_url).path
        pedido = f"{metodo} {urllib.parse.urlsplit(url).path.removeprefix(base)}"   # sin parámetros ni token
        inicio = self._reloj()
        forzado = esperado = False
        try:
            while True:
                try:
                    return self._pedir(metodo, url, self._token(forzado), cuerpo)
                except _Respuesta as r:
                    if r.codigo == 401 and not forzado:
                        forzado = True
                        continue
                    if r.codigo == 429 and not esperado and r.espera is not None and r.espera <= _ESPERA_MAXIMA_429:
                        _log.warning("Spotify limita los pedidos (429): espero %g s y reintento %s", r.espera, pedido)
                        esperado = True
                        self._dormir(r.espera)
                        continue
                    raise ErrorSpotify(f"Spotify contestó {r.codigo}: {r.mensaje}", r.codigo) from None
        finally:
            demora = self._reloj() - inicio
            if demora > _LENTO_SEGUNDOS:
                _log.warning("Spotify tardó %.1f s en contestar %s", demora, pedido)

    def paginas(self, ruta: str, params: dict | None = None) -> Iterator[dict]:
        pagina = self.get(ruta, params)
        while True:
            yield pagina
            siguiente = pagina.get("next")
            if not isinstance(siguiente, str) or not siguiente.startswith(self._config.api_url):
                return
            pagina = self.get(siguiente)

    def _token(self, forzar: bool) -> str:
        try:
            return self._sesion.token(forzar=forzar)
        except ErrorSesion as e:
            raise ErrorSpotify(str(e)) from None

    def _pedir(self, metodo: str, url: str, token: str, cuerpo: dict | None) -> dict | None:
        datos = json.dumps(cuerpo).encode() if cuerpo is not None else (b"" if metodo != "GET" else None)
        req = urllib.request.Request(url, data=datos, method=metodo,
                                     headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self._config.timeout_segundos) as r:
                crudo = r.read()
        except urllib.error.HTTPError as e:
            raise _Respuesta(e.code, _mensaje(e), _espera(e.headers.get("Retry-After"))) from None
        except (urllib.error.URLError, http.client.HTTPException, OSError) as e:
            raise ErrorSpotify(f"Spotify no responde ({getattr(e, 'reason', e)})") from None
        if metodo != "GET":
            return None                    # 200/202/204 de un comando: no interesa el cuerpo
        try:
            datos = json.loads(crudo)
        except ValueError:
            raise ErrorSpotify("Spotify contestó algo que no es JSON") from None
        if not isinstance(datos, dict):
            raise ErrorSpotify("Spotify contestó algo inesperado")
        return datos


class _Respuesta(Exception):
    def __init__(self, codigo: int, mensaje: str, espera: float | None):
        self.codigo, self.mensaje, self.espera = codigo, mensaje, espera


def _mensaje(e: urllib.error.HTTPError) -> str:
    try:
        datos = json.loads(e.read())
        mensaje = datos.get("error", {}).get("message") if isinstance(datos, dict) else None
        if isinstance(mensaje, str) and mensaje:
            return mensaje
    except Exception:
        pass
    return e.reason or "sin detalle"


def _espera(valor) -> float | None:
    try:
        return max(0.0, float(valor))
    except (TypeError, ValueError):
        return None

import http.client
import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path

_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")


class ErrorDJ(Exception):
    """El servicio DJ no respondió o respondió algo inusable; el mensaje está pensado para el log."""


def _validar_id(id: str) -> str:
    if not isinstance(id, str) or not _ID.fullmatch(id):
        raise ValueError(f"id de intervención inválido: {id!r}")
    return id


class ClienteDJ:
    """Habla con el servicio DJ (cassette-dj) por HTTP; todo fallo sale como ErrorDJ."""

    def __init__(self, url: str, timeout: float = 10.0):
        self._url = url.rstrip("/")
        self._timeout = timeout

    def enviar(self, pedido: dict) -> str:
        cuerpo = json.dumps(pedido, ensure_ascii=False).encode("utf-8")
        datos = self._json(self._pedir("POST", "/intervenciones", cuerpo))
        id_ = datos.get("id") if isinstance(datos, dict) else None
        if not isinstance(id_, str) or not _ID.fullmatch(id_):
            raise ErrorDJ("el servicio DJ contestó una respuesta ilegible (sin id)")
        return id_

    def estado(self, id: str) -> dict | None:
        try:
            datos = self._json(self._pedir("GET", f"/intervenciones/{_validar_id(id)}"))
        except _NoExiste:
            return None
        if not isinstance(datos, dict):
            raise ErrorDJ("el servicio DJ contestó una respuesta ilegible")
        return datos

    def descargar_audio(self, id: str, destino: Path) -> Path:
        try:
            crudo, largo = self._pedir("GET", f"/intervenciones/{_validar_id(id)}/audio", con_largo=True)
        except _NoExiste as e:
            raise ErrorDJ(str(e)) from None
        if not crudo.startswith(b"RIFF") or (largo is not None and len(crudo) != largo):
            raise ErrorDJ("el audio que mandó el servicio DJ está incompleto o no es un WAV")
        destino = Path(destino)
        destino.parent.mkdir(parents=True, exist_ok=True)
        parcial = destino.with_name(destino.name + ".part")
        try:
            parcial.write_bytes(crudo)
            os.replace(parcial, destino)
        except OSError as e:
            parcial.unlink(missing_ok=True)
            raise ErrorDJ(f"no se pudo guardar el audio en {destino}: {e}") from None
        return destino

    def cancelar(self, id: str) -> bool:
        try:
            datos = self._json(self._pedir("DELETE", f"/intervenciones/{_validar_id(id)}"))
        except _NoExiste:
            return False
        return bool(isinstance(datos, dict) and datos.get("cancelado"))

    def modo(self) -> str:
        datos = self._json(self._pedir("GET", "/modo"))
        modo = datos.get("modo") if isinstance(datos, dict) else None
        if not isinstance(modo, str):
            raise ErrorDJ("el servicio DJ contestó una respuesta ilegible (sin modo)")
        return modo

    def poner_modo(self, modo: str) -> dict:
        cuerpo = json.dumps({"modo": modo}).encode("utf-8")
        datos = self._json(self._pedir("POST", "/modo", cuerpo))
        if not isinstance(datos, dict) or not isinstance(datos.get("modo"), str):
            raise ErrorDJ("el servicio DJ contestó una respuesta ilegible (sin modo)")
        return datos

    def muestra(self, voz: str, idioma: str, radio: str = "") -> bytes:
        """El WAV de la frase de muestra de `voz` ("Hola, soy dora y estás escuchando…"); la primera puede tardar
        lo que el servicio en cargar el modelo."""
        cuerpo = json.dumps({"voz": voz, "idioma": idioma, "radio": radio}).encode("utf-8")
        try:
            return self._pedir("POST", "/muestra", cuerpo, timeout=max(self._timeout, 60.0))
        except _NoExiste as e:
            raise ErrorDJ(f"el servicio DJ no sabe hacer muestras (¿hay que reiniciarlo?): {e}") from None

    def salud(self) -> dict:
        datos = self._json(self._pedir("GET", "/salud"))
        if not isinstance(datos, dict):
            raise ErrorDJ("el servicio DJ contestó una respuesta ilegible")
        return datos

    def _json(self, crudo: bytes):
        try:
            return json.loads(crudo.decode("utf-8"))
        except (ValueError, UnicodeDecodeError, RecursionError):
            raise ErrorDJ("el servicio DJ contestó una respuesta ilegible (no es JSON)") from None

    def _pedir(self, metodo: str, ruta: str, cuerpo: bytes | None = None, con_largo: bool = False,
               timeout: float | None = None):
        req = urllib.request.Request(self._url + ruta, data=cuerpo, method=metodo,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout or self._timeout) as r:
                crudo = r.read()
                largo = r.headers.get("Content-Length")
        except urllib.error.HTTPError as e:
            mensaje = self._mensaje_de_error(e)
            if e.code == 404:
                raise _NoExiste(mensaje) from None
            raise ErrorDJ(f"el servicio DJ contestó {e.code}: {mensaje}") from None
        except (urllib.error.URLError, http.client.HTTPException, OSError) as e:
            razon = getattr(e, "reason", e)
            raise ErrorDJ(f"el servicio DJ no responde en {self._url} ({razon})") from None
        if con_largo:
            return crudo, int(largo) if largo and largo.isdigit() else None
        return crudo

    @staticmethod
    def _mensaje_de_error(e: urllib.error.HTTPError) -> str:
        try:
            datos = json.loads(e.read().decode("utf-8"))
            if isinstance(datos, dict) and isinstance(datos.get("error"), str):
                return datos["error"]
        except Exception:
            pass
        return e.reason or "sin detalle"


class _NoExiste(Exception):
    """404 del servicio (uso interno)."""

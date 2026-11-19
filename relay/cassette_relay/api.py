"""La API privada de los oyentes (`/api/…`): acceso, estado, órdenes, logos y el audio en vivo."""
import asyncio
import json
import logging
import socket

from aiohttp import web

from .acceso import DURACION_SESION, Acceso, Identidad
from .casa import Casa, nombre_en_ruta
from .config import CALIDADES, Ajustes
from .oyentes import Oyentes

_log = logging.getLogger("cassette_relay.api")

COOKIE = "sesion"
IDENTIDAD = web.RequestKey("identidad", Identidad)    # la identidad con que se entró, en cada pedido a /api/
_MAX_CUERPO = 4 * 1024          # los pedidos JSON de los oyentes son chicos
_SNDBUF_OYENTE = 16 * 1024     # chico: que el atraso de un oyente lento se vea en su cola y no en el kernel


def _error(status: int, texto: str) -> web.Response:
    return web.json_response({"error": texto}, status=status)


async def _leer_acotado(request: web.Request, maximo: int) -> bytes | None:
    """El cuerpo, o None si pasa de `maximo` (sin leer más de eso: `entrar` no pide clave antes de leer)."""
    if (request.content_length or 0) > maximo:
        return None
    datos = bytearray()
    while True:
        trozo = await request.content.read(maximo + 1 - len(datos))
        if not trozo:
            return bytes(datos)
        datos += trozo
        if len(datos) > maximo:
            return None


def _bearer(request: web.Request) -> str | None:
    encabezado = request.headers.get("Authorization", "")
    return encabezado[len("Bearer "):] if encabezado.startswith("Bearer ") else None


class Api:
    def __init__(self, ajustes: Ajustes, casa: Casa, oyentes: Oyentes, acceso: Acceso):
        self._a = ajustes
        self._casa = casa
        self._oyentes = oyentes
        self._acceso = acceso

    def rutas(self, app: web.Application) -> None:
        app.middlewares.append(self._middleware)
        app.router.add_post("/api/entrar", self.entrar)
        app.router.add_post("/api/salir", self.salir)
        app.router.add_get("/api/estado", self.estado)
        app.router.add_post("/api/sintonizar", self.sintonizar)
        app.router.add_post("/api/siguiente", self.siguiente)
        app.router.add_post("/api/anterior", self.anterior)
        app.router.add_get("/api/escuchar", self.escuchar)
        app.router.add_get("/api/icono/{nombre:.+}", self.icono)

    # --- acceso ---

    @web.middleware
    async def _middleware(self, request: web.Request, handler):
        if not request.path.startswith("/api/") or request.path == "/api/entrar":
            return await handler(request)
        identidad = self._acceso.identidad_de_sesion(request.cookies.get(COOKIE))
        if identidad is not None:
            request[IDENTIDAD] = identidad
            return await handler(request)
        clave = _bearer(request)
        if clave is None:
            return _error(401, "hace falta entrar con la clave")
        resultado, identidad = self._acceso.probar(clave)
        if resultado == "ok":
            request[IDENTIDAD] = identidad
            return await handler(request)
        if resultado == "bloqueado":
            return _error(429, "demasiados intentos: probá de nuevo en un minuto")
        _log.warning("clave incorrecta (encabezado Authorization)")
        return _error(401, "clave incorrecta")

    async def _json(self, request: web.Request):
        """El cuerpo JSON, o una respuesta de error (415 si no es JSON, 400 si está roto)."""
        if request.content_type != "application/json":
            return None, _error(415, "el pedido tiene que ser JSON")
        crudo = await _leer_acotado(request, _MAX_CUERPO)
        if crudo is None:
            return None, _error(413, "pedido demasiado grande")
        if not crudo:
            return {}, None
        try:
            return json.loads(crudo), None
        except ValueError:
            return None, _error(400, "JSON roto")

    async def entrar(self, request: web.Request) -> web.Response:
        cuerpo, error = await self._json(request)
        if error is not None:
            return error
        clave = cuerpo.get("clave") if isinstance(cuerpo, dict) else None
        resultado, identidad = self._acceso.probar(clave if isinstance(clave, str) else None)
        if resultado == "bloqueado":
            return _error(429, "demasiados intentos: probá de nuevo en un minuto")
        if resultado != "ok":
            _log.warning("intento de entrar con una clave incorrecta")
            return _error(401, "clave incorrecta")
        _log.info("entró %s (%s)", identidad.id, identidad.permiso)
        respuesta = web.Response(status=204)
        seguro = request.secure or request.headers.get("X-Forwarded-Proto", "").lower() == "https"
        respuesta.set_cookie(COOKIE, self._acceso.nueva_sesion(identidad), max_age=DURACION_SESION, path="/",
                             httponly=True, samesite="Lax", secure=seguro)
        return respuesta

    async def salir(self, request: web.Request) -> web.Response:
        respuesta = web.Response(status=204)
        respuesta.del_cookie(COOKIE, path="/")
        return respuesta

    # --- estado y órdenes ---

    async def estado(self, request: web.Request) -> web.Response:
        return web.json_response({"en_linea": self._casa.en_linea, "visto_hace": self._casa.visto_hace(),
                                  "calidades": list(CALIDADES), "radio": self._casa.radio(),
                                  "permiso": request[IDENTIDAD].permiso})

    async def _orden(self, request: web.Request, tipo: str, **campos) -> web.Response:
        status, cuerpo = await self._casa.orden(tipo, **campos)
        return web.json_response(cuerpo, status=status)

    @staticmethod
    def _sin_permiso(request: web.Request) -> web.Response | None:
        """403 si la clave es solo de escucha: se decide antes de leer el cuerpo y de hablar con la PC."""
        if request[IDENTIDAD].permiso != "completa":
            return _error(403, "esta clave es solo para escuchar")
        return None

    async def sintonizar(self, request: web.Request) -> web.Response:
        if (prohibido := self._sin_permiso(request)) is not None:
            return prohibido
        cuerpo, error = await self._json(request)
        if error is not None:
            return error
        estacion = cuerpo.get("estacion") if isinstance(cuerpo, dict) else None
        if not isinstance(estacion, str) or not estacion.strip():
            return _error(400, "falta la emisora")
        return await self._orden(request, "sintonizar", estacion=estacion)

    async def siguiente(self, request: web.Request) -> web.Response:
        if (prohibido := self._sin_permiso(request)) is not None:
            return prohibido
        _, error = await self._json(request)
        return error or await self._orden(request, "siguiente")

    async def anterior(self, request: web.Request) -> web.Response:
        if (prohibido := self._sin_permiso(request)) is not None:
            return prohibido
        _, error = await self._json(request)
        return error or await self._orden(request, "anterior")

    # --- logos ---

    async def icono(self, request: web.Request) -> web.Response:
        logo = self._casa.icono(nombre_en_ruta(request, "/api/icono/"))
        if logo is None:
            return _error(404, "no hay logo para esa emisora")
        version, tipo, datos = logo
        cache = ("private, max-age=31536000, immutable" if version and request.query.get("v") == version
                 else "no-cache")
        return web.Response(body=datos, content_type=tipo, headers={"Cache-Control": cache})

    # --- audio ---

    async def escuchar(self, request: web.Request) -> web.StreamResponse:
        try:
            kbps = int(request.query.get("calidad", "96"))
        except ValueError:
            kbps = 0
        if kbps not in CALIDADES:
            return _error(400, f"calidad: una de {list(CALIDADES)}")
        if not self._casa.en_linea:
            return _error(503, "la radio está fuera de línea")
        encabezados = {"Content-Type": "audio/mpeg", "Cache-Control": "no-store"}
        if request.method == "HEAD":               # reproductores que prueban la URL: ni oyente ni audio
            return web.Response(headers=encabezados)
        respuesta = web.StreamResponse(headers=encabezados)
        await respuesta.prepare(request)
        sock = request.transport.get_extra_info("socket") if request.transport else None
        if sock is not None:
            try:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, _SNDBUF_OYENTE)
            except OSError:
                pass
        oyente = self._oyentes.agregar(kbps, request[IDENTIDAD].id)
        loop = asyncio.get_running_loop()
        ultimo_audio = loop.time()
        try:
            while not oyente.cerrado:
                if request.transport is None or request.transport.is_closing():
                    break                                   # el oyente se fue
                datos = await oyente.tomar(0.5)
                if datos is None:
                    if loop.time() - ultimo_audio >= self._a.sin_audio:
                        _log.info("oyente de %d kbps sin audio de la PC: se corta", kbps)
                        break
                    continue
                if not datos:
                    break
                ultimo_audio = loop.time()
                try:
                    await asyncio.wait_for(respuesta.write(datos), self._a.trabado)
                except TimeoutError:
                    _log.info("oyente de %d kbps trabado: se corta", kbps)
                    if request.transport is not None:
                        request.transport.abort()
                    break
        except (ConnectionError, RuntimeError):
            pass                                            # el oyente cortó en medio de una escritura
        finally:
            self._oyentes.quitar(oyente)
            oyente.cerrar()
        return respuesta

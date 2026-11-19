"""El lado de la PC: el WebSocket de control, uno de audio por calidad y la subida de logos (protocolo versión 1,
docs/superpowers/specs/2026-11-19-puente-nube-design.md)."""
import asyncio
import itertools
import json
import logging
import time
import urllib.parse
from collections.abc import Callable

from aiohttp import WSMsgType, web

from .acceso import clave_igual, validar_claves
from .config import CALIDADES, PROTOCOLO, Ajustes
from .oyentes import Oyentes

_log = logging.getLogger("cassette_relay.casa")

TIPOS_LOGO = ("image/png", "image/jpeg", "image/webp", "image/gif")
MAX_LOGO = 4 * 1024 * 1024
_MAX_MENSAJE = 1024 * 1024


def nombre_en_ruta(request: web.Request, prefijo: str) -> str:
    """El nombre de la emisora tal como vino en la ruta (url-encoded, puede tener `/` y `?` codificados)."""
    crudo = request.raw_path.split("?", 1)[0]
    return urllib.parse.unquote(crudo[len(prefijo):])


def _error(status: int, texto: str) -> web.Response:
    return web.json_response({"error": texto}, status=status)


class _Control:
    """Una conexión de control: manda en orden lo que se le encola, sin trabar a quien lo encola."""

    def __init__(self, ws: web.WebSocketResponse):
        self.ws = ws
        self.saludo = False
        self.ultimo_seq = 0
        self._salida: asyncio.Queue = asyncio.Queue()
        self._envio = asyncio.create_task(self._enviar())

    def mandar(self, mensaje: dict) -> None:
        self._salida.put_nowait(mensaje)

    async def _enviar(self) -> None:
        while True:
            mensaje = await self._salida.get()
            try:
                await self.ws.send_str(json.dumps(mensaje, ensure_ascii=False))
            except (ConnectionError, RuntimeError):
                return

    async def cerrar(self) -> None:
        self._envio.cancel()
        await self.ws.close()


class Casa:
    def __init__(self, ajustes: Ajustes, oyentes: Oyentes, reloj: Callable[[], float] = time.monotonic,
                 al_recibir_claves: Callable[[list[dict]], None] | None = None):
        self._a = ajustes
        self._al_recibir_claves = al_recibir_claves
        self._oyentes = oyentes
        self._reloj = reloj
        self._control: _Control | None = None
        self._audios: dict[int, web.WebSocketResponse] = {}
        self._estado: dict | None = None
        self._desde: float | None = None             # cuándo se fue la PC
        self._iconos: dict[str, tuple[str, str, bytes]] = {}
        self._pedidos: dict[str, tuple[str, float]] = {}   # emisora → (versión pedida, cuándo)
        self._ordenes: dict[str, asyncio.Future] = {}
        self._ids = itertools.count(1)

    # --- para la API ---

    @property
    def en_linea(self) -> bool:
        return self._control is not None and self._control.saludo

    def visto_hace(self) -> int | None:
        if self.en_linea or self._desde is None:
            return None
        return int(self._reloj() - self._desde)

    def radio(self) -> dict | None:
        return dict(self._estado) if self._estado is not None else None

    def icono(self, nombre: str) -> tuple[str, str, bytes] | None:
        return self._iconos.get(nombre)

    async def orden(self, tipo: str, **campos) -> tuple[int, dict]:
        if not self.en_linea:
            return 503, {"error": "la radio está fuera de línea"}
        ident = str(next(self._ids))
        futuro = asyncio.get_running_loop().create_future()
        self._ordenes[ident] = futuro
        self._control.mandar({"tipo": tipo, "id": ident, **campos})
        try:
            resultado = await asyncio.wait_for(futuro, self._a.espera_orden)
        except TimeoutError:
            _log.warning("la PC no contestó la orden %s a tiempo", tipo)
            return 504, {"error": "la radio no contestó"}
        finally:
            self._ordenes.pop(ident, None)
        if resultado is None:
            return 503, {"error": "la radio se desconectó"}
        if resultado.get("ok") is True:
            return 200, {"ok": True}
        return 409, {"error": str(resultado.get("error") or "la radio no pudo hacerlo")[:200]}

    def mandar_demanda(self, calidades: list[int]) -> None:
        if self.en_linea:
            _log.info("calidades pedidas a la PC: %s", calidades or "ninguna")
            self._control.mandar({"tipo": "demanda", "calidades": calidades})

    async def cerrar(self) -> None:
        if self._control is not None:
            await self._control.cerrar()
        for ws in list(self._audios.values()):
            await ws.close()

    # --- autenticación de la PC ---

    def _autorizada(self, request: web.Request) -> bool:
        encabezado = request.headers.get("Authorization", "")
        if not encabezado.startswith("Bearer "):
            return False
        return clave_igual(encabezado[len("Bearer "):], self._a.ingest_token)

    # --- control ---

    async def control(self, request: web.Request) -> web.StreamResponse:
        if not self._autorizada(request):
            _log.warning("conexión de control rechazada: clave incorrecta")
            return _error(401, "clave incorrecta")
        ws = web.WebSocketResponse(heartbeat=self._a.ping, max_msg_size=_MAX_MENSAJE)
        await ws.prepare(request)
        conexion = _Control(ws)
        viejo, self._control = self._control, conexion
        if viejo is not None:
            _log.info("la PC abrió otro control: se cierra el anterior")
            self._fallar_ordenes()
            asyncio.create_task(viejo.cerrar())
        try:
            async for mensaje in ws:
                if mensaje.type == WSMsgType.TEXT:
                    await self._mensaje(conexion, mensaje.data)
                elif mensaje.type == WSMsgType.BINARY:
                    _log.warning("la PC mandó datos binarios por el control; se ignoran")
        finally:
            conexion._envio.cancel()
            if self._control is conexion:
                if conexion.saludo:
                    _log.info("la PC se desconectó")
                self._control = None
                self._desde = self._reloj()
                self._fallar_ordenes()
        return ws

    def _fallar_ordenes(self) -> None:
        for futuro in self._ordenes.values():
            if not futuro.done():
                futuro.set_result(None)

    async def _mensaje(self, conexion: _Control, crudo: str) -> None:
        try:
            mensaje = json.loads(crudo)
            tipo = mensaje["tipo"]
        except (ValueError, TypeError, KeyError):
            _log.warning("mensaje de la PC que no se entiende; se ignora")
            return
        if tipo == "hola":
            if mensaje.get("protocolo") != PROTOCOLO:
                _log.error("la PC habla otro protocolo (%r); se corta", str(mensaje.get("protocolo"))[:20])
                await conexion.ws.close()
                return
            conexion.saludo = True
            self._desde = None
            self._pedidos.clear()                  # lo que estaba pedido se vuelve a pedir con el próximo estado
            _log.info("la PC se conectó")
            conexion.mandar({"tipo": "demanda", "calidades": self._oyentes.pedidas()})
        elif tipo == "estado":
            self._estado_nuevo(conexion, mensaje)
        elif tipo == "resultado":
            futuro = self._ordenes.get(str(mensaje.get("id")))
            if futuro is not None and not futuro.done():
                futuro.set_result(mensaje)
        elif tipo == "claves":
            lista = validar_claves(mensaje.get("claves"))
            if lista is None:
                _log.warning("la PC mandó una lista de claves inválida; se ignora y sigue la anterior")
            else:
                _log.info("la PC mandó %d claves", len(lista))
                if self._al_recibir_claves is not None:
                    self._al_recibir_claves(lista)
        elif tipo == "latido":
            pass
        else:
            _log.warning("tipo de mensaje de la PC desconocido %r; se ignora", str(tipo)[:40])

    def _estado_nuevo(self, conexion: _Control, mensaje: dict) -> None:
        seq = mensaje.get("seq")
        if not isinstance(seq, int) or isinstance(seq, bool) or seq <= conexion.ultimo_seq:
            return
        conexion.ultimo_seq = seq
        self._estado = {k: v for k, v in mensaje.items() if k not in ("tipo", "seq")}
        iconos = mensaje.get("iconos") if isinstance(mensaje.get("iconos"), dict) else {}
        for nombre in [n for n in self._iconos if n not in iconos]:
            del self._iconos[nombre]
        ahora = self._reloj()
        for nombre, version in iconos.items():
            if self._iconos.get(nombre, ("",))[0] == version:
                continue
            pedido = self._pedidos.get(nombre)
            if pedido is not None and pedido[0] == version and ahora - pedido[1] < self._a.vence_logo:
                continue
            self._pedidos[nombre] = (version, ahora)
            conexion.mandar({"tipo": "pedir_icono", "estacion": nombre})

    # --- audio ---

    async def audio(self, request: web.Request) -> web.StreamResponse:
        if not self._autorizada(request):
            _log.warning("conexión de audio rechazada: clave incorrecta")
            return _error(401, "clave incorrecta")
        ws = web.WebSocketResponse(heartbeat=self._a.ping, max_msg_size=_MAX_MENSAJE)
        await ws.prepare(request)
        try:
            kbps = int(request.query.get("calidad", ""))
        except ValueError:
            kbps = 0
        if kbps not in CALIDADES:
            await ws.close(code=1008, message=b"calidad desconocida")
            return ws
        viejo, self._audios[kbps] = self._audios.get(kbps), ws
        if viejo is not None:
            asyncio.create_task(viejo.close())
        _log.info("audio de %d kbps: la PC empezó a subir", kbps)
        try:
            async for mensaje in ws:
                if mensaje.type == WSMsgType.BINARY:
                    self._oyentes.repartir(kbps, mensaje.data)
        finally:
            if self._audios.get(kbps) is ws:
                del self._audios[kbps]
            _log.info("audio de %d kbps: la PC dejó de subir", kbps)
        return ws

    # --- logos ---

    async def subir_icono(self, request: web.Request) -> web.Response:
        if not self._autorizada(request):
            _log.warning("subida de logo rechazada: clave incorrecta")
            return _error(401, "clave incorrecta")
        nombre = nombre_en_ruta(request, "/casa/icono/")
        if nombre not in ((self._estado or {}).get("iconos") or {}):
            return _error(400, "esa emisora no está en el estado")
        if request.content_type not in TIPOS_LOGO:
            return _error(415, "tipo de imagen no permitido")
        if (request.content_length or 0) > MAX_LOGO:
            return _error(413, "logo demasiado grande")
        datos = await request.read()
        if len(datos) > MAX_LOGO:
            return _error(413, "logo demasiado grande")
        if not datos:
            return _error(400, "logo vacío")
        version = request.query.get("v", "")
        self._iconos[nombre] = (version, request.content_type, datos)
        self._pedidos.pop(nombre, None)
        return web.Response(status=204)

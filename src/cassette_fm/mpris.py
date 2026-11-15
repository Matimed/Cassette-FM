"""La radio como reproductor MPRIS, y dueña de las teclas multimedia de Cinnamon (también los botones de un parlante
Bluetooth, que llegan como teclas).

Cinnamon (csd-media-keys) da las teclas al programa que las pidió con GrabMediaPlayerKeys y, si nadie las pidió, al
*primer* reproductor MPRIS que se anunció; por eso la radio las pide y además se anuncia (para el applet de sonido).
Todo corre en un loop asyncio en el hilo "mpris"; las acciones de la radio van a un hilo aparte, de a una."""
import asyncio
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from dbus_fast import Message, MessageType, Variant
from dbus_fast.aio import MessageBus
from dbus_fast.constants import RequestNameReply
from dbus_fast.service import PropertyAccess, ServiceInterface, dbus_property, method

_log = logging.getLogger("cassette_fm")

_RUTA = "/org/mpris/MediaPlayer2"
_SIN_TEMA = "/org/mpris/MediaPlayer2/TrackList/NoTrack"
_APLICACION = "cassette-fm"
_TECLAS_BUS = "org.gnome.SettingsDaemon"
_TECLAS_RUTA = "/org/gnome/SettingsDaemon/MediaKeys"
_TECLAS_IFACE = "org.gnome.SettingsDaemon.MediaKeys"
_TECLAS = {"Next": "siguiente", "Previous": "anterior", "Play": "alternar", "Pause": "alternar", "Stop": "apagar"}


class _Foto:
    """Lo que muestran las propiedades: se toma en el hilo lector, nunca en el loop (la radio puede estar ocupada)."""

    def __init__(self, sonando, estado: dict, trackid: str):
        self.sonando = sonando
        # prendida aunque el tema nuevo todavía no arrancó (al cambiar de emisora): si no, se vería "Stopped" en el medio
        self.prendida = bool(estado.get("encendida"))
        self.volumen = estado.get("volumen", 0) / 100
        self.segundo = estado.get("segundo") or 0.0
        self.tomada = time.monotonic()
        self.trackid = trackid

    def metadata(self) -> dict:
        if self.sonando is None:
            return {"mpris:trackid": Variant("o", _SIN_TEMA)}
        emisora, pista = self.sonando
        meta = {"mpris:trackid": Variant("o", self.trackid),
                "xesam:title": Variant("s", pista.cancion or pista.titulo),
                "xesam:album": Variant("s", emisora)}
        if pista.artista:
            meta["xesam:artist"] = Variant("as", [pista.artista])
        if pista.duracion > 0:
            meta["mpris:length"] = Variant("x", int(pista.duracion * 1_000_000))
        return meta

    def posicion(self) -> int:
        if not self.prendida or self.sonando is None:
            return 0
        return int((self.segundo + time.monotonic() - self.tomada) * 1_000_000)


class _Raiz(ServiceInterface):
    def __init__(self):
        super().__init__("org.mpris.MediaPlayer2")

    @method()
    def Raise(self):
        pass

    @method()
    def Quit(self):
        pass

    @dbus_property(access=PropertyAccess.READ)
    def CanQuit(self) -> "b":
        return False

    @dbus_property(access=PropertyAccess.READ)
    def CanRaise(self) -> "b":
        return False

    @dbus_property(access=PropertyAccess.READ)
    def HasTrackList(self) -> "b":
        return False

    @dbus_property(access=PropertyAccess.READ)
    def Identity(self) -> "s":
        return "cassette-fm"

    @dbus_property(access=PropertyAccess.READ)
    def SupportedUriSchemes(self) -> "as":
        return []

    @dbus_property(access=PropertyAccess.READ)
    def SupportedMimeTypes(self) -> "as":
        return []


class _Player(ServiceInterface):
    def __init__(self, servicio: "ServicioMpris"):
        super().__init__("org.mpris.MediaPlayer2.Player")
        self._s = servicio

    @method()
    def Next(self):
        self._s.accion("siguiente")

    @method()
    def Previous(self):
        self._s.accion("anterior")

    @method()
    def PlayPause(self):
        self._s.accion("alternar")

    @method()
    def Play(self):
        self._s.accion("encender")

    @method()
    def Pause(self):
        self._s.accion("apagar")

    @method()
    def Stop(self):
        self._s.accion("apagar")

    @method()
    def Seek(self, desplazamiento: "x"):
        pass

    @method()
    def SetPosition(self, pista: "o", posicion: "x"):
        pass

    @method()
    def OpenUri(self, uri: "s"):
        pass

    @dbus_property(access=PropertyAccess.READ)
    def PlaybackStatus(self) -> "s":
        return "Playing" if self._s.foto.prendida else "Stopped"

    @dbus_property(access=PropertyAccess.READ)
    def Metadata(self) -> "a{sv}":
        return self._s.foto.metadata()

    @dbus_property(access=PropertyAccess.READ)
    def Position(self) -> "x":
        return self._s.foto.posicion()

    @dbus_property(access=PropertyAccess.READ)
    def Volume(self) -> "d":
        return self._s.foto.volumen

    @dbus_property(access=PropertyAccess.READ)
    def Rate(self) -> "d":
        return 1.0

    @dbus_property(access=PropertyAccess.READ)
    def MinimumRate(self) -> "d":
        return 1.0

    @dbus_property(access=PropertyAccess.READ)
    def MaximumRate(self) -> "d":
        return 1.0

    @dbus_property(access=PropertyAccess.READ)
    def CanGoNext(self) -> "b":
        return True

    @dbus_property(access=PropertyAccess.READ)
    def CanGoPrevious(self) -> "b":
        return True

    @dbus_property(access=PropertyAccess.READ)
    def CanPlay(self) -> "b":
        return True

    @dbus_property(access=PropertyAccess.READ)
    def CanPause(self) -> "b":
        return True

    @dbus_property(access=PropertyAccess.READ)
    def CanSeek(self) -> "b":
        return False

    @dbus_property(access=PropertyAccess.READ)
    def CanControl(self) -> "b":
        return True


class ServicioMpris:
    def __init__(self, radio, nombre: str = "org.mpris.MediaPlayer2.cassette_fm", direccion: str | None = None):
        self._radio = radio
        self._nombre = nombre
        self._direccion = direccion           # None: el bus de sesión del entorno
        self._acciones = ThreadPoolExecutor(1, thread_name_prefix="mpris-accion")   # de a una, en orden
        self._lector = ThreadPoolExecutor(1, thread_name_prefix="mpris-lector")
        self._loop: asyncio.AbstractEventLoop | None = None
        self._hilo: threading.Thread | None = None
        self._bus: MessageBus | None = None
        self._player = _Player(self)
        self._ultimo = None                   # (emisora, clave) del último tema, para el trackid
        self._n_tema = 0
        self._teclas_pedidas = False
        self.foto = _Foto(None, {}, _SIN_TEMA)

    def iniciar(self, timeout: float = 5.0) -> bool:
        """Publica el reproductor y pide las teclas. False (con un warning) si no hay bus; nunca lanza."""
        self._loop = asyncio.new_event_loop()
        self._hilo = threading.Thread(target=self._loop.run_forever, name="mpris", daemon=True)
        self._hilo.start()
        try:
            asyncio.run_coroutine_threadsafe(self._arrancar(), self._loop).result(timeout)
            return True
        except Exception as e:
            _log.warning("sin MPRIS ni teclas multimedia (%s)", e or type(e).__name__)
            self.cerrar()
            return False

    def cambio(self) -> None:
        """La radio cambió: thread-safe y sin bloquear (lee la radio en otro hilo y después avisa)."""
        loop = self._loop
        if loop is None or not loop.is_running():
            return
        try:
            loop.call_soon_threadsafe(lambda: asyncio.ensure_future(self._refrescar()))
        except RuntimeError:
            pass                              # el loop se cerró en el medio

    def accion(self, nombre: str) -> None:
        """Encola `radio.<nombre>()`; si falla se loguea y el servicio sigue."""
        def hacer():
            try:
                getattr(self._radio, nombre)()
            except Exception as e:
                _log.warning("no se pudo %s desde las teclas multimedia: %s", nombre, e)
        try:
            self._acciones.submit(hacer)
        except RuntimeError:
            pass                              # cerrando

    def cerrar(self, timeout: float = 2.0) -> None:
        loop, self._loop = self._loop, None
        if loop is not None and loop.is_running():
            try:
                asyncio.run_coroutine_threadsafe(self._desconectar(), loop).result(timeout)
            except Exception:
                _log.debug("MPRIS: cierre incompleto", exc_info=True)
            loop.call_soon_threadsafe(loop.stop)
        if self._hilo is not None:
            self._hilo.join(timeout)
        self._acciones.shutdown(wait=False, cancel_futures=True)
        self._lector.shutdown(wait=False, cancel_futures=True)

    # --- en el loop ---

    async def _arrancar(self) -> None:
        self.foto = await self._leer()
        self._bus = await MessageBus(bus_address=self._direccion).connect()
        self._bus.export(_RUTA, _Raiz())
        self._bus.export(_RUTA, self._player)
        respuesta = await self._bus.request_name(self._nombre)
        if respuesta not in (RequestNameReply.PRIMARY_OWNER, RequestNameReply.ALREADY_OWNER):
            raise RuntimeError(f"el nombre {self._nombre} ya lo tiene otro programa")
        self._bus.add_message_handler(self._al_mensaje)
        for regla in (f"type='signal',interface='{_TECLAS_IFACE}',member='MediaPlayerKeyPressed'",
                      f"type='signal',interface='org.freedesktop.DBus',member='NameOwnerChanged',arg0='{_TECLAS_BUS}'"):
            await self._llamar("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus",
                               "AddMatch", "s", [regla])
        await self._pedir_teclas()

    async def _llamar(self, destino, ruta, interfaz, miembro, firma, cuerpo) -> Message:
        respuesta = await self._bus.call(Message(destination=destino, path=ruta, interface=interfaz, member=miembro,
                                                 signature=firma, body=cuerpo))
        if respuesta.message_type == MessageType.ERROR:
            raise RuntimeError(f"{respuesta.error_name}: {respuesta.body[0] if respuesta.body else ''}")
        return respuesta

    async def _pedir_teclas(self) -> None:
        try:
            await self._llamar(_TECLAS_BUS, _TECLAS_RUTA, _TECLAS_IFACE, "GrabMediaPlayerKeys", "su", [_APLICACION, 0])
            self._teclas_pedidas = True
        except Exception as e:
            _log.warning("no se pudieron pedir las teclas multimedia a Cinnamon (%s)", e)

    def _al_mensaje(self, m: Message):
        if m.message_type != MessageType.SIGNAL:
            return None
        if m.interface == _TECLAS_IFACE and m.member == "MediaPlayerKeyPressed":
            aplicacion, tecla = (m.body + ["", ""])[:2]
            if aplicacion == _APLICACION and tecla in _TECLAS:
                self.accion(_TECLAS[tecla])
        elif m.member == "NameOwnerChanged" and m.body and m.body[0] == _TECLAS_BUS and m.body[2]:
            asyncio.ensure_future(self._pedir_teclas())      # csd-media-keys se reinició: perdimos el pedido
        return None

    async def _leer(self) -> _Foto:
        loop = asyncio.get_running_loop()
        sonando, estado = await loop.run_in_executor(self._lector, lambda: (self._radio.sonando(),
                                                                            self._radio.estado()))
        if sonando is not None:
            clave = (sonando[0], sonando[1].clave)
            if clave != self._ultimo:
                self._ultimo = clave
                self._n_tema += 1
        return _Foto(sonando, estado, f"/org/cassette_fm/pista/{self._n_tema}")

    async def _refrescar(self) -> None:
        try:
            self.foto = await self._leer()
            self._player.emit_properties_changed({"PlaybackStatus": "Playing" if self.foto.prendida else "Stopped",
                                                  "Metadata": self.foto.metadata()})
        except Exception:
            _log.exception("MPRIS: no se pudo avisar el cambio")

    async def _desconectar(self) -> None:
        if self._bus is None:
            return
        if self._teclas_pedidas:
            try:
                await asyncio.wait_for(self._llamar(_TECLAS_BUS, _TECLAS_RUTA, _TECLAS_IFACE,
                                                    "ReleaseMediaPlayerKeys", "s", [_APLICACION]), 1.0)
            except Exception:
                pass
        self._bus.disconnect()

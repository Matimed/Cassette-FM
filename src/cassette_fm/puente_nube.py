"""El puente a la nube: esta PC se conecta (siempre hacia afuera) a un relay y por ahí reporta el estado, recibe
órdenes y sube el audio del bus.

Un WebSocket de control permanente (`/casa/control`) y, mientras el relay pida una calidad, uno de audio por calidad
(`/casa/audio?calidad=<kbps>`). Todo con `Authorization: Bearer <clave>`; se reconecta solo. El protocolo está en
docs/superpowers/specs/2026-11-19-puente-nube-design.md."""
import json
import logging
import queue
import random
import socket
import struct
import threading
import time
import urllib.parse
import urllib.request
from collections.abc import Callable
from pathlib import Path

from websockets.exceptions import ConnectionClosed, InvalidHandshake, InvalidStatus, WebSocketException
from websockets.sync.client import connect

from cassette_fm.lan_server import TIPOS_IMAGEN, estado_publico, version_logo
from cassette_fm.lan_stream import CodificadorNoDisponible, SinCapacidad
from cassette_fm.radio import SinEstaciones

_log = logging.getLogger("cassette_fm")

PROTOCOLO = 1
CALIDADES = (64, 96, 160)
_CONEXION_ESTABLE = 60.0       # una conexión que duró más que esto vuelve la espera al mínimo
_VUELTA_LECTURA = 0.05         # cada cuánto el control mira si hay un estado para mandar
_VUELTA_AUDIO = 0.2            # cada cuánto una conexión de audio mira si sigue pedida
_BUFFER_ENVIO_BYTES = 8192     # como en la LAN: que el atraso no se esconda en el kernel


def mensaje_estado(estado: dict, seq: int) -> dict:
    """Lo mismo que el `/status` de la LAN, pero `iconos` lleva solo la versión de cada logo (el relay los pide)."""
    iconos = {}
    for nombre, ruta in (estado.get("iconos") or {}).items():
        version = version_logo(Path(ruta))
        if version:
            iconos[nombre] = version
    return {"tipo": "estado", "seq": seq, **estado_publico(estado), "iconos": iconos}


def url_icono(base: str, emisora: str, version: str) -> str:
    """Al mismo host del relay por HTTP(S): wss → https, ws → http."""
    esquema, resto = base.split("://", 1)
    http = "https" if esquema == "wss" else "http"
    return f"{http}://{resto}/casa/icono/{urllib.parse.quote(emisora, safe='')}?v={urllib.parse.quote(version)}"


def subir_icono(url: str, token: str, datos: bytes, tipo: str) -> None:
    pedido = urllib.request.Request(url, data=datos, method="PUT",
                                    headers={"Authorization": f"Bearer {token}", "Content-Type": tipo})
    with urllib.request.urlopen(pedido, timeout=15) as respuesta:
        respuesta.read()


class Espera:
    """Espera entre reintentos: se duplica hasta `maximo`, con algo de azar para no reconectar todos a la vez."""

    def __init__(self, minimo: float = 1.0, maximo: float = 30.0, azar: Callable[[], float] = random.random):
        self._minimo, self._maximo, self._azar = minimo, maximo, azar
        self._intentos = 0

    def siguiente(self) -> float:
        base = min(self._maximo, self._minimo * 2 ** self._intentos)
        self._intentos += 1
        return base * (0.5 + 0.5 * self._azar())

    def reiniciar(self) -> None:
        self._intentos = 0


class _Rechazado(Exception):
    """El relay no aceptó la clave."""


def _cortar_socket(ws) -> None:
    """Corta una conexión desde otro hilo sin esperar nada: el hilo que la usa ve el error y la cierra él."""
    if ws is None:
        return
    try:
        ws.socket.shutdown(socket.SHUT_RDWR)
    except OSError:
        pass


class _Audio:
    """Una conexión de audio de una calidad: su hilo y cómo pararla."""

    def __init__(self):
        self.parar = threading.Event()
        self.reabrir = threading.Event()      # reconectar(): se cierra y se vuelve a abrir (con la clave nueva)
        self.ws = None
        self.hilo: threading.Thread | None = None


class PuenteNube:
    def __init__(self, radio, difusores, url: str, token: Callable[[], str], conectar=connect,
                 subir=None, reloj: Callable[[], float] = time.monotonic, ping_segundos: float = 20.0,
                 intervalo_estado: float = 0.5, espera_401: float = 300.0, gracia_control: float = 60.0,
                 espera: Espera | None = None, timeout_envio_audio: float = 10.0):
        self._radio = radio
        self._difusores = difusores
        self._url = url.rstrip("/")
        self._token = token
        self._conectar = conectar
        self._subir = subir or subir_icono
        self._reloj = reloj
        self._ping = ping_segundos
        self._intervalo_estado = intervalo_estado
        self._espera_401 = espera_401
        self._gracia_control = gracia_control
        self._espera = espera or Espera()
        self._timeout_envio = timeout_envio_audio
        self._parar = threading.Event()
        self._despertar = threading.Event()      # reconectar() corta la espera entre intentos
        self._lock = threading.Lock()
        self._envio = threading.Lock()           # un mensaje a la vez por el control
        self._ws = None                          # la conexión de control abierta, si hay
        self._desde: float | None = None
        self._error: str | None = None
        self._cambio = threading.Event()
        self._ordenes: queue.Queue = queue.Queue()
        self._logos: queue.Queue = queue.Queue()  # aparte de las órdenes: un PUT lento no demora un "sintonizar"
        self._logos_pendientes: set[str] = set()
        self._hilos: list[threading.Thread] = []
        self._audios: dict[int, _Audio] = {}     # calidades pedidas por el relay, con su conexión
        self._control_caido_desde: float | None = None

    # --- ciclo de vida ---

    def iniciar(self) -> None:
        self._radio.escuchar_cambios(self._cambio.set)
        for nombre, objetivo in (("nube-control", self._bucle_control), ("nube-ordenes", self._bucle_ordenes),
                                 ("nube-logos", self._bucle_logos)):
            hilo = threading.Thread(target=objetivo, daemon=True, name=nombre)
            hilo.start()
            self._hilos.append(hilo)

    def cerrar(self) -> None:
        self._parar.set()
        self._despertar.set()
        self._ordenes.put(None)
        self._logos.put(None)
        self._cerrar_control()
        for audio in self._pedir_calidades(set()):
            audio.hilo.join(timeout=5)
        for hilo in self._hilos:
            hilo.join(timeout=5)

    def reconectar(self) -> None:
        """Corta las conexiones y vuelve a conectar enseguida (p. ej. con una clave nueva)."""
        self._despertar.set()
        self._cerrar_control()
        with self._lock:
            audios = list(self._audios.values())
        for audio in audios:
            audio.reabrir.set()
            _cortar_socket(audio.ws)          # aunque esté trabada en un envío

    def info(self) -> dict:
        with self._lock:
            subiendo = sorted(k for k, a in self._audios.items() if a.ws is not None)
            hace = self._reloj() - self._desde if self._desde is not None else None
            return {"conectado": self._ws is not None, "conectado_hace": hace, "error": self._error,
                    "subiendo": subiendo}

    # --- control ---

    def _encabezados(self) -> dict:
        return {"Authorization": f"Bearer {self._token()}"}

    def _abrir(self, ruta: str):
        try:
            return self._conectar(self._url + ruta, additional_headers=self._encabezados(), open_timeout=10,
                                  ping_interval=self._ping, ping_timeout=self._ping, close_timeout=2,
                                  compression=None, proxy=None, legacy=True)
        except InvalidStatus as e:
            if e.response.status_code in (401, 403):
                raise _Rechazado(f"el relay rechazó la clave (HTTP {e.response.status_code}): la de `cassette nube` "
                                 f"tiene que ser la misma que tiene cargada el relay") from None
            raise

    def _bucle_control(self) -> None:
        caido_desde: float | None = None
        while not self._parar.is_set():
            try:
                ws = self._abrir("/casa/control")
            except _Rechazado as e:
                if self._error != str(e):
                    _log.error("puente a la nube: %s", e)
                with self._lock:
                    self._error = str(e)
                self._esperar(self._espera_401)
                continue
            except (OSError, TimeoutError, InvalidHandshake, WebSocketException) as e:
                if caido_desde is None:
                    caido_desde = self._reloj()
                    _log.warning("puente a la nube: no se pudo conectar con el relay (%s); se reintenta", e)
                else:
                    _log.debug("puente a la nube: reintento fallido (%s)", e)
                with self._lock:
                    self._error = f"no se pudo conectar con el relay: {e}"
                self._esperar(self._espera.siguiente())
                continue
            inicio = self._reloj()
            if caido_desde is not None:
                _log.info("puente a la nube: conectado de nuevo al relay después de %.0f s", inicio - caido_desde)
            else:
                _log.info("puente a la nube: conectado al relay")
            with self._lock:
                self._ws, self._desde, self._error = ws, inicio, None
                self._control_caido_desde = None
            try:
                self._sesion(ws)
            except Exception:
                _log.exception("puente a la nube: error inesperado en el control; se reconecta")
            finally:
                with self._lock:
                    self._ws = self._desde = None
                    self._control_caido_desde = self._reloj()
                ws.close()
            if self._parar.is_set():
                break
            caido_desde = self._reloj()
            _log.warning("puente a la nube: se cortó la conexión con el relay; se reintenta")
            if caido_desde - inicio >= _CONEXION_ESTABLE:
                self._espera.reiniciar()
            if not self._despertar.is_set():
                self._esperar(self._espera.siguiente())

    def _esperar(self, segundos: float) -> None:
        self._despertar.wait(segundos)
        self._despertar.clear()

    def _cerrar_control(self) -> None:
        with self._lock:
            ws = self._ws
        if ws is not None:
            ws.close()

    def _sesion(self, ws) -> None:
        seq = 0
        try:
            self._mandar(ws, {"tipo": "hola", "protocolo": PROTOCOLO, "calidades": list(CALIDADES)})
            self._cambio.clear()
            seq += 1
            self._mandar(ws, mensaje_estado(self._radio.estado(), seq))
            ultimo = self._reloj()
            while not self._parar.is_set():
                try:
                    crudo = ws.recv(timeout=_VUELTA_LECTURA)
                except TimeoutError:
                    crudo = None
                if crudo is not None:
                    self._recibir(ws, crudo)
                if self._cambio.is_set() and self._reloj() - ultimo >= self._intervalo_estado:
                    self._cambio.clear()
                    seq += 1
                    self._mandar(ws, mensaje_estado(self._radio.estado(), seq))
                    ultimo = self._reloj()
        except ConnectionClosed:
            pass

    def _mandar(self, ws, mensaje: dict) -> None:
        with self._envio:
            ws.send(json.dumps(mensaje, ensure_ascii=False))

    def _recibir(self, ws, crudo) -> None:
        if isinstance(crudo, bytes):
            _log.warning("puente a la nube: el relay mandó datos binarios por el control; se ignoran")
            return
        try:
            mensaje = json.loads(crudo)
            tipo = mensaje["tipo"]
        except (ValueError, TypeError, KeyError):
            _log.warning("puente a la nube: mensaje del relay que no se entiende; se ignora")
            return
        if tipo in ("sintonizar", "siguiente", "anterior"):
            self._ordenes.put((ws, mensaje))
        elif tipo == "pedir_icono":
            nombre = mensaje.get("estacion")
            if isinstance(nombre, str) and nombre not in self._logos_pendientes:
                self._logos_pendientes.add(nombre)    # el mismo logo pedido dos veces se sube una
                self._logos.put(nombre)
        elif tipo == "demanda":
            self._demanda(mensaje)
        else:
            _log.warning("puente a la nube: tipo de mensaje desconocido %r; se ignora", str(tipo)[:40])

    # --- audio ---

    def _demanda(self, mensaje: dict) -> None:
        calidades = mensaje.get("calidades")
        if not isinstance(calidades, list):
            _log.warning("puente a la nube: demanda sin lista de calidades; se ignora")
            return
        validas = {c for c in calidades if isinstance(c, int) and not isinstance(c, bool) and c in CALIDADES}
        if len(validas) != len(calidades):
            _log.warning("puente a la nube: calidades que no se ofrecen en la demanda %s; se ignoran",
                         str(calidades)[:80])
        self._pedir_calidades(validas)

    def _pedir_calidades(self, calidades: set[int]) -> list[_Audio]:
        """Abre las conexiones que faltan y para las que sobran; devuelve las paradas."""
        if self._difusores is None:
            return []
        paradas = []
        with self._lock:
            for kbps in list(self._audios):
                if kbps not in calidades:
                    audio = self._audios.pop(kbps)
                    audio.parar.set()
                    paradas.append(audio)
            for kbps in calidades - set(self._audios):
                if self._parar.is_set():
                    break
                audio = self._audios[kbps] = _Audio()
                audio.hilo = threading.Thread(target=self._bucle_audio, args=(kbps, audio), daemon=True,
                                              name=f"nube-audio-{kbps}")
                audio.hilo.start()
        for audio in paradas:
            _cortar_socket(audio.ws)           # sin close() acá: con el envío trabado colgaría a quien llama
        return paradas

    def _audio_vigente(self, kbps: int, audio: _Audio) -> bool:
        """Sigue pedida y el control no lleva caído más que la gracia (sin control no hay cómo saber si se pide)."""
        if audio.parar.is_set() or self._parar.is_set():
            return False
        with self._lock:
            caido = self._control_caido_desde
        if caido is not None and self._reloj() - caido > self._gracia_control:
            _log.info("puente a la nube: sin control hace más de %.0f s, se deja de subir %d kbps",
                      self._gracia_control, kbps)
            with self._lock:
                if self._audios.get(kbps) is audio:
                    del self._audios[kbps]
            audio.parar.set()
            return False
        return True

    def _bucle_audio(self, kbps: int, audio: _Audio) -> None:
        espera = Espera()
        while self._audio_vigente(kbps, audio):
            try:
                ws = self._abrir(f"/casa/audio?calidad={kbps}")
            except (_Rechazado, OSError, TimeoutError, InvalidHandshake, WebSocketException) as e:
                _log.debug("puente a la nube: no se pudo abrir el audio de %d kbps (%s)", kbps, e)
                audio.parar.wait(espera.siguiente())
                continue
            try:
                ws.socket.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, _BUFFER_ENVIO_BYTES)
                # un relay que deja de leer traba el envío (y con él el ping): pasado este plazo falla y se reabre
                segundos = max(self._timeout_envio, 0.001)
                ws.socket.setsockopt(socket.SOL_SOCKET, socket.SO_SNDTIMEO,
                                     struct.pack("ll", int(segundos), int(segundos % 1 * 1_000_000)))
            except OSError:
                pass
            with self._lock:
                audio.ws = ws
            audio.reabrir.clear()
            if audio.parar.is_set():           # la pararon mientras se abría: el corte no la alcanzó
                _cortar_socket(ws)
            try:
                self._subir_audio(kbps, audio, ws)
                espera.reiniciar()
            except (CodificadorNoDisponible, SinCapacidad) as e:
                _log.warning("puente a la nube: no se puede codificar a %d kbps: %s", kbps, e)
                audio.parar.wait(espera.siguiente())
            except Exception:
                _log.exception("puente a la nube: error inesperado en el audio de %d kbps; se reintenta", kbps)
                audio.parar.wait(espera.siguiente())
            finally:
                with self._lock:
                    audio.ws = None
                ws.close()

    def _subir_audio(self, kbps: int, audio: _Audio, ws) -> None:
        difusor = self._difusores.de(kbps)
        cola = difusor.suscribir()
        try:
            while self._audio_vigente(kbps, audio):
                if audio.reabrir.is_set():
                    audio.reabrir.clear()
                    return
                try:
                    datos = cola.get(timeout=_VUELTA_AUDIO)
                except queue.Empty:
                    continue
                if datos is None:              # el difusor la cortó (atrasada, o se recreó el bus): se reabre en vivo
                    return
                ws.send(datos)
        except (ConnectionClosed, OSError):
            return
        finally:
            difusor.desuscribir(cola)

    # --- órdenes (de a una, fuera del hilo que lee la conexión) ---

    def _bucle_ordenes(self) -> None:
        while True:
            item = self._ordenes.get()
            if item is None:
                return
            ws, mensaje = item
            respuesta = self._ejecutar(mensaje)
            if respuesta is None:
                continue
            try:
                self._mandar(ws, {"tipo": "resultado", "id": mensaje.get("id"), **respuesta})
            except (ConnectionClosed, OSError):
                pass                      # se cortó el control: el relay no espera más este resultado

    def _ejecutar(self, mensaje: dict) -> dict | None:
        tipo = mensaje["tipo"]
        try:
            if tipo == "sintonizar":
                nombre = mensaje.get("estacion")
                if nombre not in [e.nombre for e in self._radio.estaciones()]:
                    return {"ok": False, "error": "esa emisora no existe"}
                self._radio.sintonizar(nombre, oir_aca=False)
            elif tipo == "siguiente":
                self._radio.siguiente(oir_aca=False)
            elif tipo == "anterior":
                self._radio.anterior(oir_aca=False)
            else:
                return None
        except SinEstaciones:
            return {"ok": False, "error": "no hay estaciones"}
        except Exception:
            _log.exception("puente a la nube: error al ejecutar %r", tipo)
            return {"ok": False, "error": "error interno"}
        return {"ok": True}

    def _bucle_logos(self) -> None:
        while True:
            nombre = self._logos.get()
            if nombre is None:
                return
            self._logos_pendientes.discard(nombre)
            self._subir_logo(nombre)

    def _subir_logo(self, nombre) -> None:
        """Solo logos del mapa de la propia radio, por nombre: el relay nunca elige una ruta de esta PC."""
        ruta = (self._radio.estado().get("iconos") or {}).get(nombre) if isinstance(nombre, str) else None
        version = version_logo(Path(ruta)) if ruta else None
        if version is None:
            _log.warning("puente a la nube: el relay pidió un logo que no hay (%r)", str(nombre)[:60])
            return
        try:
            datos = Path(ruta).read_bytes()
            self._subir(url_icono(self._url, nombre, version), self._token(), datos,
                        TIPOS_IMAGEN[Path(ruta).suffix.lower()])
        except Exception as e:
            _log.warning("puente a la nube: no se pudo subir el logo de %r: %s", nombre, e)

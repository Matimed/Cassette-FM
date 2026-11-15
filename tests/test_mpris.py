import asyncio
import logging
import threading
import time
from pathlib import Path

import pytest
from dbus_fast.aio import MessageBus
from dbus_fast.service import ServiceInterface, method, signal

from cassette_fm.biblioteca import Pista
from cassette_fm.mpris import ServicioMpris
from cassette_fm.radio import SinEstaciones

NOMBRE = "org.mpris.MediaPlayer2.cassette_fm"
RUTA = "/org/mpris/MediaPlayer2"
PLAYER = "org.mpris.MediaPlayer2.Player"


def esperar(condicion, segundos=3.0):
    fin = time.monotonic() + segundos
    while time.monotonic() < fin:
        if condicion():
            return True
        time.sleep(0.02)
    return False


class RadioFalsa:
    def __init__(self):
        self.acciones = []
        self.encendida = False
        self.pista = Pista(Path("/m/a.mp3"), 200.0, "Queen - Bohemian Rhapsody", artista="Queen",
                           cancion="Bohemian Rhapsody")
        self.emisora = "Rock"
        self.al_cambiar = None
        self.lenta = 0.0
        self.falla = None
        self.en_curso = 0
        self.solapadas = False

    def _accion(self, nombre):
        self.en_curso += 1
        if self.en_curso > 1:
            self.solapadas = True
        try:
            time.sleep(self.lenta)
            self.acciones.append(nombre)
            if self.falla:
                falla, self.falla = self.falla, None
                raise falla
        finally:
            self.en_curso -= 1

    def siguiente(self):
        self._accion("siguiente")

    def anterior(self):
        self._accion("anterior")

    def alternar(self):
        self._accion("alternar")

    def encender(self):
        self._accion("encender")

    def apagar(self):
        self._accion("apagar")

    def sonando(self):
        return (self.emisora, self.pista) if self.encendida else None

    def estado(self):
        return {"encendida": self.encendida, "volumen": 70, "segundo": 12.5 if self.encendida else None}


class Bucle:
    """Un loop asyncio en un hilo, para hablarle al bus desde tests sincrónicos."""

    def __init__(self):
        self.loop = asyncio.new_event_loop()
        threading.Thread(target=self.loop.run_forever, daemon=True).start()

    def __call__(self, coro, timeout=5):
        return asyncio.run_coroutine_threadsafe(coro, self.loop).result(timeout)

    def bus(self, direccion):
        async def conectar():
            return await MessageBus(bus_address=direccion).connect()
        return self(conectar())

    def cerrar(self):
        self.loop.call_soon_threadsafe(self.loop.stop)


class TeclasFalsas(ServiceInterface):
    """Hace de csd-media-keys: registra los pedidos y manda teclas."""

    def __init__(self):
        super().__init__("org.gnome.SettingsDaemon.MediaKeys")
        self.pedidos = []

    @method()
    def GrabMediaPlayerKeys(self, aplicacion: "s", tiempo: "u"):
        self.pedidos.append(("grab", aplicacion, tiempo))

    @method()
    def ReleaseMediaPlayerKeys(self, aplicacion: "s"):
        self.pedidos.append(("release", aplicacion))

    @signal()
    def MediaPlayerKeyPressed(self, aplicacion, tecla) -> "ss":
        return [aplicacion, tecla]


@pytest.fixture
def bucle():
    b = Bucle()
    yield b
    b.cerrar()


@pytest.fixture
def cliente(bus_privado, bucle):
    bus = bucle.bus(bus_privado)
    yield bus
    bus.disconnect()


@pytest.fixture
def teclas(bus_privado, bucle):
    bus = bucle.bus(bus_privado)
    falsas = TeclasFalsas()
    bus.export("/org/gnome/SettingsDaemon/MediaKeys", falsas)
    bucle(bus.request_name("org.gnome.SettingsDaemon"))
    falsas.bus = bus
    yield falsas
    bus.disconnect()


@pytest.fixture
def servicio(bus_privado):
    creados = []

    def crear(radio=None):
        radio = radio or RadioFalsa()
        s = ServicioMpris(radio, direccion=bus_privado)
        assert s.iniciar()
        creados.append(s)
        return s, radio
    yield crear
    for s in creados:
        s.cerrar()


def player(cliente, bucle):
    async def armar():
        intro = await cliente.introspect(NOMBRE, RUTA)
        obj = cliente.get_proxy_object(NOMBRE, RUTA, intro)
        return obj.get_interface(PLAYER), obj.get_interface("org.mpris.MediaPlayer2"), \
            obj.get_interface("org.freedesktop.DBus.Properties")
    return bucle(armar())


def test_next_pasa_a_la_siguiente_emisora(servicio, cliente, bucle):
    _, radio = servicio()
    p, _, _ = player(cliente, bucle)
    bucle(p.call_next())
    assert esperar(lambda: radio.acciones == ["siguiente"])


def test_cada_metodo_llama_a_su_accion(servicio, cliente, bucle):
    _, radio = servicio()
    p, _, _ = player(cliente, bucle)
    for llamada in (p.call_previous, p.call_play_pause, p.call_play, p.call_pause, p.call_stop):
        bucle(llamada())
    assert esperar(lambda: radio.acciones == ["anterior", "alternar", "encender", "apagar", "apagar"])


def test_estado_y_metadata(servicio, cliente, bucle):
    radio = RadioFalsa()
    radio.encendida = True
    servicio(radio)
    p, _, _ = player(cliente, bucle)
    assert bucle(p.get_playback_status()) == "Playing"
    meta = {k: v.value for k, v in bucle(p.get_metadata()).items()}
    assert meta["xesam:title"] == "Bohemian Rhapsody"
    assert meta["xesam:artist"] == ["Queen"]
    assert meta["xesam:album"] == "Rock"
    assert meta["mpris:length"] == 200_000_000
    assert meta["mpris:trackid"].startswith("/org/cassette_fm/pista/")
    assert bucle(p.get_position()) >= 12_500_000
    assert bucle(p.get_volume()) == pytest.approx(0.7)


def test_apagada_esta_stopped_sin_metadata(servicio, cliente, bucle):
    servicio()
    p, _, _ = player(cliente, bucle)
    assert bucle(p.get_playback_status()) == "Stopped"
    meta = {k: v.value for k, v in bucle(p.get_metadata()).items()}
    assert meta == {"mpris:trackid": "/org/mpris/MediaPlayer2/TrackList/NoTrack"}
    assert bucle(p.get_position()) == 0


def test_metadata_sin_artista_ni_duracion(servicio, cliente, bucle):
    radio = RadioFalsa()
    radio.encendida = True
    radio.pista = Pista(Path("/m/b.mp3"), 0.0, "b")
    servicio(radio)
    p, _, _ = player(cliente, bucle)
    meta = {k: v.value for k, v in bucle(p.get_metadata()).items()}
    assert meta["xesam:title"] == "b"
    assert "xesam:artist" not in meta and "mpris:length" not in meta


def test_cambio_emite_properties_changed(servicio, cliente, bucle):
    s, radio = servicio()
    _, _, props = player(cliente, bucle)
    vistos = []
    props.on_properties_changed(lambda iface, cambios, _: vistos.append((iface, cambios)))
    radio.encendida = True
    s.cambio()
    assert esperar(lambda: vistos)
    iface, cambios = vistos[0]
    assert iface == PLAYER
    assert cambios["PlaybackStatus"].value == "Playing"
    assert cambios["Metadata"].value["xesam:album"].value == "Rock"


def test_otro_tema_cambia_el_trackid(servicio, cliente, bucle):
    radio = RadioFalsa()
    radio.encendida = True
    s, _ = servicio(radio)
    p, _, _ = player(cliente, bucle)
    antes = bucle(p.get_metadata())["mpris:trackid"].value
    radio.pista = Pista(Path("/m/c.mp3"), 100.0, "c")
    s.cambio()
    assert esperar(lambda: bucle(p.get_metadata())["mpris:trackid"].value != antes)


def test_cambio_no_bloquea_con_el_loop_ocupado(servicio, cliente, bucle):
    s, radio = servicio()
    radio.lenta = 1.0
    p, _, _ = player(cliente, bucle)
    bucle(p.call_next())
    inicio = time.monotonic()
    s.cambio()
    assert time.monotonic() - inicio < 0.1
    assert esperar(lambda: radio.acciones == ["siguiente"])


def test_una_accion_que_falla_no_mata_el_servicio(servicio, cliente, bucle, caplog):
    _, radio = servicio()
    radio.falla = SinEstaciones("no hay estaciones")
    p, _, _ = player(cliente, bucle)
    with caplog.at_level(logging.WARNING, logger="cassette_fm"):
        bucle(p.call_next())
        assert esperar(lambda: "no hay estaciones" in caplog.text)
    bucle(p.call_next())
    assert esperar(lambda: radio.acciones == ["siguiente", "siguiente"])
    assert "siguiente" in caplog.text


def test_dos_next_seguidos_se_procesan_en_orden(servicio, cliente, bucle):
    _, radio = servicio()
    radio.lenta = 0.2
    p, _, _ = player(cliente, bucle)
    bucle(p.call_next())
    bucle(p.call_previous())
    assert esperar(lambda: radio.acciones == ["siguiente", "anterior"])
    assert not radio.solapadas


def test_capacidades(servicio, cliente, bucle):
    servicio()
    p, raiz, _ = player(cliente, bucle)
    for getter in (p.get_can_go_next, p.get_can_go_previous, p.get_can_play, p.get_can_pause, p.get_can_control):
        assert bucle(getter()) is True
    assert bucle(p.get_can_seek()) is False
    assert bucle(raiz.get_can_quit()) is False
    assert bucle(raiz.get_can_raise()) is False
    assert bucle(raiz.get_has_track_list()) is False
    assert bucle(raiz.get_identity()) == "cassette-fm"


def test_sin_bus_iniciar_da_false_y_avisa(tmp_path, caplog):
    s = ServicioMpris(RadioFalsa(), direccion=f"unix:path={tmp_path}/no-hay")
    with caplog.at_level(logging.WARNING, logger="cassette_fm"):
        assert s.iniciar(timeout=2) is False
    assert "MPRIS" in caplog.text
    s.cambio()        # no lanza
    s.cerrar()


def test_cerrar_termina_el_hilo(servicio):
    s, _ = servicio()
    s.cerrar()
    assert esperar(lambda: not any(t.name == "mpris" and t.is_alive() for t in threading.enumerate()))


def test_pide_las_teclas_al_iniciar(teclas, servicio):
    servicio()
    assert esperar(lambda: ("grab", "cassette-fm", 0) in teclas.pedidos)


def test_cada_tecla_llama_a_su_accion(teclas, servicio, bucle):
    _, radio = servicio()
    assert esperar(lambda: teclas.pedidos)
    for tecla in ("Next", "Previous", "Play", "Pause", "Stop"):
        bucle.loop.call_soon_threadsafe(teclas.MediaPlayerKeyPressed, "cassette-fm", tecla)
    assert esperar(lambda: radio.acciones == ["siguiente", "anterior", "alternar", "alternar", "apagar"])


def test_ignora_teclas_de_otra_aplicacion(teclas, servicio, bucle):
    _, radio = servicio()
    assert esperar(lambda: teclas.pedidos)
    bucle.loop.call_soon_threadsafe(teclas.MediaPlayerKeyPressed, "otra", "Next")
    bucle.loop.call_soon_threadsafe(teclas.MediaPlayerKeyPressed, "cassette-fm", "Previous")
    assert esperar(lambda: radio.acciones == ["anterior"])
    time.sleep(0.2)
    assert radio.acciones == ["anterior"]


def test_vuelve_a_pedirlas_si_settings_daemon_se_reinicia(teclas, servicio, bucle):
    servicio()
    assert esperar(lambda: len(teclas.pedidos) == 1)
    bucle(teclas.bus.release_name("org.gnome.SettingsDaemon"))
    bucle(teclas.bus.request_name("org.gnome.SettingsDaemon"))
    assert esperar(lambda: [p for p in teclas.pedidos if p[0] == "grab"] == [("grab", "cassette-fm", 0)] * 2)


def test_sin_settings_daemon_igual_publica_mpris(servicio, cliente, bucle, caplog):
    with caplog.at_level(logging.WARNING, logger="cassette_fm"):
        _, radio = servicio()
        assert esperar(lambda: "teclas" in caplog.text)
    p, _, _ = player(cliente, bucle)
    bucle(p.call_next())
    assert esperar(lambda: radio.acciones == ["siguiente"])


def test_cerrar_suelta_las_teclas(teclas, servicio):
    s, _ = servicio()
    assert esperar(lambda: teclas.pedidos)
    s.cerrar()
    assert esperar(lambda: ("release", "cassette-fm") in teclas.pedidos)

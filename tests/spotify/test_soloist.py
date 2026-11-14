import json
import socket
import threading
import time

import pytest
from websockets.sync.server import serve

from cassette_fm.spotify.api import ErrorSpotify
from cassette_fm.spotify.soloist import ClienteSoloist


def puerto_libre():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class SoloistFalso:
    """WebSocket que hace de Soloist: registra los comandos y manda eventos a pedido."""

    def __init__(self, puerto=None):
        self.puerto = puerto or puerto_libre()
        self.comandos = []
        self.conexiones = []
        self.listo = threading.Event()
        self._arrancar()

    def _atender(self, ws):
        self.conexiones.append(ws)
        self.listo.set()
        try:
            for crudo in ws:
                self.comandos.append(json.loads(crudo))
        except Exception:
            pass

    def _arrancar(self):
        self.servidor = serve(self._atender, "127.0.0.1", self.puerto)
        threading.Thread(target=self.servidor.serve_forever, daemon=True).start()

    def enviar(self, evento):
        self.conexiones[-1].send(json.dumps(evento))

    def cortar(self):
        for c in self.conexiones:
            c.close()
        self.servidor.shutdown()

    def volver(self):
        self.listo.clear()
        self._arrancar()


def esperar(condicion, segundos=3.0):
    fin = time.monotonic() + segundos
    while time.monotonic() < fin:
        if condicion():
            return True
        time.sleep(0.02)
    return False


@pytest.fixture
def soloist():
    s = SoloistFalso()
    yield s
    try:
        s.servidor.shutdown()
    except Exception:
        pass


def test_comando_con_el_formato_de_soloist(soloist):
    c = ClienteSoloist(f"ws://127.0.0.1:{soloist.puerto}", al_evento=lambda e: None)
    c.conectar(2)
    c.comando("set_volume", volume=40)
    assert esperar(lambda: {"type": "command", "command": "set_volume", "volume": 40} in soloist.comandos)
    assert c.conectado
    c.cerrar()


def test_los_eventos_llegan_en_orden(soloist):
    vistos = []
    c = ClienteSoloist(f"ws://127.0.0.1:{soloist.puerto}", al_evento=vistos.append)
    c.conectar(2)
    soloist.listo.wait(2)
    for i in range(5):
        soloist.enviar({"type": "position_sync", "position": {"position_ms": i, "timestamp_ms": 0, "speed": 1}})
    assert esperar(lambda: len(vistos) == 5)
    assert [e["position"]["position_ms"] for e in vistos] == [0, 1, 2, 3, 4]
    c.cerrar()


def test_se_reconecta_solo_y_pide_el_estado(soloist):
    cortes = []
    c = ClienteSoloist(f"ws://127.0.0.1:{soloist.puerto}", al_evento=lambda e: None,
                       al_desconectar=lambda: cortes.append(1), reintento_segundos=0.1)
    c.conectar(2)
    soloist.listo.wait(2)
    soloist.cortar()
    assert esperar(lambda: cortes == [1] and not c.conectado)
    soloist.comandos.clear()
    soloist.volver()
    assert esperar(lambda: c.conectado and {"type": "command", "command": "get_state"} in soloist.comandos, 5)
    assert cortes == [1]
    c.cerrar()


def test_sin_soloist_dice_donde_lo_busco():
    url = f"ws://127.0.0.1:{puerto_libre()}"
    c = ClienteSoloist(url, al_evento=lambda e: None)
    with pytest.raises(ErrorSpotify, match=url):
        c.conectar(0.5)
    with pytest.raises(ErrorSpotify):
        c.comando("pause")


def test_cerrar_termina_el_hilo(soloist):
    c = ClienteSoloist(f"ws://127.0.0.1:{soloist.puerto}", al_evento=lambda e: None, reintento_segundos=0.1)
    c.conectar(2)
    c.cerrar()
    assert esperar(lambda: not any(t.name == "soloist-ws" and t.is_alive() for t in threading.enumerate()))


def test_iniciar_conecta_en_segundo_plano_cuando_soloist_aparece():
    puerto = puerto_libre()
    c = ClienteSoloist(f"ws://127.0.0.1:{puerto}", al_evento=lambda e: None, reintento_segundos=0.1)
    c.iniciar()                      # Soloist todavía no está: no bloquea ni lanza
    assert not c.conectado
    s = SoloistFalso(puerto)
    assert esperar(lambda: c.conectado, 5)
    c.cerrar()
    s.servidor.shutdown()

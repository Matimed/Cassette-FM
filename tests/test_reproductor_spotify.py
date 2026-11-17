import json
import time as _time
from dataclasses import replace
from itertools import islice
from pathlib import Path

import pytest

from cassette_fm.agenda import EPOCA, con_pedido, desfase, secuencia, transiciones
from cassette_fm.biblioteca import Estacion, Pedido, Pista
from cassette_fm.reproductor_spotify import ReproductorSpotify
from cassette_fm.spotify.api import ErrorSpotify

T0 = EPOCA + 1_000_000.0


def pista(i, dur=200.0):
    return Pista(ruta=None, duracion=dur, titulo=f"A - T{i}", fuente="spotify", artista="A", cancion=f"T{i}",
                 uri=f"spotify:track:{i:022d}")


def estacion(nombre="Sing", n=5):
    return Estacion(nombre, tuple(pista(i, 180.0 + i) for i in range(n)), fuente="spotify")


class ControlFalso:
    def __init__(self, error=None):
        self.llamadas = []
        self.error = error
        self.antes = None          # lo que pasa antes del play (shuffle, repeat: tardan)

    def reproducir(self, uris, posicion_ms):
        if self.antes:
            self.antes()
        self.llamadas.append((list(uris), posicion_ms()))
        if self.error:
            raise self.error


class SoloistFalso:
    def __init__(self, conectado=True):
        self.conectado = conectado
        self.comandos = []

    def comando(self, nombre, **campos):
        if not self.conectado:
            raise ErrorSpotify("no conectado")
        self.comandos.append((nombre, campos))


class Temporizadores:
    def __init__(self):
        self.pendientes = []

    def __call__(self, segundos, funcion):
        t = type("T", (), {})()
        t.segundos, t.funcion, t.cancelado = segundos, funcion, False
        t.cancel = lambda: setattr(t, "cancelado", True)
        self.pendientes.append(t)
        return t

    def disparar(self):
        for t in list(self.pendientes):
            if not t.cancelado:
                t.funcion()


class Reloj:
    def __init__(self, t=T0):
        self.t = t

    def __call__(self):
        return self.t


def armar(control=None, soloist=None, reloj=None, uris=100):
    control, soloist, reloj = control or ControlFalso(), soloist or SoloistFalso(), reloj or Reloj()
    tempo = Temporizadores()
    r = ReproductorSpotify(control, soloist, reloj=reloj, uris_por_pedido=uris, espera_sonido_segundos=10.0,
                           temporizador=tempo, en_segundo_plano=lambda f: f())
    r.eventos = {"sonar": 0, "fallas": [], "cambios": [], "linea": [], "agendas": [], "encolados": [],
                 "desencolados": []}
    r.al_sonar = lambda: r.eventos.__setitem__("sonar", r.eventos["sonar"] + 1)
    r.al_fallar = lambda e, motivo=None: r.eventos["fallas"].append((e.nombre, motivo))

    def cambio_de_pista(p, e):
        r.eventos["cambios"].append((p.clave, e.nombre))
        r.eventos["linea"].append(("pista", p.clave, e))

    def cambio_de_agenda(e, nuevo):
        r.eventos["agendas"].append((e, nuevo))
        r.eventos["linea"].append(("agenda", e))
    r.al_cambiar_pista = cambio_de_pista
    r.al_cambiar_agenda = cambio_de_agenda
    r.al_encolado = lambda p, e, fin: r.eventos["encolados"].append((p, e.nombre, fin))
    r.al_desencolado = lambda clave: r.eventos["desencolados"].append(clave)
    return r, control, soloist, reloj, tempo


def cambio(uri, nombre="T", ms=200000):
    return {"type": "track_changed", "item": {"uri": uri, "decorations": {"identity": {"name": nombre},
                                                                          "playback": {"duration_ms": ms}}}}


SONANDO = {"type": "playback_changed", "status": "playing"}


def test_sintonizar_manda_la_agenda_desde_el_segundo_que_corresponde():
    r, control, _, reloj, _ = armar(uris=7)
    e = estacion()
    r.sintonizar(e)
    esperado = list(islice(secuencia(e, reloj()), 7))
    ((uris, pos),) = control.llamadas
    assert uris == [p.uri for p, _ in esperado] and pos == int(esperado[0][1] * 1000)


def test_suena_cuando_llega_el_tema_esperado_y_cancela_la_espera():
    r, control, _, _, tempo = armar()
    r.sintonizar(estacion())
    primero = control.llamadas[0][0][0]
    r.manejar_evento(cambio(primero))
    r.manejar_evento(SONANDO)
    assert r.eventos["sonar"] == 1 and tempo.pendientes[0].cancelado
    r.manejar_evento(SONANDO)
    assert r.eventos["sonar"] == 1


def test_si_no_suena_en_10_s_falla_con_motivo():
    r, _, _, _, tempo = armar()
    r.sintonizar(estacion())
    assert tempo.pendientes[0].segundos == 10.0
    tempo.disparar()
    assert r.eventos["fallas"] == [("Sing", "Spotify no empezó a sonar en 10 s")]


def test_un_error_de_spotify_al_dar_play_falla_con_el_mensaje():
    r, *_ = armar(control=ControlFalso(ErrorSpotify("no hay sesión de Spotify: corré cassette spotify login")))
    r.sintonizar(estacion())
    assert r.eventos["fallas"] == [("Sing", "no hay sesión de Spotify: corré cassette spotify login")]


def test_soloist_desconectado_falla_enseguida_y_sin_pedirle_nada_a_spotify():
    r, control, *_ = armar(soloist=SoloistFalso(conectado=False))
    r.sintonizar(estacion())
    assert control.llamadas == []
    ((nombre, motivo),) = r.eventos["fallas"]
    assert "Soloist" in motivo and "cassette-soloist" in motivo


def test_eventos_de_una_sintonia_vieja_no_cuentan():
    r, control, _, reloj, tempo = armar()
    r.sintonizar(estacion("A"))
    viejo = control.llamadas[0][0][0]
    reloj.t += 3
    r.sintonizar(estacion("B", n=6))
    nuevo = control.llamadas[1][0][0]
    if nuevo == viejo:
        pytest.skip("las dos sintonías empiezan por el mismo tema")
    r.manejar_evento(cambio(viejo))
    r.manejar_evento(SONANDO)
    assert r.eventos["sonar"] == 0
    tempo.pendientes[0].funcion()            # la espera de la sintonía vieja vence: no falla la nueva
    assert r.eventos["fallas"] == []
    r.manejar_evento(cambio(nuevo))
    r.manejar_evento(SONANDO)
    assert r.eventos["sonar"] == 1


def test_cambio_de_tema_avisa_con_la_pista_de_la_agenda_o_una_minima():
    r, control, *_ = armar()
    e = estacion()
    r.sintonizar(e)
    primero = control.llamadas[0][0][0]
    r.manejar_evento(cambio(primero))
    assert r.pista_actual in e.pistas and r.eventos["cambios"] == [(primero, "Sing")]
    r.manejar_evento(cambio("spotify:track:ajeno0000000000000000", "Encolado", 123000))
    assert r.pista_actual.clave == "spotify:track:ajeno0000000000000000" and r.pista_actual.titulo == "Encolado"
    assert r.pista_actual.duracion == 123.0


def test_posicion_interpola_el_position_sync():
    r, control, _, reloj, _ = armar()
    r.sintonizar(estacion())
    r.manejar_evento(cambio(control.llamadas[0][0][0]))
    assert r.posicion() is None
    r.manejar_evento({"type": "position_sync", "position": {"position_ms": 30000, "timestamp_ms": int(reloj.t * 1000),
                                                            "speed": 1}})
    reloj.t += 2.5
    assert r.posicion() == pytest.approx(32.5)


def test_detener_pausa_y_despues_ignora_los_eventos():
    r, control, soloist, _, _ = armar()
    r.sintonizar(estacion())
    r.detener()
    assert ("pause", {}) in soloist.comandos and r.pista_actual is None
    r.manejar_evento(cambio(control.llamadas[0][0][0]))
    r.manejar_evento(SONANDO)
    assert r.eventos["cambios"] == [] and r.eventos["sonar"] == 0


def test_si_se_corta_soloist_y_no_vuelve_falla():
    r, control, soloist, _, tempo = armar()
    r.sintonizar(estacion())
    r.manejar_evento(cambio(control.llamadas[0][0][0]))
    r.manejar_evento(SONANDO)
    soloist.conectado = False
    r.soloist_desconectado()
    tempo.disparar()
    assert r.eventos["fallas"] == [("Sing", "se perdió la conexión con Soloist")]


def test_si_se_corta_soloist_y_vuelve_sigue():
    r, control, soloist, _, tempo = armar()
    r.sintonizar(estacion())
    r.manejar_evento(cambio(control.llamadas[0][0][0]))
    r.manejar_evento(SONANDO)
    soloist.conectado = False
    r.soloist_desconectado()
    soloist.conectado = True
    tempo.disparar()
    assert r.eventos["fallas"] == []


# --- volumen, rampas, desfase y control de la cuenta (tarea 5) ---

def armar_vol(ajuste_db=0.0, **kw):
    subidas = []
    r, control, soloist, reloj, tempo = armar(**kw)
    r._ganancia = 10 ** (ajuste_db / 60)
    r._subir_stream = subidas.append
    r.sintonizar(estacion())
    soloist.comandos.clear()
    return r, soloist, subidas


def volumenes(soloist):
    return [c["volume"] for n, c in soloist.comandos if n == "set_volume"]


def test_volumen_y_atenuar_sin_rampa():
    r, soloist, _ = armar_vol()
    r.volumen(80)
    r.atenuar(0.6)
    assert volumenes(soloist) == [80, 48]


def test_el_ajuste_en_db_sigue_la_curva_cubica():
    r, soloist, _ = armar_vol(ajuste_db=6)
    r.volumen(50)
    assert volumenes(soloist) == [63]


def test_pasarse_de_100_sube_el_stream_de_pipewire_y_despues_lo_vuelve_a_100():
    r, soloist, subidas = armar_vol(ajuste_db=6)
    r.volumen(90)
    assert volumenes(soloist) == [100] and subidas == [113]
    r.volumen(50)
    assert volumenes(soloist)[-1] == 63 and subidas == [113, 100]
    r.volumen(40)
    assert subidas == [113, 100]               # ya estaba en 100: no se repite


def test_rampa_llega_al_destino_pasando_por_el_medio():
    r, soloist, _ = armar_vol()
    r.volumen(80)
    r.atenuar(0.5, 0.3)
    _time.sleep(0.6)
    v = volumenes(soloist)
    assert v[-1] == 40 and any(40 < x < 80 for x in v)


def test_una_rampa_nueva_reemplaza_a_la_anterior():
    r, soloist, _ = armar_vol()
    r.volumen(80)
    r.atenuar(0.5, 1.0)
    _time.sleep(0.2)
    r.atenuar(1.0, 0.2)
    _time.sleep(1.2)
    assert volumenes(soloist)[-1] == 80


def proximo(e, t):
    return next(transiciones(e, t))


def sonando(r, control):
    r.manejar_evento(cambio(control.llamadas[-1][0][0]))
    r.manejar_evento(SONANDO)


def test_la_posicion_del_play_cuenta_lo_que_tardaron_las_ordenes_previas():
    r, control, _, reloj, _ = armar()
    e = estacion()
    _, segundo = next(secuencia(e, reloj()))
    control.antes = lambda: setattr(reloj, "t", reloj.t + 2.5)
    r.sintonizar(e)
    assert control.llamadas[0][1] == pytest.approx((segundo + 2.5) * 1000, abs=1)


def test_la_posicion_del_play_no_pasa_el_final_del_tema():
    r, control, _, reloj, _ = armar()
    e = estacion()
    primero, fin = proximo(e, reloj())
    actual, _ = next(secuencia(e, reloj()))
    control.antes = lambda: setattr(reloj, "t", fin + 5)      # tardó más que lo que le quedaba al tema
    r.sintonizar(e)
    assert control.llamadas[0][1] < actual.duracion * 1000


APAGAR = [("set_shuffle", {"enabled": False}), ("set_repeat_context", {"enabled": False}),
          ("set_repeat_track", {"enabled": False})]


def _ordenes(soloist):
    return [c for c in soloist.comandos if c[0] not in ("set_volume", "play", "seek")]    # play/seek: la sintonía local


def test_sintonizar_apaga_shuffle_y_repeat_en_soloist_antes_del_play():
    r, control, soloist, _, _ = armar()
    control.antes = lambda: soloist.comandos.append(("PLAY", {}))
    r.sintonizar(estacion())
    assert _ordenes(soloist) == APAGAR + [("PLAY", {})]


def test_un_error_de_soloist_queda_en_el_log(caplog):
    r, _, _, _, _ = armar()
    r.sintonizar(estacion())
    with caplog.at_level("WARNING", logger="cassette_fm"):
        r.manejar_evento({"type": "error", "message": "unknown command: set_shuffle"})
    assert "Soloist rechazó una orden: unknown command: set_shuffle" in caplog.text


def test_resintonizar_tambien_apaga_shuffle_y_repeat():
    r, control, soloist, reloj, _ = armar()
    control.antes = lambda: soloist.comandos.append(("PLAY", {}))
    e = estacion()
    r.sintonizar(e)
    sonando(r, control)
    pista, inicio = proximo(e, reloj())
    reloj.t = inicio + 5.0                                 # desfase grande: re-sintoniza
    r.manejar_evento(cambio(pista.uri))
    assert _ordenes(soloist) == (APAGAR + [("PLAY", {})]) * 2


def test_desfase_grande_resintoniza_en_el_borde_y_chico_no():
    for atraso, resintoniza in ((5.0, True), (2.0, False)):
        r, control, _, reloj, _ = armar()
        e = estacion()
        r.sintonizar(e)
        sonando(r, control)
        pista, inicio = proximo(e, reloj())
        reloj.t = inicio + atraso
        r.manejar_evento(cambio(pista.uri))
        assert (len(control.llamadas) == 2) is resintoniza
        assert r.eventos["sonar"] == 1           # sin estática ni al_sonar de nuevo


def test_un_tema_ajeno_no_resintoniza_y_al_volver_la_agenda_si():
    r, control, _, reloj, _ = armar()
    e = estacion()
    r.sintonizar(e)
    sonando(r, control)
    reloj.t += 400
    r.manejar_evento(cambio("spotify:track:ajeno0000000000000000", "Encolado"))
    assert len(control.llamadas) == 1
    pista, _ = proximo(e, reloj())
    r.manejar_evento(cambio(pista.uri))
    assert len(control.llamadas) == 2


def test_se_vuelve_a_mandar_la_lista_antes_de_que_se_acabe():
    r, control, _, reloj, _ = armar(uris=12)
    e = estacion()
    r.sintonizar(e)
    sonando(r, control)                       # 1.º de 12: quedan 11 por delante
    pista, inicio = proximo(e, reloj())
    reloj.t = inicio + 0.1
    r.manejar_evento(cambio(pista.uri))       # 2.º: quedan 10
    assert len(control.llamadas) == 1
    pista, inicio = proximo(e, reloj())
    reloj.t = inicio + 0.1
    r.manejar_evento(cambio(pista.uri))       # 3.º: quedan 9 → se manda la lista de nuevo
    assert len(control.llamadas) == 2


def test_otro_dispositivo_toma_spotify():
    r, control, *_ = armar()
    r.sintonizar(estacion())
    r.manejar_evento({"type": "device_changed", "is_active": False, "device_name": "cassette-fm"})
    assert r.eventos["fallas"] == []            # todavía no había tomado el control
    r.manejar_evento({"type": "device_changed", "is_active": True, "device_name": "cassette-fm"})
    sonando(r, control)
    r.manejar_evento({"type": "device_changed", "is_active": False, "device_name": "cassette-fm"})
    assert r.eventos["fallas"] == [("Sing", "Spotify se está escuchando en otro dispositivo")]


def test_despues_de_detener_perder_el_control_no_falla():
    r, control, *_ = armar()
    r.sintonizar(estacion())
    r.manejar_evento({"type": "device_changed", "is_active": True, "device_name": "cassette-fm"})
    r.detener()
    r.manejar_evento({"type": "device_changed", "is_active": False, "device_name": "cassette-fm"})
    assert r.eventos["fallas"] == []


def test_la_resintonia_no_avisa_dos_veces_el_mismo_tema():
    r, control, _, reloj, _ = armar()
    e = estacion()
    r.sintonizar(e)
    sonando(r, control)
    pista, inicio = proximo(e, reloj())
    reloj.t = inicio + 5
    r.manejar_evento(cambio(pista.uri))           # desfase de 5 s → se re-sintoniza
    assert len(control.llamadas) == 2
    r.manejar_evento(cambio(control.llamadas[-1][0][0]))   # Spotify vuelve a empezar ese mismo tema
    assert [c for c, _ in r.eventos["cambios"]].count(pista.uri) == 1


# --- arreglos de la revisión final ---

class Diferido:
    """`en_segundo_plano` que guarda la orden para correrla cuando el test quiera (la orden "en vuelo")."""
    def __init__(self):
        self.pendientes = []

    def __call__(self, f):
        self.pendientes.append(f)

    def correr(self):
        while self.pendientes:
            self.pendientes.pop(0)()


def armar_diferido(control=None):
    diferido = Diferido()
    control, soloist, reloj = control or ControlFalso(), SoloistFalso(), Reloj()
    r = ReproductorSpotify(control, soloist, reloj=reloj, uris_por_pedido=20, temporizador=Temporizadores(),
                           en_segundo_plano=diferido)
    r.al_sonar = r.al_fallar = r.al_cambiar_pista = lambda *a, **k: None
    return r, control, soloist, reloj, diferido


def test_una_orden_vieja_que_no_salio_no_se_manda():
    r, control, soloist, _, diferido = armar_diferido()
    r.sintonizar(estacion())
    r.detener()
    diferido.correr()
    assert control.llamadas == []


def test_una_orden_en_vuelo_que_termina_despues_de_detener_se_pausa():
    class ControlLento(ControlFalso):
        def reproducir(self, uris, posicion_ms):
            super().reproducir(uris, posicion_ms)
            self.durante()                       # el usuario cambió de emisora mientras viajaba el play…
            self.soloist.comandos.append(("play", {}))   # …y el play le llega a Soloist después de la pausa
    control = ControlLento()
    r, _, soloist, _, diferido = armar_diferido(control)
    control.durante, control.soloist = r.detener, soloist
    r.sintonizar(estacion())
    diferido.correr()
    assert soloist.comandos[-1] == ("pause", {})


def test_las_ordenes_no_se_cruzan_entre_sintonias():
    r, control, _, reloj, diferido = armar_diferido()
    r.sintonizar(estacion("A"))
    reloj.t += 30
    r.sintonizar(estacion("B", n=6))
    diferido.correr()                            # la de A ya es vieja: solo sale la de B
    assert len(control.llamadas) == 1


def test_mientras_arranca_un_tema_ajeno_no_cuenta():
    r, control, *_ = armar()
    r.sintonizar(estacion())
    r.manejar_evento(cambio("spotify:track:ultimo00000000000000", "Lo que sonaba antes en la cuenta"))
    assert r.eventos["cambios"] == [] and r.pista_actual is None
    r.manejar_evento(cambio(control.llamadas[0][0][0]))
    assert len(r.eventos["cambios"]) == 1


def test_si_soloist_se_reinicia_se_vuelve_a_sintonizar():
    r, control, soloist, _, tempo = armar()
    r.sintonizar(estacion())
    sonando(r, control)
    soloist.conectado = False
    r.soloist_desconectado()
    soloist.conectado = True
    r.soloist_reconectado()
    tempo.disparar()
    assert len(control.llamadas) == 2 and r.eventos["fallas"] == []


def test_sin_emisora_el_volumen_no_se_le_manda_a_soloist():
    r, control, soloist, *_ = armar()
    r.volumen(50)
    assert soloist.comandos == []
    r.sintonizar(estacion())
    assert ("set_volume", {"volume": 50}) in soloist.comandos


def test_si_otro_dispositivo_tomo_spotify_no_se_le_manda_pausa():
    r, control, soloist, *_ = armar()
    r.sintonizar(estacion())
    r.manejar_evento({"type": "device_changed", "is_active": True})
    sonando(r, control)
    r.manejar_evento({"type": "device_changed", "is_active": False})
    soloist.comandos.clear()
    r.detener()
    assert ("pause", {}) not in soloist.comandos


def test_soloist_caido_dice_tambien_que_puede_haber_vencido():
    r, *_ = armar(soloist=SoloistFalso(conectado=False))
    r.sintonizar(estacion())
    assert "cassette spotify estado" in r.eventos["fallas"][0][1]


# --- peticiones por la cola de la app (etapa 7a) ---

def _items_capturados() -> dict:
    """Los ítems tal como los manda Soloist (captura real de `scripts/capturar-cola-soloist.py`)."""
    items = {}
    for linea in (Path(__file__).parent / "spotify" / "eventos_cola.jsonl").read_text(encoding="utf-8").splitlines():
        for u in json.loads(linea)["evento"].get("upcoming", []):
            items[u["item"]["uri"]] = u["item"]
    return items


CAPTURADOS = _items_capturados()
PARA_NO_OLVIDAR = "spotify:track:1ZGs4W7LBJy68hRPTsvMFc"
EL_OLVIDAU = "spotify:track:3sGZPPoTkKOKEHWrstBjcJ"
AJENO = "spotify:track:pedido000000000000001"
OTRO = "spotify:track:pedido000000000000002"


def cola(*items):
    """`queue_changed` como el de Soloist: lo encolado (`source == "queue"`) primero y después la playlist."""
    return {"type": "queue_changed", "upcoming": [{"source": "queue", "item": i} for i in items]
            + [{"source": "context", "item": CAPTURADOS[EL_OLVIDAU]}]}


def item(uri, nombre="Encolado", ms=150000):
    return {"uri": uri, "entity_type": "track",
            "decorations": {"identity": {"name": nombre}, "playback": {"duration_ms": ms}}}


def de_la_agenda(p):
    return item(p.uri, p.cancion, int(p.duracion * 1000))


def posicion_en(reloj, segundos):
    return {"type": "position_sync", "position": {"position_ms": int(segundos * 1000),
                                                  "timestamp_ms": int(reloj() * 1000), "speed": 1}}


def en_marcha():
    """Una emisora sonando su primer tema, con la posición conocida."""
    r, control, _, reloj, _ = armar()
    e = estacion()
    r.sintonizar(e)
    sonando(r, control)
    r.manejar_evento(posicion_en(reloj, control.llamadas[0][1] / 1000))
    return r, control, reloj, e


def test_sintonizar_el_tema_que_ya_estaba_sonando_lo_toma_sin_track_changed():
    r, control, _, reloj, _ = armar()
    e = estacion()
    r.sintonizar(e)
    uri, posicion_ms = control.llamadas[0][0][0], control.llamadas[0][1]
    # Spotify ya estaba en ese tema (p. ej. se reinició la radio): salta a la posición sin avisar un cambio
    r.manejar_evento({"type": "playback_state", "status": "playing", "item": {"uri": uri}})
    r.manejar_evento(posicion_en(reloj, posicion_ms / 1000))
    assert r.pista_actual is not None and r.pista_actual.uri == uri
    assert r.eventos["linea"][-1][:2] == ("pista", uri)
    _, fin = proximo(e, reloj())
    r.manejar_evento(cola(item(AJENO)))
    ((p, _, fin_actual),) = r.eventos["encolados"]
    assert p.uri == AJENO and fin_actual == pytest.approx(fin)
    r.manejar_evento(cambio(uri))                          # si igual llegara el aviso, no cambia nada
    assert [x[0] for x in r.eventos["linea"]].count("pista") == 1 and len(control.llamadas) == 1


def test_reiniciar_a_mitad_del_pedido_que_ya_estaba_sonando_lo_retoma():
    r, control, _, reloj, _ = armar()
    e = estacion()
    pedido = Pista(None, 150.0, "Encolado", fuente="spotify", cancion="Encolado", uri=AJENO)
    borde = proximo(e, reloj())[1]
    e = con_pedido(e, pedido, borde)                       # los pedidos empiezan en un borde de tema
    reloj.t = borde + 40
    r.sintonizar(e)
    assert control.llamadas[0][0][0] == AJENO
    r.manejar_evento({"type": "playback_state", "status": "playing", "item": {"uri": AJENO}})
    assert r.pista_actual == pedido and r._estacion.pedidos == e.pedidos
    reloj.t += 110                                         # termina el pedido y sigue la agenda, sin re-sintonía
    r.manejar_evento(cambio(control.llamadas[0][0][1]))
    assert len(control.llamadas) == 1


def test_encolar_avisa_con_metadata_y_fin_del_tema_actual():
    r, _, reloj, e = en_marcha()
    _, fin = proximo(e, reloj())
    reloj.t += 20
    r.manejar_evento(cola(CAPTURADOS[PARA_NO_OLVIDAR]))
    ((p, nombre, fin_actual),) = r.eventos["encolados"]
    assert (p.uri, p.cancion, p.artista, p.album, p.duracion) == (
        PARA_NO_OLVIDAR, "Para no olvidar", "Los Rodriguez", "Palabras más, palabras menos", 235.0)
    assert p.titulo == "Los Rodriguez - Para no olvidar" and nombre == "Sing"
    assert fin_actual == pytest.approx(fin)
    r.manejar_evento(cola(CAPTURADOS[PARA_NO_OLVIDAR]))      # Soloist repite la cola: no se avisa de nuevo
    assert len(r.eventos["encolados"]) == 1


TRANSITORIA = {"type": "queue_changed", "upcoming": [{"source": "context",
                                                      "item": {"uri": "spotify:meta:node_rules_placeholder"}}]}


def test_sacar_de_la_cola_el_encolado_avisado_lo_desencola():
    r, _, _, _ = en_marcha()
    r.manejar_evento(cola(item(AJENO)))
    assert len(r.eventos["encolados"]) == 1
    r.manejar_evento(cola())
    assert r.eventos["desencolados"] == [AJENO]


def test_la_cola_transitoria_de_soloist_no_desencola_ni_olvida_la_cola():
    r, control, reloj, e = en_marcha()
    _, fin = proximo(e, reloj())
    r.manejar_evento(cola(item(AJENO)))
    r.manejar_evento(TRANSITORIA)                          # Soloist la manda al agregar otro tema a la cola
    assert r.eventos["desencolados"] == []
    reloj.t = fin
    r.manejar_evento(cambio(AJENO, "Encolado", 150000))
    assert r.eventos["agendas"][-1][1].pista.uri == AJENO and len(control.llamadas) == 1


def test_el_pedido_que_empieza_no_cuenta_como_desencolado():
    r, _, reloj, e = en_marcha()
    _, fin = proximo(e, reloj())
    r.manejar_evento(cola(item(AJENO)))
    reloj.t = fin
    r.manejar_evento(cambio(AJENO, "Encolado", 150000))
    r.manejar_evento(cola())                               # Soloist lo saca de la cola porque empezó
    assert r.eventos["desencolados"] == []


def test_item_sin_nombre_es_pedido_sin_cancion():
    r, _, reloj, e = en_marcha()
    _, fin = proximo(e, reloj())
    sin_nombre = {"uri": AJENO, "decorations": {
        "creators": [{"entity": {"decorations": {"identity": {"name": "Artista"}}}}],
        "playback": {"duration_ms": 150000}}}
    r.manejar_evento(cola(sin_nombre))
    reloj.t = fin
    r.manejar_evento(cambio(AJENO))
    pedido = r.eventos["agendas"][-1][1]
    assert pedido.pista.cancion is None and pedido.pista.titulo == "Artista"


# --- temas que Soloist saltea o cambia por otra versión ---

def _x_y_z(e, reloj):
    x, borde = proximo(e, reloj())
    y, despues = next(transiciones(e, borde + 0.001))
    z, _ = next(transiciones(e, despues + 0.001))
    return borde, x, y, z


def test_soloist_saltea_el_tema_y_la_radio_sigue_con_el_siguiente():
    r, control, reloj, e = en_marcha()
    borde, x, y, _ = _x_y_z(e, reloj)
    reloj.t = borde
    r.manejar_evento(cambio(x.uri))
    reloj.t = borde + 0.5                                  # Soloist no pudo cargar x y pasó al siguiente
    r.manejar_evento(cambio(y.uri))
    assert len(control.llamadas) == 1
    nueva, nuevo = r.eventos["agendas"][-1]
    assert nuevo is None and desfase(nueva, y, reloj()) == pytest.approx(0, abs=0.01)


def test_varios_salteos_seguidos_terminan_en_lo_ultimo_que_suena():
    r, control, reloj, e = en_marcha()
    borde, x, y, z = _x_y_z(e, reloj)
    for i, p in enumerate((x, y, z)):
        reloj.t = borde + 0.7 * i
        r.manejar_evento(cambio(p.uri))
    assert len(control.llamadas) == 1
    assert desfase(r.eventos["agendas"][-1][0], z, reloj()) == pytest.approx(0, abs=0.01)


def test_un_salto_lento_a_un_tema_adelantado_resintoniza():
    r, control, reloj, e = en_marcha()
    borde, x, y, _ = _x_y_z(e, reloj)
    reloj.t = borde
    r.manejar_evento(cambio(x.uri))
    reloj.t = borde + 10
    r.manejar_evento(cambio(y.uri))
    assert len(control.llamadas) == 2


def test_un_cambio_rapido_con_un_pedido_en_curso_lo_pliega():
    r, control, reloj, e = en_marcha()
    x, borde = proximo(e, reloj())
    r.manejar_evento(cola(item(AJENO)))
    reloj.t = borde
    r.manejar_evento(cambio(AJENO, "Encolado", 150000))
    reloj.t = borde + 0.5                                  # el pedido se corta enseguida y vuelve la agenda
    r.manejar_evento(cambio(x.uri))
    nueva, nuevo = r.eventos["agendas"][-1]
    assert nueva.pedidos == () and nuevo is None and r.pista_actual == x


def test_un_cambio_rapido_tras_una_resintonia_no_es_salteo():
    r, control, reloj, e = en_marcha()
    borde, x, y, z = _x_y_z(e, reloj)
    reloj.t = borde
    r.manejar_evento(cambio(x.uri))
    reloj.t = borde + 10
    r.manejar_evento(cambio(y.uri))                        # salto lento: re-sintoniza
    assert len(control.llamadas) == 2
    reloj.t += 0.5
    r.manejar_evento(cambio(z.uri))                        # lo primero tras la re-sintonía no corre la agenda
    assert r.eventos["agendas"] == []


def test_otra_version_del_tema_esperado_cuenta_como_ese():
    r, control, _, _, _ = armar()
    e = estacion()
    r.sintonizar(e)
    esperado = next(p for p in e.pistas if p.uri == control.llamadas[0][0][0])
    r.manejar_evento(cambio("spotify:track:otraversion00000000001", f"{esperado.cancion} - From Some Soundtrack"))
    assert r.pista_actual == esperado and r.eventos["linea"][-1][:2] == ("pista", esperado.uri)


def test_el_aviso_doble_de_un_pedido_no_lo_toma_por_otra_version():
    r, control, reloj, e = en_marcha()
    x, borde = proximo(e, reloj())
    vivo = f"{x.cancion} (live)"                           # el pedido se llama como el tema que sigue en la agenda
    r.manejar_evento(cola(item(AJENO, vivo)))
    reloj.t = borde
    r.manejar_evento(cambio(AJENO, vivo, 150000))
    ((_, pedido),) = r.eventos["agendas"]
    reloj.t += 0.3
    r.manejar_evento(cambio(AJENO, vivo, 150000))          # Soloist avisa otra vez el mismo comienzo
    assert r._estacion.pedidos == (pedido,) and r.pista_actual.uri == AJENO


def test_otra_version_que_ya_sonaba_al_sintonizar_corta_la_estatica():
    r, control, _, _, _ = armar()
    e = estacion()
    r.sintonizar(e)
    esperado = next(p for p in e.pistas if p.uri == control.llamadas[0][0][0])
    # se reinició la radio con Soloist en otra versión del tema: no hay track_changed, solo el estado
    version = item("spotify:track:otraversion00000000001", f"{esperado.cancion} - 2011 Remaster")
    r.manejar_evento({"type": "playback_state", "status": "playing", "item": version})
    assert r.eventos["sonar"] == 1 and r.pista_actual == esperado


def test_otro_tema_que_ya_sonaba_al_sintonizar_no_corta_la_estatica():
    r, *_ = armar()
    r.sintonizar(estacion())
    r.manejar_evento({"type": "playback_state", "status": "playing",
                      "item": item("spotify:track:otraversion00000000001", "Love")})
    assert r.eventos["sonar"] == 0 and r.pista_actual is None


@pytest.mark.parametrize("nombre,es_version", [(" (Remastered)", True), (" - From Some Soundtrack", True),
                                               ("0 otra canción", False), ("away", False)])
def test_otra_version_exige_el_nombre_entero(nombre, es_version):
    r, control, _, _, _ = armar()
    e = estacion()
    r.sintonizar(e)
    esperado = next(p for p in e.pistas if p.uri == control.llamadas[0][0][0])
    r.manejar_evento(cambio("spotify:track:otraversion00000000001", esperado.cancion + nombre))
    assert (r.pista_actual == esperado) is es_version


def test_un_tema_desconocido_con_otro_nombre_no_se_confunde():
    r, control, _, _, _ = armar()
    r.sintonizar(estacion())
    sonando(r, control)
    r.manejar_evento(cambio("spotify:track:otraversion00000000001", "Love"))
    assert r.pista_actual.uri == "spotify:track:otraversion00000000001"


def test_tema_encolado_que_empieza_es_un_pedido_sin_resintonia():
    r, control, reloj, e = en_marcha()
    _, fin = proximo(e, reloj())
    r.manejar_evento(cola(item(AJENO)))
    reloj.t = fin
    r.manejar_evento(cambio(AJENO, "Encolado", 150000))
    ((nueva, pedido),) = r.eventos["agendas"]
    assert pedido.inicio == fin and pedido.pista.uri == AJENO and nueva.pedidos == (pedido,)
    assert [x[0] for x in r.eventos["linea"][-2:]] == ["agenda", "pista"]   # la radio ya tiene la agenda nueva
    assert r.eventos["linea"][-1][2] == nueva
    assert len(control.llamadas) == 1 and r.pista_actual.uri == AJENO


def test_encolado_que_es_de_la_playlist_igual_es_pedido():
    r, control, reloj, e = en_marcha()
    siguiente, fin = proximo(e, reloj())
    r.manejar_evento(cola(de_la_agenda(siguiente)))
    reloj.t = fin
    r.manejar_evento(cambio(siguiente.uri))
    ((_, pedido),) = r.eventos["agendas"]
    assert pedido == Pedido(siguiente, fin) and len(control.llamadas) == 1
    r.manejar_evento(cola())                               # Soloist lo saca de la cola
    reloj.t = fin + siguiente.duracion - 0.5               # el mismo tema, ahora de la agenda (y un poco antes)
    r.manejar_evento(cambio(siguiente.uri))
    nueva, nuevo = r.eventos["agendas"][-1]
    assert nuevo is None and nueva.pedidos == () and nueva.corrimiento == pytest.approx(siguiente.duracion - 0.5)
    assert len(control.llamadas) == 1


def test_el_comienzo_del_pedido_avisado_dos_veces_no_lo_pliega():
    r, control, reloj, e = en_marcha()
    siguiente, fin = proximo(e, reloj())
    r.manejar_evento(cola(de_la_agenda(siguiente)))
    reloj.t = fin + 4.3                                    # Spotify viene atrasado respecto del reloj
    r.manejar_evento(cambio(siguiente.uri))
    reloj.t += 0.018                                       # Soloist avisó el mismo comienzo otra vez
    r.manejar_evento(cambio(siguiente.uri))
    ((nueva, pedido),) = r.eventos["agendas"]
    assert pedido == Pedido(siguiente, fin + 4.3) and r._estacion.pedidos == (pedido,)
    assert len(control.llamadas) == 1 and [x[0] for x in r.eventos["linea"]].count("pista") == 2


def test_tema_de_la_agenda_tras_el_pedido_pliega_y_no_resintoniza():
    r, control, reloj, e = en_marcha()
    siguiente, fin = proximo(e, reloj())
    r.manejar_evento(cola(item(AJENO)))
    reloj.t = fin
    r.manejar_evento(cambio(AJENO, "Encolado", 150000))
    r.manejar_evento(cola())
    reloj.t = fin + 150
    r.manejar_evento(cambio(siguiente.uri))
    nueva, nuevo = r.eventos["agendas"][-1]
    assert nuevo is None and nueva.pedidos == () and nueva.corrimiento == pytest.approx(150)
    assert r.eventos["linea"][-1] == ("pista", siguiente.uri, nueva)
    assert len(control.llamadas) == 1


def test_pedido_salteado_pliega_lo_que_sono():
    r, control, reloj, e = en_marcha()
    siguiente, fin = proximo(e, reloj())
    r.manejar_evento(cola(item(AJENO)))
    reloj.t = fin
    r.manejar_evento(cambio(AJENO, "Encolado", 150000))
    r.manejar_evento(cola())
    reloj.t = fin + 8                                      # lo saltearon desde la app
    r.manejar_evento(cambio(siguiente.uri))
    assert r.eventos["agendas"][-1][0].corrimiento == pytest.approx(8)
    assert len(control.llamadas) == 1


def test_dos_pedidos_seguidos():
    r, control, reloj, e = en_marcha()
    siguiente, fin = proximo(e, reloj())
    r.manejar_evento(cola(item(AJENO, "Uno"), item(OTRO, "Dos", 100000)))
    reloj.t = fin
    r.manejar_evento(cambio(AJENO, "Uno", 150000))      # el orden de la captura: track_changed, queue_changed
    r.manejar_evento(cola(item(OTRO, "Dos", 100000)))   # y recién después la posición
    r.manejar_evento(posicion_en(reloj, 0))
    assert [p.uri for p, _, _ in r.eventos["encolados"]] == [AJENO, OTRO]
    assert [f for _, _, f in r.eventos["encolados"]] == [pytest.approx(fin), pytest.approx(fin + 150)]
    reloj.t = fin + 5                                      # salteó el primero
    r.manejar_evento(cambio(OTRO, "Dos", 100000))
    r.manejar_evento(cola())
    nueva, pedido = r.eventos["agendas"][-1]
    assert pedido.pista.uri == OTRO and nueva.pedidos == (pedido,) and nueva.corrimiento == pytest.approx(5)
    reloj.t = fin + 105
    r.manejar_evento(cambio(siguiente.uri))
    assert r.eventos["agendas"][-1][0].corrimiento == pytest.approx(105)
    assert len(control.llamadas) == 1


def test_volver_a_mitad_del_pedido_no_es_pedido_nuevo():
    r, control, _, reloj, _ = armar()
    pedida = Pista(None, 150.0, "Encolado", fuente="spotify", cancion="Encolado", uri=AJENO)
    _, borde = proximo(estacion(), reloj())                # los pedidos empiezan en un borde de tema
    e = replace(estacion(), pedidos=(Pedido(pedida, borde),))
    reloj.t = borde + 40
    r.manejar_evento(cola(item(AJENO)))                    # aunque Spotify lo siga teniendo en la cola
    r.sintonizar(e)
    assert control.llamadas[0][0][0] == AJENO and control.llamadas[0][1] == 40000
    r.manejar_evento(cambio(AJENO, "Encolado", 150000))
    r.manejar_evento(SONANDO)
    assert r.eventos["agendas"] == [] and r.eventos["cambios"] == [(AJENO, "Sing")]
    siguiente, fin = proximo(e, reloj())
    reloj.t = fin
    r.manejar_evento(cambio(siguiente.uri))
    nueva, nuevo = r.eventos["agendas"][-1]
    assert nuevo is None and nueva.pedidos == () and nueva.corrimiento == pytest.approx(150)
    assert len(control.llamadas) == 1


def test_tema_ajeno_que_no_vino_de_la_cola_no_toca_la_agenda():
    r, control, reloj, e = en_marcha()
    _, fin = proximo(e, reloj())
    reloj.t = fin
    r.manejar_evento(cambio(AJENO, "Ajeno", 150000))
    assert r.eventos["agendas"] == [] and r.pista_actual.uri == AJENO


def test_encolado_sin_duracion_no_es_pedido():
    r, control, reloj, e = en_marcha()
    _, fin = proximo(e, reloj())
    r.manejar_evento(cola({"uri": AJENO, "decorations": {"identity": {"name": "Raro"}}}))
    reloj.t = fin
    r.manejar_evento(cambio(AJENO, "Raro", 0))
    assert r.eventos["encolados"] == [] and r.eventos["agendas"] == []


def test_lo_encolado_mientras_no_suena_spotify_cuenta_al_volver():
    r, control, _, reloj, _ = armar()
    r.manejar_evento(cola(item(AJENO)))                    # la radio estaba en una emisora local
    e = estacion()
    r.sintonizar(e)
    sonando(r, control)
    _, fin = proximo(e, reloj())
    reloj.t = fin
    r.manejar_evento(cambio(AJENO, "Encolado", 150000))
    assert r.eventos["agendas"][0][1].pista.uri == AJENO


def test_actualizar_toma_las_pistas_nuevas_y_conserva_la_agenda_del_reproductor():
    r, control, _, reloj, _ = armar()
    r.sintonizar(replace(estacion(), corrimiento=50.0))
    sonando(r, control)
    r.actualizar(estacion(n=6))                                # el rescan trajo un tema más
    r.actualizar(estacion("Otra", n=7))                        # no es la que suena: no cambia nada
    r.soloist_reconectado()                                    # vuelve a mandar la agenda desde ahora
    esperado = list(islice(secuencia(replace(estacion(n=6), corrimiento=50.0), reloj()), 100))
    assert control.llamadas[-1] == ([p.uri for p, _ in esperado], int(esperado[0][1] * 1000))


# --- sintonía instantánea: el primer tema por Soloist, la lista por la Web API ---

def _primero(e, reloj):
    return next(iter(islice(secuencia(e, reloj()), 1)))[0].uri


def _seeks(soloist):
    return [c["position_ms"] for nombre, c in soloist.comandos if nombre == "seek"]


def test_sintonizar_suena_primero_por_soloist():
    r, control, soloist, reloj, _ = armar()
    e = estacion()
    al_play_de_la_api = []
    control.antes = lambda: al_play_de_la_api.extend(soloist.comandos)
    r.sintonizar(e)
    assert ("play", {"uri": _primero(e, reloj)}) in al_play_de_la_api


def test_al_cargar_el_tema_local_salta_a_la_posicion():
    r, control, soloist, reloj, _ = armar()
    r.sintonizar(estacion())
    (uris, pos), = control.llamadas
    reloj.t += 0.3
    r.manejar_evento(cambio(uris[0]))
    (seek,) = _seeks(soloist)
    assert abs(seek - (pos + 300)) <= 1          # ms enteros: el redondeo puede comerse uno
    r.manejar_evento(cambio(uris[0]))           # un segundo aviso del mismo comienzo no vuelve a saltar
    assert len(_seeks(soloist)) == 1


def test_track_changed_de_otro_tema_no_salta():
    r, _, soloist, _, _ = armar()
    r.sintonizar(estacion())
    r.manejar_evento(cambio("spotify:track:lo_que_sonaba_antes"))
    assert _seeks(soloist) == []


def test_spotify_lento_corrige_la_posicion_al_volver():
    r, control, soloist, reloj, _ = armar()
    control.antes = lambda: setattr(reloj, "t", reloj.t + 3)
    r.sintonizar(estacion())
    (_, pos), = control.llamadas
    assert _seeks(soloist) == [pos]              # la posición de cuando volvió la Web API


def test_spotify_rapido_no_agrega_otro_seek():
    r, control, soloist, reloj, _ = armar()
    e = estacion()
    primero = _primero(e, reloj)

    def carga_y_vuelve():
        reloj.t += 0.2
        r.manejar_evento(cambio(primero))
    control.antes = carga_y_vuelve
    r.sintonizar(e)
    assert len(_seeks(soloist)) == 1


def test_una_sintonia_nueva_anula_el_seek_de_la_vieja():
    r, control, soloist, reloj, diferido = armar_diferido()
    a = estacion("A")
    primero_a = _primero(a, reloj)
    r.sintonizar(a)
    r.sintonizar(estacion("B", n=6))
    diferido.correr()
    r.manejar_evento(cambio(primero_a))
    assert _seeks(soloist) == []


def test_si_el_play_local_falla_sigue_por_la_api():
    class SoloistSinPlay(SoloistFalso):
        def comando(self, nombre, **campos):
            if nombre == "play":
                raise ErrorSpotify("Soloist rechazó el play")
            super().comando(nombre, **campos)
    r, control, soloist, _, _ = armar(soloist=SoloistSinPlay())
    r.sintonizar(estacion())
    (uris, _), = control.llamadas
    r.manejar_evento(cambio(uris[0]))
    assert r.eventos["fallas"] == [] and _seeks(soloist) == []


def test_la_resintonia_no_usa_el_play_local():
    r, _, soloist, _, _ = armar()
    r.sintonizar(estacion())
    plays = [c for c in soloist.comandos if c[0] == "play"]
    r._resintonizar()
    assert [c for c in soloist.comandos if c[0] == "play"] == plays

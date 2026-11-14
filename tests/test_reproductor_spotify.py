from itertools import islice

import pytest

from cassette_fm.agenda import EPOCA, secuencia
from cassette_fm.biblioteca import Estacion, Pista
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

    def reproducir(self, uris, posicion_ms):
        self.llamadas.append((list(uris), posicion_ms))
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
    r.eventos = {"sonar": 0, "fallas": [], "cambios": []}
    r.al_sonar = lambda: r.eventos.__setitem__("sonar", r.eventos["sonar"] + 1)
    r.al_fallar = lambda e, motivo=None: r.eventos["fallas"].append((e.nombre, motivo))
    r.al_cambiar_pista = lambda p, e: r.eventos["cambios"].append((p.clave, e.nombre))
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

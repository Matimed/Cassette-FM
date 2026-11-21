import threading
import time

from cassette_fm.vigilante import Vigilante


class RadioFalsa:
    def __init__(self, oyentes=0, encendida=True):
        self.encendida = encendida
        self.cuantos = oyentes
        self.ultima_sintonia = 0.0
        self.durmio = 0
        self.fallar_una_vez = False

    def oyentes(self):
        if self.fallar_una_vez:
            self.fallar_una_vez = False
            raise RuntimeError("explota")
        return self.cuantos

    def dormir(self, gracia_segundos=None):
        self.durmio += 1
        self.gracias = getattr(self, "gracias", []) + [gracia_segundos]
        self.encendida = False


def vigilante(radio, gracia=60.0):
    t = [0.0]
    return Vigilante(radio, gracia, reloj=lambda: t[0]), t


def esperar(condicion, timeout=3.0):
    fin = time.monotonic() + timeout
    while time.monotonic() < fin:
        if condicion():
            return True
        time.sleep(0.01)
    return False


def test_con_oyentes_nunca_duerme():
    radio = RadioFalsa(oyentes=1)
    v, t = vigilante(radio)
    for t[0] in range(0, 1001, 10):
        v.revisar()
    assert radio.durmio == 0


def test_sin_oyentes_duerme_pasada_la_gracia_y_no_antes():
    radio = RadioFalsa()
    v, t = vigilante(radio)
    for t[0] in (0.0, 59.0):
        v.revisar()
    assert radio.durmio == 0
    t[0] = 60.0
    v.revisar()
    assert radio.durmio == 1
    assert radio.gracias == [60.0]            # la radio vuelve a mirar bajo su lock con esa misma gracia


def test_si_vuelve_un_oyente_antes_de_la_gracia_la_cuenta_se_reinicia():
    radio = RadioFalsa()
    v, t = vigilante(radio)
    v.revisar()                                  # t=0, sin oyentes
    t[0], radio.cuantos = 30.0, 1
    v.revisar()                                  # vuelve uno
    t[0], radio.cuantos = 40.0, 0
    v.revisar()                                  # se va de nuevo: la cuenta arranca acá
    t[0] = 99.0
    v.revisar()
    assert radio.durmio == 0
    t[0] = 100.0
    v.revisar()
    assert radio.durmio == 1


def test_radio_dormida_no_se_vuelve_a_dormir():
    radio = RadioFalsa(encendida=False)
    v, t = vigilante(radio)
    for t[0] in (0.0, 100.0, 1000.0):
        v.revisar()
    assert radio.durmio == 0


def test_un_pedido_de_la_red_en_la_gracia_reinicia_la_cuenta():
    radio = RadioFalsa()
    v, t = vigilante(radio)
    v.revisar()                                  # sin oyentes desde t=0
    t[0], radio.ultima_sintonia = 50.0, 50.0     # alguien elige emisora: todavía no abrió su stream
    v.revisar()
    t[0] = 100.0
    v.revisar()
    assert radio.durmio == 0
    t[0] = 110.0
    v.revisar()
    assert radio.durmio == 1


def test_el_hilo_revisa_y_se_cierra():
    radio = RadioFalsa()
    v = Vigilante(radio, 0.0)
    v.iniciar(intervalo=0.01)
    assert esperar(lambda: radio.durmio >= 1)
    v.cerrar()
    v.cerrar()                                   # idempotente
    assert not [h for h in threading.enumerate() if h.name == "vigilante-oyentes"]


def test_una_excepcion_en_revisar_no_mata_el_hilo():
    radio = RadioFalsa()
    radio.fallar_una_vez = True
    v = Vigilante(radio, 0.0)
    v.iniciar(intervalo=0.01)
    try:
        assert esperar(lambda: radio.durmio >= 1)
    finally:
        v.cerrar()

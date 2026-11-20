import json
from pathlib import Path

import pytest

from cassette_fm import recuperacion
from cassette_fm.biblioteca import Estacion


def estacion(nombre="Power F.M.", fuente="spotify"):
    return Estacion(nombre, (), fuente=fuente)


class Banco:
    """Reloj y 'systemctl' falsos."""
    def __init__(self):
        self.t = 1000.0
        self.reinicios = 0

    def ahora(self):
        return self.t

    def reiniciar(self):
        self.reinicios += 1


@pytest.fixture
def banco():
    return Banco()


@pytest.fixture
def ruta(tmp_path):
    return tmp_path / "estado" / "reinicio.json"


def pedir(ruta, banco, nombre="Power F.M.", motivo="Spotify no empezó a sonar en 10 s", bajo_systemd=True):
    return recuperacion.pedir_reinicio(ruta, nombre, motivo, ahora=banco.ahora, bajo_systemd=lambda: bajo_systemd,
                                       reiniciar=banco.reiniciar)


def test_pedir_reinicio_deja_el_marcador_y_reinicia(ruta, banco):
    assert pedir(ruta, banco) is True and banco.reinicios == 1
    datos = json.loads(ruta.read_text())
    assert datos["estacion"] == "Power F.M." and datos["cuando"] == 1000.0 and datos["retomado"] is False


def test_no_reinicia_dos_veces_seguidas(ruta, banco):
    assert pedir(ruta, banco) is True
    banco.t += recuperacion.VENTANA_SEGUNDOS - 1
    assert pedir(ruta, banco) is False and banco.reinicios == 1      # el freno: si el reinicio no arregló nada, se apaga


def test_pasada_la_ventana_puede_volver_a_reiniciar(ruta, banco):
    pedir(ruta, banco)
    banco.t += recuperacion.VENTANA_SEGUNDOS + 1
    assert pedir(ruta, banco) is True and banco.reinicios == 2


def test_fuera_de_systemd_no_reinicia_ni_deja_marcador(ruta, banco):
    assert pedir(ruta, banco, bajo_systemd=False) is False
    assert banco.reinicios == 0 and not ruta.exists()


def test_si_no_se_puede_lanzar_el_reinicio_no_queda_marcador(ruta, banco):
    def falla():
        raise OSError("no hay systemctl")
    assert recuperacion.pedir_reinicio(ruta, "A", "m", ahora=banco.ahora, bajo_systemd=lambda: True, reiniciar=falla) is False
    assert not ruta.exists()


def test_solo_las_emisoras_de_spotify_merecen_un_reinicio():
    assert recuperacion.merece_reinicio(estacion(), "Spotify no empezó a sonar en 10 s")
    assert recuperacion.merece_reinicio(estacion(), "Soloist no responde: ¿está corriendo?")
    assert not recuperacion.merece_reinicio(estacion(fuente="carpeta"), "no hay temas")
    assert not recuperacion.merece_reinicio(estacion(), "Spotify se está escuchando en otro dispositivo")   # reiniciar no lo arregla


def test_a_retomar_devuelve_la_emisora_si_el_marcador_es_reciente(ruta, banco):
    pedir(ruta, banco, nombre="Pop Hits F.M.")
    banco.t += 20
    assert recuperacion.a_retomar(ruta, ahora=banco.ahora) == "Pop Hits F.M."


@pytest.mark.parametrize("contenido", [None, "{no es json", "[]", '{"cuando": "x"}', '{"cuando": 1000, "estacion": 3}'])
def test_a_retomar_ignora_un_marcador_ausente_o_roto(ruta, banco, contenido):
    if contenido is not None:
        ruta.parent.mkdir(parents=True)
        ruta.write_text(contenido)
    assert recuperacion.a_retomar(ruta, ahora=banco.ahora) is None


def test_a_retomar_ignora_un_marcador_viejo_o_ya_usado(ruta, banco):
    pedir(ruta, banco)
    banco.t += recuperacion.VIGENCIA_SEGUNDOS + 1
    assert recuperacion.a_retomar(ruta, ahora=banco.ahora) is None      # el servicio no volvió por esto
    banco.t = 1010.0
    recuperacion.marcar_retomado(ruta)
    assert recuperacion.a_retomar(ruta, ahora=banco.ahora) is None      # ya se retomó una vez
    assert json.loads(ruta.read_text())["retomado"] is True             # y el marcador sigue de freno


class RadioFalsa:
    def __init__(self):
        self.llamadas = []

    def sintonizar(self, nombre, oir_aca=True):
        self.llamadas.append((nombre, oir_aca))


def test_retomar_espera_a_que_este_listo_y_sintoniza_sin_tocar_el_monitor(ruta, banco):
    pedir(ruta, banco, nombre="Power F.M.")
    radio, esperas = RadioFalsa(), []
    listo = iter([False, False, True])

    def dormir(s):
        esperas.append(s)
        banco.t += s
    assert recuperacion.retomar(ruta, radio, lambda: next(listo), ahora=banco.ahora, dormir=dormir) is True
    assert radio.llamadas == [("Power F.M.", False)] and len(esperas) == 2
    assert json.loads(ruta.read_text())["retomado"] is True


def test_retomar_sintoniza_igual_si_lo_que_espera_no_llega(ruta, banco):
    pedir(ruta, banco)
    radio = RadioFalsa()

    def dormir(s):
        banco.t += s
    assert recuperacion.retomar(ruta, radio, lambda: False, ahora=banco.ahora, dormir=dormir, espera=5.0) is True
    assert radio.llamadas == [("Power F.M.", False)]     # la radio sabe qué hacer si falla (otra emisora, o apagarse)


def test_retomar_sin_marcador_no_hace_nada(ruta, banco):
    radio = RadioFalsa()
    assert recuperacion.retomar(ruta, radio, lambda: True, ahora=banco.ahora, dormir=lambda s: None) is False
    assert radio.llamadas == []

import os
import queue
import threading
import time

import pytest

from cassette_fm.lan_stream import (FUENTE_ESTATICA, FUENTE_MONITOR, CodificadorNoDisponible, Difusor, SinCapacidad,
                                    comando_gst, lanzar_gst)


class ProcesoFalso:
    """Hace de gst-launch: lo que se `emitir` sale por stdout; terminarlo (o `morir`) cierra el pipe."""

    def __init__(self, comando):
        self.comando = comando
        lectura, self._escritura = os.pipe()
        self.stdout = os.fdopen(lectura, "rb", buffering=0)
        self.terminado = False
        self._lock = threading.Lock()

    def emitir(self, datos: bytes):
        os.write(self._escritura, datos)

    def morir(self):
        with self._lock:
            if not self.terminado:
                self.terminado = True
                os.close(self._escritura)

    terminate = kill = morir

    def wait(self, timeout=None):
        return 0


class Banco:
    def __init__(self):
        self.procesos: list[ProcesoFalso] = []
        self.fuente = FUENTE_MONITOR
        self.ahora = 1000.0

    def lanzar(self, comando):
        p = ProcesoFalso(comando)
        self.procesos.append(p)
        return p

    def difusor(self, **kw):
        kw.setdefault("gracia_segundos", 5.0)
        kw.setdefault("estabilidad_segundos", 2.0)
        return Difusor(lambda: self.fuente, lanzar=self.lanzar, reloj=lambda: self.ahora, **kw)


@pytest.fixture
def banco():
    b = Banco()
    yield b
    for p in b.procesos:
        p.morir()


def esperar(condicion, timeout=3.0):
    fin = time.monotonic() + timeout
    while time.monotonic() < fin:
        if condicion():
            return True
        time.sleep(0.01)
    return False


def test_arranca_con_el_primer_oyente_y_no_antes(banco):
    d = banco.difusor()
    assert banco.procesos == []
    d.suscribir()
    assert len(banco.procesos) == 1
    d.suscribir()
    assert len(banco.procesos) == 1
    d.cerrar()


def test_reparte_los_mismos_bytes_a_todos_los_oyentes(banco):
    d = banco.difusor()
    a, b = d.suscribir(), d.suscribir()
    banco.procesos[0].emitir(b"hola")
    assert a.get(timeout=2) == b"hola" and b.get(timeout=2) == b"hola"
    d.cerrar()


def test_se_detiene_pasada_la_gracia_del_ultimo_oyente_y_no_antes(banco):
    d = banco.difusor()
    q = d.suscribir()
    d.desuscribir(q)
    banco.ahora += 4.9
    d.revisar_fuente()
    assert not banco.procesos[0].terminado
    banco.ahora += 0.2
    d.revisar_fuente()
    assert banco.procesos[0].terminado


def test_un_oyente_que_vuelve_dentro_de_la_gracia_no_reinicia_el_codificador(banco):
    d = banco.difusor()
    d.desuscribir(d.suscribir())
    banco.ahora += 3
    d.suscribir()
    banco.ahora += 10
    d.revisar_fuente()
    assert len(banco.procesos) == 1 and not banco.procesos[0].terminado
    d.cerrar()


def test_oyente_lento_se_descarta_sin_frenar_a_los_demas(banco):
    d = banco.difusor(cola_max=2)
    lento, rapido = d.suscribir(), d.suscribir()
    proceso = banco.procesos[0]
    recibidos = []
    for i in range(6):
        proceso.emitir(bytes([i]) * 8)
        recibidos.append(rapido.get(timeout=2))
    assert len(recibidos) == 6
    assert esperar(lambda: None in list(lento.queue))      # al lento le llegó el fin
    d.cerrar()


def test_el_oyente_numero_cinco_recibe_SinCapacidad(banco):
    d = banco.difusor(max_oyentes=4)
    [d.suscribir() for _ in range(4)]
    with pytest.raises(SinCapacidad):
        d.suscribir()
    d.cerrar()


def test_cambio_de_fuente_reinicia_el_codificador_y_mantiene_a_los_oyentes(banco):
    d = banco.difusor()
    q = d.suscribir()
    assert "pulsesrc" in banco.procesos[0].comando
    banco.fuente = FUENTE_ESTATICA
    d.revisar_fuente()                      # marca la candidata
    banco.ahora += 2.5
    d.revisar_fuente()                      # estable: reinicia
    assert banco.procesos[0].terminado and len(banco.procesos) == 2
    assert "audiotestsrc" in banco.procesos[1].comando
    banco.procesos[1].emitir(b"estatica")
    assert q.get(timeout=2) == b"estatica"
    d.cerrar()


def test_el_flapeo_de_fuente_no_reinicia_antes_de_la_estabilidad(banco):
    d = banco.difusor()
    d.suscribir()
    banco.fuente = FUENTE_ESTATICA
    d.revisar_fuente()
    banco.ahora += 1.0
    banco.fuente = FUENTE_MONITOR
    d.revisar_fuente()
    banco.ahora += 1.5
    banco.fuente = FUENTE_ESTATICA
    d.revisar_fuente()
    banco.ahora += 1.5
    d.revisar_fuente()                       # solo 1,5 s desde la última vez que cambió: todavía no
    assert len(banco.procesos) == 1
    d.cerrar()


def test_cortar_oyentes_manda_None_a_todos_y_apaga_el_codificador(banco):
    d = banco.difusor()
    a, b = d.suscribir(), d.suscribir()
    d.cortar_oyentes()
    assert a.get(timeout=2) is None and b.get(timeout=2) is None
    assert banco.procesos[0].terminado


def test_codificador_que_muere_corta_a_los_oyentes_y_el_proximo_lo_relanza(banco):
    d = banco.difusor()
    q = d.suscribir()
    banco.procesos[0].morir()
    assert q.get(timeout=2) is None
    d.suscribir()
    assert len(banco.procesos) == 2
    d.cerrar()


def test_un_oyente_que_se_va_no_afecta_a_los_demas(banco):
    d = banco.difusor()
    a, b = d.suscribir(), d.suscribir()
    d.desuscribir(a)
    banco.procesos[0].emitir(b"x")
    assert b.get(timeout=2) == b"x"
    d.cerrar()


def test_comando_gst_para_cada_fuente():
    monitor = comando_gst(FUENTE_MONITOR)
    assert monitor[0] == "gst-launch-1.0" and "-q" in monitor
    assert "pulsesrc" in monitor and "device=radio_virtual.monitor" in monitor
    assert "lamemp3enc" in monitor and "bitrate=160" in monitor and "cbr=true" in monitor
    assert monitor[-2:] == ["fdsink", "fd=1"]
    estatica = comando_gst(FUENTE_ESTATICA)
    assert "audiotestsrc" in estatica and "wave=white-noise" in estatica and "pulsesrc" not in estatica


def test_lanzar_gst_sin_gstreamer_levanta_CodificadorNoDisponible(monkeypatch):
    monkeypatch.setenv("PATH", "/nonexistent")
    with pytest.raises(CodificadorNoDisponible):
        lanzar_gst(["gst-launch-1.0", "-q"])

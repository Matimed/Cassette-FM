import io
import os
import queue
import threading
import time

import pytest

from cassette_fm.lan_stream import (FUENTE_ESTATICA, FUENTE_MONITOR, CodificadorNoDisponible, Difusor, Difusores,
                                    SinCapacidad, comando_gst, lanzar_gst)


class ProcesoFalso:
    """Hace de gst-launch: lo que se `emitir` sale por stdout; terminarlo (o `morir`) cierra el pipe."""

    def __init__(self, comando, error=b""):
        self.comando = comando
        self.stderr = io.BytesIO(error)
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
        kw.setdefault("arranque_segundos", 0.0)
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


def test_la_calidad_de_ahorro_de_datos_va_en_mono_a_22050():
    # a 32 kbps el estéreo de 44,1 kHz obliga a LAME a bajar el muestreo a 16 kHz; en mono a 22,05 kHz conserva el del formato
    ahorro = comando_gst(FUENTE_MONITOR, kbps=32)
    assert "audio/x-raw,rate=22050,channels=1" in ahorro and "bitrate=32" in ahorro
    for kbps in (64, 96, 160):
        assert "audio/x-raw,rate=44100,channels=2" in comando_gst(FUENTE_MONITOR, kbps=kbps)


def test_lanzar_gst_sin_gstreamer_levanta_CodificadorNoDisponible(monkeypatch):
    monkeypatch.setenv("PATH", "/nonexistent")
    with pytest.raises(CodificadorNoDisponible):
        lanzar_gst(["gst-launch-1.0", "-q"])


def test_si_el_codificador_muere_al_arrancar_el_primer_oyente_recibe_el_motivo(banco):
    def lanzar(comando):
        p = ProcesoFalso(comando, error=b"ERROR: no existe el dispositivo radio_virtual.monitor\n")
        p.morir()
        banco.procesos.append(p)
        return p

    d = Difusor(lambda: banco.fuente, lanzar=lanzar, arranque_segundos=2.0)
    inicio = time.monotonic()
    with pytest.raises(CodificadorNoDisponible, match="radio_virtual.monitor"):
        d.suscribir()
    assert time.monotonic() - inicio < 1.5          # no espera todo el plazo: se entera cuando el pipe se cierra
    assert d._oyentes == [] and d._proceso is None
    d.cerrar()


def test_un_arranque_lento_pero_vivo_no_es_un_error(banco):
    d = banco.difusor(arranque_segundos=0.2)
    q = d.suscribir()                                  # no emite nada en 0,2 s pero el proceso sigue vivo
    banco.procesos[0].emitir(b"tarde")
    assert q.get(timeout=2) == b"tarde"
    d.cerrar()


def test_la_cola_por_oyente_tolera_baches_normales_pero_no_acumula_atrasos_enormes():
    # ~0,2 s por bloque de 4096 bytes a 160 kbps: los baches de unos segundos no cortan el audio (el retraso se recupera
    # al cambiar de emisora, con `resync`), y un oyente trabado por mucho más tiempo se descarta en vez de atrasarse sin fin
    d = Difusor(lambda: FUENTE_MONITOR)
    segundos = d._cola_max * 4096 * 8 / 160_000
    assert 3.0 <= segundos <= 8.0


# --- calidades ---

from cassette_fm.lan_stream import Difusores  # noqa: E402


def test_difusor_codifica_a_su_calidad(banco):
    d = banco.difusor(kbps=64)
    d.suscribir()
    assert "bitrate=64" in banco.procesos[0].comando and d.kbps == 64
    d.cerrar()


def test_difusores_crea_uno_por_calidad_y_lo_reusa(banco):
    creados = []

    def crear(fuente, **kw):
        creados.append(kw)
        return banco.difusor(**kw)

    r = Difusores(lambda: banco.fuente, crear=crear, max_oyentes=3)
    assert r.de(96) is r.de(96)
    assert r.de(64) is not r.de(96)
    assert [(k["kbps"], k["max_oyentes"]) for k in creados] == [(96, 3), (64, 3)]
    r.cerrar()


def test_la_cola_tolera_el_mismo_tiempo_en_cualquier_calidad(banco):
    r = Difusores(lambda: banco.fuente, crear=lambda f, **kw: banco.difusor(**kw))
    for kbps in (32, 64, 96, 160):
        d = r.de(kbps)
        segundos = d._cola_max * 4096 * 8 / (kbps * 1000)
        assert 4.0 <= segundos <= 6.0, (kbps, segundos)
    r.cerrar()


def test_difusores_revisa_corta_y_cierra_todos():
    class Falso:
        def __init__(self, **kw):
            self.revisiones = self.cortes = 0
            self.cerrado = False

        def revisar_fuente(self): self.revisiones += 1
        def cortar_oyentes(self): self.cortes += 1
        def cerrar(self): self.cerrado = True

    r = Difusores(lambda: FUENTE_MONITOR, crear=lambda f, **kw: Falso(**kw))
    a, b = r.de(64), r.de(160)
    r.revisar_fuente()
    r.cortar_oyentes()
    r.cerrar()
    assert (a.revisiones, b.revisiones, a.cortes, b.cortes, a.cerrado, b.cerrado) == (1, 1, 1, 1, True, True)


# --- conteo de oyentes y aviso de conexión (la radio se despierta con el primero) ---

def test_cantidad_oyentes_sube_y_baja_con_suscribir_y_desuscribir(banco):
    d = banco.difusor()
    assert d.cantidad_oyentes() == 0
    a, _b = d.suscribir(), d.suscribir()
    assert d.cantidad_oyentes() == 2
    d.desuscribir(a)
    assert d.cantidad_oyentes() == 1


def test_total_oyentes_suma_las_calidades(banco):
    difusores = Difusores(lambda: FUENTE_MONITOR, crear=lambda fuente, **kw: banco.difusor(**kw))
    difusores.de(64).suscribir()
    difusores.de(160).suscribir()
    difusores.de(160).suscribir()
    assert difusores.total_oyentes() == 3


def test_al_conectarse_se_llama_una_vez_por_suscripcion(banco):
    avisos = []
    d = banco.difusor(al_conectarse=lambda: avisos.append(1))
    d.suscribir()
    d.suscribir()
    assert len(avisos) == 2


def test_al_conectarse_llega_a_cada_calidad_de_difusores(banco):
    avisos = []
    difusores = Difusores(lambda: FUENTE_MONITOR, crear=lambda fuente, **kw: banco.difusor(**kw),
                          al_conectarse=lambda: avisos.append(1))
    difusores.de(64).suscribir()
    difusores.de(160).suscribir()
    assert len(avisos) == 2


def test_al_conectarse_corre_sin_el_lock_del_difusor(banco):
    """La radio toma su lock y pregunta cuántos oyentes hay: si el aviso corriera con el lock del difusor tomado,
    los dos locks se tomarían en orden inverso y se trabarían."""
    resultado = []
    d = banco.difusor()

    def aviso():
        def intentar():
            resultado.append(d._lock.acquire(timeout=1.0))
            if resultado[-1]:
                d._lock.release()
        hilo = threading.Thread(target=intentar)
        hilo.start()
        hilo.join()

    d._al_conectarse = aviso
    d.suscribir()
    assert resultado == [True]


def test_un_al_conectarse_que_falla_no_impide_el_stream(banco, caplog):
    def explota():
        raise RuntimeError("sin emisoras")

    d = banco.difusor(al_conectarse=explota)
    cola = d.suscribir()
    assert cola is not None and d.cantidad_oyentes() == 1
    assert "sin emisoras" in caplog.text

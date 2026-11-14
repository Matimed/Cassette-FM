import threading
import time
from pathlib import Path

import pytest

from cassette_fm.dj.cola import Cola, EstadoTrabajo
from cassette_fm.dj.produccion import Resultado
from cassette_fm.dj.sintetizador import ErrorModelos


class Reloj:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


class ProductorFalso:
    def __init__(self, tmp_path):
        self.tmp = tmp_path
        self.producidos = []
        self.puerta = None            # Event: si está, producir espera hasta que se abra
        self.entro = threading.Event()
        self.fallos = {}              # id -> excepción a lanzar
        self.paralelo = None          # Barrier: producir espera a que lleguen N trabajadores

    def producir(self, pedido):
        self.producidos.append(pedido.id)
        self.entro.set()
        if self.paralelo is not None:
            self.paralelo.wait(timeout=3)
        if self.puerta is not None:
            assert self.puerta.wait(timeout=5)
        if pedido.id in self.fallos:
            raise self.fallos[pedido.id]
        audio = self.tmp / f"{pedido.id}.wav"
        audio.write_bytes(b"RIFFfake")
        return Resultado(texto="hola", marcado="hola", ingredientes=("cancion",), duracion=3.0, audio=audio,
                         voz=pedido.voz, idioma=pedido.idioma)


@pytest.fixture
def armar(tmp_path):
    colas = []

    def crear(trabajadores=1, retencion=3600.0, reloj=None):
        prod = ProductorFalso(tmp_path)
        cola = Cola(prod, trabajadores=trabajadores, retencion_segundos=retencion, reloj=reloj or time.monotonic)
        colas.append(cola)
        return cola, prod

    yield crear
    for c in colas:
        c.detener(2)


def esperar(cond, timeout=3.0):
    fin = time.monotonic() + timeout
    while time.monotonic() < fin:
        if cond():
            return True
        time.sleep(0.01)
    return False


def terminado(cola, id_):
    return esperar(lambda: (cola.estado(id_) or {}).get("estado") in ("listo", "error", "cancelado"))


def test_un_pedido_termina_en_listo_con_su_resultado(armar, hacer_pedido):
    cola, _ = armar()
    assert cola.enviar(hacer_pedido("a")) == "a"
    assert terminado(cola, "a")
    e = cola.estado("a")
    assert e == {"estado": "listo", "duracion": 3.0, "texto": "hola", "ingredientes": ["cancion"], "error": None}


def test_es_idempotente_por_id(armar, hacer_pedido):
    cola, prod = armar()
    cola.enviar(hacer_pedido("a"))
    cola.enviar(hacer_pedido("a"))
    assert terminado(cola, "a")
    time.sleep(0.1)
    assert prod.producidos == ["a"]


def test_orden_de_llegada_con_un_trabajador(armar, hacer_pedido):
    cola, prod = armar()
    prod.puerta = threading.Event()
    for i in "abc":
        cola.enviar(hacer_pedido(i))
    assert prod.entro.wait(2)
    prod.puerta.set()
    assert all(terminado(cola, i) for i in "abc")
    assert prod.producidos == ["a", "b", "c"]


def test_cancelar_un_pendiente_si_y_uno_en_trabajo_no(armar, hacer_pedido):
    cola, prod = armar()
    prod.puerta = threading.Event()
    cola.enviar(hacer_pedido("a"))
    assert prod.entro.wait(2)
    cola.enviar(hacer_pedido("b"))
    assert cola.cancelar("b") is True
    assert cola.cancelar("a") is False
    assert cola.cancelar("no-existe") is False
    prod.puerta.set()
    assert terminado(cola, "a")
    time.sleep(0.2)
    assert prod.producidos == ["a"] and cola.estado("b")["estado"] == "cancelado"


@pytest.mark.parametrize("excepcion,texto", [
    (ValueError("el clip dura 20.0 s y el máximo es 10 s"), "el clip dura 20.0 s"),
    (ErrorModelos("faltan los modelos: corré `cassette-dj modelos`"), "cassette-dj modelos"),
])
def test_un_error_deja_el_trabajo_en_error_con_mensaje(armar, hacer_pedido, excepcion, texto):
    cola, prod = armar()
    prod.fallos["a"] = excepcion
    cola.enviar(hacer_pedido("a"))
    assert terminado(cola, "a")
    e = cola.estado("a")
    assert e["estado"] == "error" and texto in e["error"] and e["duracion"] is None


def test_una_excepcion_inesperada_no_mata_al_hilo(armar, hacer_pedido, caplog):
    cola, prod = armar()
    prod.fallos["a"] = RuntimeError("boom interno")
    cola.enviar(hacer_pedido("a"))
    cola.enviar(hacer_pedido("b"))
    assert terminado(cola, "a") and terminado(cola, "b")
    e = cola.estado("a")
    assert e["estado"] == "error" and "boom interno" not in e["error"] and "log" in e["error"]
    assert "boom interno" in caplog.text
    assert cola.estado("b")["estado"] == "listo"


def test_estado_de_un_id_desconocido_es_None(armar):
    cola, _ = armar()
    assert cola.estado("nadie") is None and cola.audio("nadie") is None


def test_audio_solo_si_esta_listo(armar, hacer_pedido):
    cola, prod = armar()
    prod.puerta = threading.Event()
    cola.enviar(hacer_pedido("a"))
    assert prod.entro.wait(2)
    assert cola.audio("a") is None                       # trabajando
    prod.puerta.set()
    assert terminado(cola, "a")
    ruta = cola.audio("a")
    assert isinstance(ruta, Path) and ruta.exists()
    ruta.unlink()
    assert cola.audio("a") is None                       # listo pero el archivo ya no está


def test_contadores(armar, hacer_pedido):
    cola, prod = armar()
    prod.puerta = threading.Event()
    prod.fallos["c"] = ValueError("x")
    cola.enviar(hacer_pedido("a"))
    assert prod.entro.wait(2)
    cola.enviar(hacer_pedido("b"))
    assert cola.contadores() == {"pendiente": 1, "trabajando": 1, "listo": 0, "error": 0, "cancelado": 0}
    cola.cancelar("b")
    prod.puerta.set()
    cola.enviar(hacer_pedido("c"))
    assert terminado(cola, "a") and terminado(cola, "c")
    assert cola.contadores() == {"pendiente": 0, "trabajando": 0, "listo": 1, "error": 1, "cancelado": 1}


def test_la_retencion_borra_terminados_y_sus_clips(armar, hacer_pedido):
    reloj = Reloj()
    cola, prod = armar(retencion=100, reloj=reloj)
    cola.enviar(hacer_pedido("a"))
    assert terminado(cola, "a")
    clip = cola.audio("a")
    reloj.t = 99
    assert cola.limpiar() == 0 and clip.exists()
    reloj.t = 100
    assert cola.limpiar() == 1
    assert not clip.exists() and cola.estado("a") is None


def test_detener_no_deja_hilos_vivos(armar, hacer_pedido):
    antes = set(threading.enumerate())
    cola, _ = armar(trabajadores=2)
    cola.enviar(hacer_pedido("a"))
    assert terminado(cola, "a")
    cola.detener(3)
    nuevos = [h for h in threading.enumerate() if h not in antes and h.is_alive()]
    assert nuevos == []


def test_dos_trabajadores_procesan_en_paralelo(armar, hacer_pedido):
    cola, prod = armar(trabajadores=2)
    prod.paralelo = threading.Barrier(2)
    cola.enviar(hacer_pedido("a"))
    cola.enviar(hacer_pedido("b"))
    assert terminado(cola, "a") and terminado(cola, "b")
    assert cola.estado("a")["estado"] == "listo" and cola.estado("b")["estado"] == "listo"


def test_enviar_despues_de_detener_falla(armar, hacer_pedido):
    cola, _ = armar()
    cola.detener(2)
    with pytest.raises(RuntimeError):
        cola.enviar(hacer_pedido("a"))

import time
from itertools import islice
from pathlib import Path

import pytest

from cassette_fm.agenda import EPOCA, secuencia
from cassette_fm.biblioteca import Estacion, Pista
from cassette_fm.mpv import ClienteMpv
from cassette_fm.reproductor import Reproductor


class MpvFalso:
    def __init__(self):
        self.comandos = []
        self.al_evento = None
        self.al_perder = None
        self.generacion = 0
        self._ids = 0

    def asegurar(self):
        pass

    def comando(self, *args, **nombrados):
        self.comandos.append((args, nombrados))
        if args[0] == "loadfile":
            self._ids += 1
            return {"playlist_entry_id": self._ids}
        return None


def estacion(n=4, nombre="E"):
    return Estacion(nombre, tuple(
        Pista(Path(f"/m/{i}.mp3"), 100 + i, f"t{i}") for i in range(n)))


T = EPOCA + 30
E = estacion()
S = list(islice(secuencia(E, T), 5))


@pytest.fixture
def mpv():
    return MpvFalso()


@pytest.fixture
def rep(mpv):
    return Reproductor(mpv, reloj=lambda: T)


def test_sintonizar_carga_con_desplazamiento_y_encola(rep, mpv):
    rep.sintonizar(E)
    (p0, desde) = S[0]
    assert mpv.comandos == [
        (("loadfile",), {"url": str(p0.ruta), "flags": "replace",
                         "options": {"start": f"{desde:.3f}"}}),
        (("loadfile",), {"url": str(S[1][0].ruta), "flags": "append"}),
        (("loadfile",), {"url": str(S[2][0].ruta), "flags": "append"}),
    ]


def test_start_file_fija_pista_actual_y_file_loaded_avisa(rep, mpv):
    avisos = []
    rep.al_cambiar_pista = avisos.append
    rep.sintonizar(E)
    rep.manejar_evento({"event": "start-file", "playlist_entry_id": 1})
    assert rep.pista_actual == S[0][0]
    assert avisos == []
    rep.manejar_evento({"event": "file-loaded"})
    assert avisos == [S[0][0]]


def test_start_file_siguiente_rota_la_cola(rep, mpv):
    rep.sintonizar(E)
    rep.manejar_evento({"event": "start-file", "playlist_entry_id": 1})
    mpv.comandos.clear()
    rep.manejar_evento({"event": "start-file", "playlist_entry_id": 2})
    assert rep.pista_actual == S[1][0]
    assert mpv.comandos == [
        (("playlist-remove", 0), {}),
        (("loadfile",), {"url": str(S[3][0].ruta), "flags": "append"}),
    ]


def test_eventos_de_sintonizacion_vieja_se_ignoran(rep, mpv):
    rep.sintonizar(E)  # ids 1..3
    rep.sintonizar(estacion(4, "B"))  # ids 4..6
    rep.manejar_evento({"event": "start-file", "playlist_entry_id": 4})
    actual = rep.pista_actual
    mpv.comandos.clear()
    rep.manejar_evento({"event": "start-file", "playlist_entry_id": 2})
    assert rep.pista_actual == actual
    assert mpv.comandos == []


def test_volumen_se_recorta(rep, mpv):
    assert rep.volumen(150) == 100
    assert rep.volumen(-5) == 0
    assert mpv.comandos == [(("set_property", "volume", 100), {}),
                            (("set_property", "volume", 0), {})]


def test_detener(rep, mpv):
    rep.sintonizar(E)
    rep.manejar_evento({"event": "start-file", "playlist_entry_id": 1})
    mpv.comandos.clear()
    rep.detener()
    assert mpv.comandos == [(("stop",), {})]
    assert rep.pista_actual is None
    rep.manejar_evento({"event": "start-file", "playlist_entry_id": 2})
    assert rep.pista_actual is None


def test_relanzamiento_restaura_volumen_y_estacion(rep, mpv):
    rep.sintonizar(E)
    rep.volumen(60)
    mpv.comandos.clear()
    mpv.generacion += 1  # mpv se relanzó
    rep.asegurar()
    assert mpv.comandos[0] == (("set_property", "volume", 60), {})
    assert mpv.comandos[1][1]["flags"] == "replace"
    assert mpv.comandos[1][1]["url"] == str(S[0][0].ruta)
    mpv.comandos.clear()
    rep.asegurar()  # ya restaurado: no repite
    assert mpv.comandos == []


def test_sintonizar_tras_relanzamiento_no_carga_dos_veces(rep, mpv):
    rep.sintonizar(E)
    rep.volumen(60)
    mpv.comandos.clear()
    mpv.generacion += 1
    rep.sintonizar(estacion(3, "B"))
    cargas = [c for c in mpv.comandos if c[0][0] == "loadfile" and c[1]["flags"] == "replace"]
    assert len(cargas) == 1
    assert (("set_property", "volume", 60), {}) in mpv.comandos


def test_volumen_tras_relanzamiento_restaura_estacion_y_aplica_el_nuevo(rep, mpv):
    rep.sintonizar(E)
    mpv.comandos.clear()
    mpv.generacion += 1
    rep.volumen(50)
    assert any(c[0][0] == "loadfile" and c[1]["flags"] == "replace" for c in mpv.comandos)
    assert mpv.comandos[-1] == (("set_property", "volume", 50), {})


def test_detener_olvida_la_estacion_para_el_relanzamiento(rep, mpv):
    rep.sintonizar(E)
    rep.detener()
    mpv.comandos.clear()
    mpv.generacion += 1
    rep.asegurar()
    assert not any(c[0][0] == "loadfile" for c in mpv.comandos)


# --- integración con mpv real ---

def esperar(condicion, timeout):
    fin = time.monotonic() + timeout
    while time.monotonic() < fin:
        if condicion():
            return True
        time.sleep(0.02)
    return False


@pytest.fixture
def mpv_real(dir_corto):
    cliente = ClienteMpv(dir_corto / "mpv.sock", extra_args=["--ao=null"])
    cliente.iniciar()
    yield cliente
    cliente.cerrar()


def _estacion_real(crear_mp3, tmp_path, n, segundos=2):
    pistas = []
    for i in range(n):
        r = crear_mp3(tmp_path / f"{i}.mp3", segundos)
        pistas.append(Pista(r, float(segundos), f"t{i}"))
    return Estacion("R", tuple(pistas))


def test_integracion_entra_a_mitad_y_avanza(mpv_real, crear_mp3, tmp_path):
    e = _estacion_real(crear_mp3, tmp_path, 3)
    reloj = lambda: EPOCA + 1.5
    esperadas = [p for p, _ in islice(secuencia(e, reloj()), 3)]
    rep = Reproductor(mpv_real, reloj=reloj)
    vistas = []
    rep.al_cambiar_pista = vistas.append
    rep.sintonizar(e)
    assert esperar(lambda: len(vistas) >= 2, 5)
    assert vistas[0] == esperadas[0]
    assert vistas[1] == esperadas[1]


def test_integracion_salta_archivo_borrado(mpv_real, crear_mp3, tmp_path):
    e = _estacion_real(crear_mp3, tmp_path, 4)
    reloj = lambda: EPOCA + 0.5
    s = [p for p, _ in islice(secuencia(e, reloj()), 4)]
    rep = Reproductor(mpv_real, reloj=reloj)
    vistas = []
    rep.al_cambiar_pista = vistas.append
    rep.sintonizar(e)
    s[1].ruta.unlink()
    assert esperar(lambda: s[2] in vistas, 8)
    assert s[1] not in vistas


def test_integracion_mpv_muerto_restaura_volumen_y_playlist(mpv_real, crear_mp3, tmp_path):
    import os, signal
    e = _estacion_real(crear_mp3, tmp_path, 3, segundos=30)
    rep = Reproductor(mpv_real, reloj=lambda: EPOCA + 1)
    vistas = []
    rep.al_cambiar_pista = vistas.append
    rep.volumen(70)
    rep.sintonizar(e)
    assert esperar(lambda: len(vistas) == 1, 5)
    os.kill(mpv_real._proceso.pid, signal.SIGKILL)
    assert esperar(lambda: len(vistas) == 2, 8)  # se resintonizó solo, sin ningún comando
    assert mpv_real.comando("get_property", "volume") == 70

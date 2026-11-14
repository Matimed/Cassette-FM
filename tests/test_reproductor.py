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

    def vivo(self):
        return True

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
    rep.al_cambiar_pista = lambda p, e: avisos.append((p, e.nombre))
    rep.sintonizar(E)
    rep.manejar_evento({"event": "start-file", "playlist_entry_id": 1})
    assert rep.pista_actual == S[0][0]
    assert avisos == []
    rep.manejar_evento({"event": "file-loaded"})
    assert avisos == [(S[0][0], "E")]


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


def test_posicion_pregunta_a_mpv_solo_si_hay_pista(rep, mpv):
    assert rep.posicion() is None
    rep.sintonizar(E)
    rep.manejar_evento({"event": "start-file", "playlist_entry_id": 1})
    mpv.comando = lambda *a, **k: 12.5 if a[:2] == ("get_property", "time-pos") else {"playlist_entry_id": 1}
    mpv.vivo = lambda: True
    assert rep.posicion() == 12.5
    mpv.vivo = lambda: False
    assert rep.posicion() is None


def _fallo(rep, id_):
    rep.manejar_evento({"event": "end-file", "reason": "error", "playlist_entry_id": id_})


def test_demasiados_errores_seguidos_detienen_y_avisan(rep, mpv):
    caidas = []
    rep.al_fallar = lambda e: caidas.append(e.nombre)
    rep.sintonizar(E)  # ids 1..3
    mpv.comandos.clear()
    for _ in range(Reproductor.MAX_FALLOS - 1):
        _fallo(rep, 1)
    assert caidas == [] and (("stop",), {}) not in mpv.comandos
    _fallo(rep, 1)
    assert caidas == ["E"] and (("stop",), {}) in mpv.comandos
    assert rep.pista_actual is None


def test_cargar_bien_reinicia_la_cuenta_de_errores(rep, mpv):
    caidas = []
    rep.al_fallar = lambda e: caidas.append(e.nombre)
    rep.sintonizar(E)
    for _ in range(Reproductor.MAX_FALLOS - 1):
        _fallo(rep, 1)
    rep.manejar_evento({"event": "start-file", "playlist_entry_id": 1})
    rep.manejar_evento({"event": "file-loaded"})
    for _ in range(Reproductor.MAX_FALLOS - 1):
        _fallo(rep, 1)
    assert caidas == []


def _con_mpv(mpv, idle, playlist=()):
    """El mpv falso responde idle-active y la playlist actual (lista de {"id": n})."""
    original = mpv.comando

    def comando(*args, **kw):
        if args[:2] == ("get_property", "idle-active"):
            mpv.comandos.append((args, kw))
            return idle
        if args[:2] == ("get_property", "playlist"):
            mpv.comandos.append((args, kw))
            return [{"id": i} for i in playlist]
        return original(*args, **kw)

    mpv.comando = comando


def test_idle_con_todos_los_temas_fallidos_detiene_y_avisa(rep, mpv):
    caidas = []
    rep.al_fallar = lambda e: caidas.append(e.nombre)
    rep.sintonizar(E)  # ids 1..3
    for i in (1, 2, 3):
        _fallo(rep, i)
    _con_mpv(mpv, idle=True, playlist=(1, 2, 3))
    rep.manejar_evento({"event": "idle"})
    assert caidas == ["E"] and (("stop",), {}) in mpv.comandos
    assert rep.pista_actual is None


def test_idle_con_temas_buenos_pendientes_sigue_con_el_primero_sano(rep, mpv):
    caidas = []
    rep.al_fallar = lambda e: caidas.append(e.nombre)
    rep.sintonizar(E)  # ids 1..3
    _fallo(rep, 1)     # el primero no cargó
    _con_mpv(mpv, idle=True, playlist=(1, 2, 3))
    mpv.comandos.clear()
    rep.manejar_evento({"event": "idle"})
    assert caidas == []
    assert (("playlist-play-index", 1), {}) in mpv.comandos
    assert (("stop",), {}) not in mpv.comandos


def test_idle_falso_con_mpv_sonando_se_ignora(rep, mpv):
    caidas = []
    rep.al_fallar = lambda e: caidas.append(e.nombre)
    rep.sintonizar(E)
    _con_mpv(mpv, idle=False)
    mpv.comandos.clear()
    rep.manejar_evento({"event": "idle"})
    assert caidas == [] and (("stop",), {}) not in mpv.comandos


def test_idle_sin_estacion_sintonizada_se_ignora(rep, mpv):
    caidas = []
    rep.al_fallar = lambda e: caidas.append(e.nombre)
    _con_mpv(mpv, idle=True)
    rep.manejar_evento({"event": "idle"})
    assert caidas == []


def _volumenes(mpv):
    return [c[0][2] for c in mpv.comandos if c[0][:2] == ("set_property", "volume")]


def test_atenuar_sin_rampa_aplica_el_volumen_por_el_factor(rep, mpv):
    rep.volumen(80)
    rep.atenuar(0.35, 0)
    assert _volumenes(mpv)[-1] == pytest.approx(28.0)


def test_atenuar_con_rampa_baja_en_pasos_y_llega_al_valor(rep, mpv):
    rep.volumen(80)
    mpv.comandos.clear()
    rep.atenuar(0.5, 0.2)
    fin = time.monotonic() + 1.0
    while time.monotonic() < fin and (not _volumenes(mpv) or _volumenes(mpv)[-1] != pytest.approx(40.0)):
        time.sleep(0.02)
    v = _volumenes(mpv)
    assert len(v) > 2
    assert all(b <= a + 1e-9 for a, b in zip(v, v[1:]))
    assert v[-1] == pytest.approx(40.0)


def test_volumen_durante_la_atenuacion_respeta_el_factor(rep, mpv):
    rep.volumen(80)
    rep.atenuar(0.35, 0)
    rep.volumen(60)
    assert _volumenes(mpv)[-1] == pytest.approx(21.0)
    rep.atenuar(1.0, 0)
    assert _volumenes(mpv)[-1] == pytest.approx(60.0)


def test_restaurar_devuelve_el_volumen_del_usuario(rep, mpv):
    rep.volumen(70)
    rep.atenuar(0.35, 0)
    rep.atenuar(1.0, 0)
    assert _volumenes(mpv)[-1] == pytest.approx(70.0)


def test_una_rampa_nueva_reemplaza_a_la_anterior(rep, mpv):
    rep.volumen(80)
    rep.atenuar(0.2, 0.5)
    rep.atenuar(1.0, 0)
    time.sleep(0.7)
    assert _volumenes(mpv)[-1] == pytest.approx(80.0)


def test_volumen_cero_con_atenuacion_es_cero(rep, mpv):
    rep.volumen(0)
    rep.atenuar(0.35, 0)
    assert _volumenes(mpv)[-1] == pytest.approx(0.0)


def test_una_rampa_que_encuentra_mpv_caido_deja_el_factor_en_el_destino(rep, mpv):
    """Review: no dejar la música bajada a medias si la rampa se corta."""
    rep.volumen(80)
    rep.atenuar(0.5, 0)
    mpv.vivo = lambda: False
    rep.atenuar(1.0, 0.2)
    time.sleep(0.4)
    mpv.vivo = lambda: True
    rep.volumen(80)
    assert _volumenes(mpv)[-1] == pytest.approx(80.0)


def test_relanzamiento_reaplica_el_volumen_efectivo(rep, mpv):
    rep.volumen(80)
    rep.atenuar(0.5, 0)
    mpv.generacion += 1
    rep.asegurar()
    assert _volumenes(mpv)[-1] == pytest.approx(40.0)


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
    rep.al_cambiar_pista = lambda p, e: vistas.append(p)
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
    rep.al_cambiar_pista = lambda p, e: vistas.append(p)
    rep.sintonizar(e)
    s[1].ruta.unlink()
    assert esperar(lambda: s[2] in vistas, 8)
    assert s[1] not in vistas


def test_integracion_mpv_muerto_restaura_volumen_y_playlist(mpv_real, crear_mp3, tmp_path):
    import os, signal
    e = _estacion_real(crear_mp3, tmp_path, 3, segundos=30)
    rep = Reproductor(mpv_real, reloj=lambda: EPOCA + 1)
    vistas = []
    rep.al_cambiar_pista = lambda p, e: vistas.append(p)
    rep.volumen(70)
    rep.sintonizar(e)
    assert esperar(lambda: len(vistas) == 1, 5)
    os.kill(mpv_real._proceso.pid, signal.SIGKILL)
    assert esperar(lambda: len(vistas) == 2, 8)  # se resintonizó solo, sin ningún comando
    assert mpv_real.comando("get_property", "volume") == 70


def test_integracion_estacion_sin_archivos_termina_parando(mpv_real, crear_mp3, tmp_path):
    e = _estacion_real(crear_mp3, tmp_path, 3)
    for p in e.pistas:
        p.ruta.unlink()
    rep = Reproductor(mpv_real, reloj=lambda: EPOCA + 1)
    caidas = []
    rep.al_fallar = lambda e: caidas.append(e.nombre)
    rep.sintonizar(e)
    assert esperar(lambda: caidas, 8)
    assert rep.pista_actual is None


def test_integracion_primer_archivo_roto_sigue_con_el_siguiente(mpv_real, crear_mp3, tmp_path):
    e = _estacion_real(crear_mp3, tmp_path, 4)
    reloj = lambda: EPOCA + 0.5
    s = [p for p, _ in islice(secuencia(e, reloj()), 4)]
    s[0].ruta.unlink()   # falla el primero, justo el que se carga con `replace`
    rep = Reproductor(mpv_real, reloj=reloj)
    vistas, caidas = [], []
    rep.al_cambiar_pista = lambda p, est: vistas.append(p)
    rep.al_fallar = lambda est: caidas.append(1)
    rep.sintonizar(e)
    assert esperar(lambda: s[1] in vistas, 8)
    assert caidas == []


def test_integracion_una_rampa_en_curso_no_relanza_mpv_tras_cerrar(dir_corto):
    """Review: cerrar el servicio durante una rampa no puede dejar un mpv de música huérfano."""
    import subprocess
    cliente = ClienteMpv(dir_corto / "m.sock", extra_args=["--ao=null"])
    cliente.iniciar()
    rep = Reproductor(cliente)
    rep.volumen(80)
    rep.atenuar(0.3, 0)
    rep.atenuar(1.0, 0.8)           # rampa de subida en curso
    time.sleep(0.1)
    cliente.cerrar()
    time.sleep(1.3)                 # la rampa seguía hasta ~0,8 s: antes relanzaba mpv
    assert subprocess.run(["pgrep", "-f", str(dir_corto / "m.sock")], capture_output=True).returncode == 1


def test_estatica_en_bucle_y_al_sacarla_para(mpv):
    rep = Reproductor(mpv, reloj=lambda: T)
    rep.sintonizar(E)
    mpv.comandos.clear()
    rep.estatica(Path("/tmp/estatica.wav"))
    assert mpv.comandos == [(("loadfile",), {"url": "/tmp/estatica.wav", "flags": "replace",
                                             "options": {"loop-file": "inf"}})]   # solo para ese archivo
    assert rep.pista_actual is None
    rep.manejar_evento({"event": "file-loaded"})        # el clip de estática no es un tema de la emisora
    mpv.comandos.clear()
    rep.estatica(None)
    assert mpv.comandos == [(("stop",), {})]

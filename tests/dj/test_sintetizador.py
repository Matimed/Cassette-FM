import functools
import http.server
import threading
import wave

import mutagen
import numpy as np
import pytest

from cassette_fm.dj.config import ConfigServicioDJ
from cassette_fm.dj.sintetizador import (ARCHIVOS_MODELO, ErrorModelos, Sintetizador, descargar_modelos,
                                         faltan_modelos, fonemizador)


class Reloj:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def sint(fabrica, config=None, reloj=None):
    return Sintetizador(config or ConfigServicioDJ(), fabrica=fabrica, reloj=reloj or Reloj())


def test_sintetiza_y_escribe_un_wav_valido(tmp_path, fabrica_falsa):
    salida = tmp_path / "a" / "b" / "clip.wav"
    dur = sint(fabrica_falsa).sintetizar("fonemas", "em_santa", "es", salida)
    assert dur == pytest.approx(0.5)
    with wave.open(str(salida), "rb") as w:
        assert w.getnchannels() == 1 and w.getsampwidth() == 2 and w.getframerate() == 24000
    assert mutagen.File(salida).info.length == pytest.approx(0.5, abs=0.02)
    assert not list(salida.parent.glob("*.part"))


def test_pasa_los_parametros_de_la_configuracion(tmp_path, fabrica_falsa):
    cfg = ConfigServicioDJ(velocidad=1.1, pausa_oracion_segundos=0.2, pausa_coma_segundos=0.05, continuo=True)
    sint(fabrica_falsa, cfg).sintetizar("fon", "em_santa", "es", tmp_path / "c.wav")
    (llamada,) = fabrica_falsa.estado.llamadas
    assert llamada == dict(text="fon", voice="em_santa", speed=1.1, lang="es", is_phonemes=True,
                           sentence_pause=0.2, clause_pause=0.05, continuous=True)


def test_carga_una_sola_vez(tmp_path, fabrica_falsa):
    s = sint(fabrica_falsa)
    s.sintetizar("a", "em_santa", "es", tmp_path / "1.wav")
    s.sintetizar("b", "em_santa", "es", tmp_path / "2.wav")
    assert fabrica_falsa.estado.cargas == 1 and s.cargado


def test_descarga_tras_el_tiempo_ocioso(tmp_path, fabrica_falsa):
    reloj = Reloj()
    s = sint(fabrica_falsa, ConfigServicioDJ(descargar_tras_minutos=5), reloj)
    assert s.descargar_si_ocioso() is False                  # nunca se cargó
    s.sintetizar("a", "em_santa", "es", tmp_path / "1.wav")
    reloj.t = 299
    assert s.descargar_si_ocioso() is False and s.cargado
    reloj.t = 300
    assert s.descargar_si_ocioso() is True and not s.cargado
    s.sintetizar("b", "em_santa", "es", tmp_path / "2.wav")
    assert fabrica_falsa.estado.cargas == 2


def test_voz_inexistente_da_ValueError_con_las_disponibles(tmp_path, fabrica_falsa):
    with pytest.raises(ValueError) as exc:
        sint(fabrica_falsa).sintetizar("a", "voz_rara", "es", tmp_path / "x.wav")
    assert "voz_rara" in str(exc.value) and "em_santa" in str(exc.value)
    assert not (tmp_path / "x.wav").exists()


def test_mezcla_de_voces_promedia_los_estilos(tmp_path, fabrica_falsa):
    sint(fabrica_falsa).sintetizar("a", "em_santa+em_alex", "es", tmp_path / "m.wav")
    (llamada,) = fabrica_falsa.estado.llamadas
    assert isinstance(llamada["voice"], np.ndarray)
    assert np.allclose(llamada["voice"], 4.0)                # (5 + 3) / 2


def test_mezcla_con_una_voz_inexistente_falla(tmp_path, fabrica_falsa):
    with pytest.raises(ValueError) as exc:
        sint(fabrica_falsa).sintetizar("a", "em_santa+nadie", "es", tmp_path / "m.wav")
    assert "nadie" in str(exc.value)


def test_voces_no_carga_el_modelo(tmp_path, fabrica_falsa):
    modelos = tmp_path / "modelos"
    modelos.mkdir()
    with open(modelos / "voices-v1.0.bin", "wb") as f:
        np.savez(f, em_santa=np.zeros(3), am_michael=np.zeros(3))
    s = sint(fabrica_falsa, ConfigServicioDJ(modelos_dir=modelos))
    assert s.voces() == ["am_michael", "em_santa"]
    assert fabrica_falsa.estado.cargas == 0 and not s.cargado


def test_voces_sin_archivo_da_ErrorModelos(tmp_path, fabrica_falsa):
    with pytest.raises(ErrorModelos):
        sint(fabrica_falsa, ConfigServicioDJ(modelos_dir=tmp_path / "vacio")).voces()


def test_sin_modelos_da_ErrorModelos_claro(tmp_path):
    cfg = ConfigServicioDJ(modelos_dir=tmp_path / "vacio")
    with pytest.raises(ErrorModelos) as exc:
        Sintetizador(cfg).sintetizar("a", "em_santa", "es", tmp_path / "x.wav")
    mensaje = str(exc.value)
    assert "kokoro-v1.0.onnx" in mensaje and "voices-v1.0.bin" in mensaje and "cassette-dj modelos" in mensaje
    assert [p.name for p in faltan_modelos(cfg.modelos_dir)] == list(ARCHIVOS_MODELO)


def test_archivos_vacios_cuentan_como_faltantes(tmp_path):
    for nombre in ARCHIVOS_MODELO:
        (tmp_path / nombre).write_bytes(b"")
    assert len(faltan_modelos(tmp_path)) == 2
    (tmp_path / ARCHIVOS_MODELO[0]).write_bytes(b"x")
    assert [p.name for p in faltan_modelos(tmp_path)] == [ARCHIVOS_MODELO[1]]


def test_es_seguro_con_hilos(tmp_path, fabrica_falsa):
    s = sint(fabrica_falsa)
    hilos = [threading.Thread(target=s.sintetizar, args=("x", "em_santa", "es", tmp_path / f"{i}.wav"))
             for i in range(4)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join(10)
    assert all((tmp_path / f"{i}.wav").exists() for i in range(4)) and fabrica_falsa.estado.cargas == 1


# --- descarga de modelos ---

@pytest.fixture
def servidor_local(tmp_path):
    raiz = tmp_path / "web"
    raiz.mkdir()
    manejador = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(raiz))
    manejador.log_message = lambda *a, **k: None
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), manejador)
    hilo = threading.Thread(target=lambda: srv.serve_forever(poll_interval=0.02), daemon=True)
    hilo.start()
    yield raiz, f"http://127.0.0.1:{srv.server_address[1]}/"
    srv.shutdown()
    srv.server_close()


def test_descargar_modelos_baja_solo_los_que_faltan(tmp_path, servidor_local):
    raiz, url = servidor_local
    for nombre in ARCHIVOS_MODELO:
        (raiz / nombre).write_bytes(nombre.encode() * 100)
    destino = tmp_path / "modelos"
    destino.mkdir()
    (destino / ARCHIVOS_MODELO[0]).write_bytes(b"ya estaba")
    lineas = []
    bajados = descargar_modelos(destino, url, lineas.append)
    assert [p.name for p in bajados] == [ARCHIVOS_MODELO[1]]
    assert (destino / ARCHIVOS_MODELO[0]).read_bytes() == b"ya estaba"
    assert (destino / ARCHIVOS_MODELO[1]).read_bytes() == ARCHIVOS_MODELO[1].encode() * 100
    assert not list(destino.glob("*.part")) and lineas and any(ARCHIVOS_MODELO[1] in l for l in lineas)


def test_descargar_modelos_con_error_de_red_no_deja_basura(tmp_path, servidor_local):
    raiz, url = servidor_local                                   # no hay ningún archivo: 404
    destino = tmp_path / "modelos"
    with pytest.raises(OSError):
        descargar_modelos(destino, url, lambda l: None)
    assert not list(destino.glob("*.part")) and faltan_modelos(destino)


def test_descargar_no_hace_nada_si_estan_todos(tmp_path):
    for nombre in ARCHIVOS_MODELO:
        (tmp_path / nombre).write_bytes(b"x")
    assert descargar_modelos(tmp_path, "http://127.0.0.1:1/", lambda l: None) == []


# --- con Kokoro de verdad (se saltean si no están los modelos) ---

def test_integracion_con_kokoro_real(tmp_path, modelos_reales):
    from kokoro_onnx import Tokenizer
    cfg = ConfigServicioDJ(modelos_dir=modelos_reales)
    s = Sintetizador(cfg)
    fon = Tokenizer().phonemize("Qué tal gente son las nueve en Buenos Aires con dieciocho grados", "es")
    dur = s.sintetizar(fon, "em_santa", "es", tmp_path / "real.wav")
    assert 2.0 <= dur <= 8.0
    assert mutagen.File(tmp_path / "real.wav").info.length == pytest.approx(dur, abs=0.1)
    assert "em_santa" in s.voces()
    mezcla = s.sintetizar(fon, "em_santa+em_alex", "es", tmp_path / "mezcla.wav")
    assert 2.0 <= mezcla <= 8.0
    s.descargar_si_ocioso()


def test_fonemizador_funciona_sin_el_modelo():
    pytest.importorskip("kokoro_onnx")
    f = fonemizador()
    assert "bwˈenos" in f("Buenos Aires", "es")

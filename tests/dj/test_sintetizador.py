import functools
import http.server
import sys
import threading
import wave

import mutagen
import pytest

np = pytest.importorskip("numpy")

from cassette_fm.dj.config import ConfigServicioDJ
from cassette_fm.dj.texto_voz import preparar, texto_para_piper
from cassette_fm.dj import sintetizador as mod
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


def test_descargar_rechaza_descargas_incompletas(tmp_path):
    """Review: un archivo truncado no puede quedar con su nombre final como si estuviera bien."""
    class Truncado(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Length", "1000")
            self.end_headers()
            self.wfile.write(b"x" * 10)

        def log_message(self, *a):
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Truncado)
    threading.Thread(target=lambda: srv.serve_forever(poll_interval=0.02), daemon=True).start()
    try:
        destino = tmp_path / "modelos"
        with pytest.raises(OSError):
            descargar_modelos(destino, f"http://127.0.0.1:{srv.server_address[1]}/", lambda l: None)
        assert not list(destino.glob("*.part"))
        assert [p.name for p in faltan_modelos(destino)] == list(ARCHIVOS_MODELO)   # nada quedó "completo"
    finally:
        srv.shutdown()
        srv.server_close()


def test_archivo_de_voces_corrupto_da_ErrorModelos(tmp_path):
    (tmp_path / ARCHIVOS_MODELO[1]).write_bytes(b"basura que no es un npz")
    with pytest.raises(ErrorModelos) as exc:
        Sintetizador(ConfigServicioDJ(modelos_dir=tmp_path)).voces()
    assert "cassette-dj modelos" in str(exc.value)


def test_modelo_corrupto_da_ErrorModelos(tmp_path):
    pytest.importorskip("kokoro_onnx")
    (tmp_path / ARCHIVOS_MODELO[0]).write_bytes(b"esto no es un modelo onnx")
    with open(tmp_path / ARCHIVOS_MODELO[1], "wb") as f:
        np.savez(f, em_santa=np.zeros(3))
    with pytest.raises(ErrorModelos) as exc:
        Sintetizador(ConfigServicioDJ(modelos_dir=tmp_path)).sintetizar("x", "em_santa", "es", tmp_path / "x.wav")
    assert "corrupto" in str(exc.value) and "cassette-dj modelos" in str(exc.value)


def test_sin_soundfile_da_ErrorModelos_claro(tmp_path, fabrica_falsa, monkeypatch):
    monkeypatch.setitem(sys.modules, "soundfile", None)          # como si no estuviera instalado el extra [dj]
    with pytest.raises(ErrorModelos) as exc:
        sint(fabrica_falsa).sintetizar("a", "em_santa", "es", tmp_path / "x.wav")
    assert "extra [dj]" in str(exc.value)


def test_descargar_si_ocioso_devuelve_la_memoria_al_sistema(tmp_path, fabrica_falsa, monkeypatch):
    """Review: sin esto glibc se queda con ~200-450 MB después de soltar Kokoro."""
    llamadas = []
    monkeypatch.setattr(mod, "_devolver_memoria", lambda: llamadas.append(1))
    reloj = Reloj()
    s = sint(fabrica_falsa, ConfigServicioDJ(descargar_tras_minutos=1), reloj)
    s.sintetizar("a", "em_santa", "es", tmp_path / "1.wav")
    reloj.t = 61
    assert s.descargar_si_ocioso() is True
    assert llamadas == [1]


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


_MEDIR_MEMORIA = """
import json, os, sys
from pathlib import Path
from kokoro_onnx import Kokoro, Tokenizer
from cassette_fm.dj.config import ConfigServicioDJ
from cassette_fm.dj.sintetizador import Sintetizador

def rss():
    with open("/proc/self/statm") as f:
        return int(f.read().split()[1]) * os.sysconf("SC_PAGE_SIZE") / 1e6

s = Sintetizador(ConfigServicioDJ(modelos_dir=Path(sys.argv[1]), descargar_tras_minutos=0))
fon = Tokenizer().phonemize("Qué tal gente son las nueve en Buenos Aires", "es")
antes = rss()
s.sintetizar(fon, "em_santa", "es", Path(sys.argv[2]))
cargado = rss()
assert s.descargar_si_ocioso() is True
print(json.dumps([antes, cargado, rss()]))
"""


def test_integracion_descargar_libera_la_memoria(tmp_path, modelos_reales):
    # en un proceso aparte: el RSS de este proceso depende de lo que hicieron los tests anteriores
    import json
    import subprocess
    salida = subprocess.run([sys.executable, "-I", "-c", _MEDIR_MEMORIA, str(modelos_reales), str(tmp_path / "x.wav")],
                            capture_output=True, text=True, check=True, timeout=120)
    antes, cargado, despues = json.loads(salida.stdout.strip().splitlines()[-1])
    assert cargado - antes > 150                       # el modelo ocupaba de verdad
    assert despues - antes < 150, f"quedaron {despues - antes:.0f} MB sin devolver"


def test_la_velocidad_del_pedido_pisa_a_la_del_servicio(tmp_path, fabrica_falsa):
    s = sint(fabrica_falsa, ConfigServicioDJ(velocidad=1.05))
    s.sintetizar("fon", "em_santa", "es", tmp_path / "a.wav", velocidad=1.3)
    s.sintetizar("fon", "em_santa", "es", tmp_path / "b.wav")
    assert [l["speed"] for l in fabrica_falsa.estado.llamadas] == [1.3, 1.05]


# --- voces con nombre y motor Piper ---

class PiperFalso:
    """Imita a piper.PiperVoice: `synthesize` da un trozo de 1 s por frase y registra lo que se le pidió."""

    def __init__(self, ruta, registro):
        from types import SimpleNamespace
        self.ruta = ruta
        self.registro = registro
        self.config = SimpleNamespace(sample_rate=22050)

    def synthesize(self, texto, syn_config=None):
        from types import SimpleNamespace
        self.registro.append((self.ruta.name, texto, syn_config.length_scale if syn_config else None))
        yield SimpleNamespace(audio_int16_bytes=b"\x01\x00" * 22050, sample_rate=22050)      # 1 s


def sint_piper(tmp_path, fabrica_falsa, voces=None):
    registro, cargas = [], []
    cfg = ConfigServicioDJ(modelos_dir=tmp_path, voces=voces or {})

    def fabrica_piper(ruta):
        cargas.append(ruta.name)
        return PiperFalso(ruta, registro)

    (tmp_path / "piper").mkdir(exist_ok=True)
    for nombre in ("es_AR-daniela-high", "es_MX-claude-high"):
        (tmp_path / "piper" / f"{nombre}.onnx").write_bytes(b"x")
    s = Sintetizador(cfg, fabrica=fabrica_falsa, reloj=Reloj(), fabrica_piper=fabrica_piper)
    return s, registro, cargas


def test_una_voz_con_nombre_se_resuelve_antes_de_sintetizar(tmp_path, fabrica_falsa):
    cfg = ConfigServicioDJ(voces={"alex_santa": "em_alex+em_santa"})
    sint(fabrica_falsa, cfg).sintetizar("fon", "alex_santa", "es", tmp_path / "a.wav")
    (llamada,) = fabrica_falsa.estado.llamadas
    assert llamada["voice"].shape == (4, 1, 3) and float(llamada["voice"][0, 0, 0]) == 4.0   # promedio de 3 y 5


def test_piper_usa_el_texto_y_la_velocidad_como_length_scale(tmp_path, fabrica_falsa):
    s, registro, cargas = sint_piper(tmp_path, fabrica_falsa)
    salida = tmp_path / "out" / "a.wav"
    dur = s.sintetizar("fon-de-kokoro", "piper:es_AR-daniela-high", "es", salida, velocidad=0.8, texto="Hola gente.")
    assert registro == [("es_AR-daniela-high.onnx", "Hola gente", pytest.approx(1 / 0.8))]
    assert dur == pytest.approx(1.0) and mutagen.File(salida).info.length == pytest.approx(1.0, abs=0.02)
    assert fabrica_falsa.estado.cargas == 0 and not list(salida.parent.glob("*.part"))   # Kokoro ni se cargó
    s.sintetizar("x", "piper:es_AR-daniela-high", "es", tmp_path / "b.wav", texto="Otra.")
    assert registro[1][2] == 1.0 and cargas == ["es_AR-daniela-high.onnx"]               # sin velocidad: natural, y se reusa


def test_piper_por_alias(tmp_path, fabrica_falsa):
    s, registro, _ = sint_piper(tmp_path, fabrica_falsa, {"daniela": "piper:es_AR-daniela-high"})
    s.sintetizar("x", "daniela", "es", tmp_path / "a.wav", texto="Hola.")
    assert registro[0][0] == "es_AR-daniela-high.onnx"


@pytest.mark.parametrize("voz, texto, mensaje", [("piper:no_existe", "Hola.", "no_existe"),
                                                 ("piper:../x", "Hola.", "inválido"),
                                                 ("piper:es_AR-daniela-high", "", "texto")])
def test_piper_con_datos_invalidos(tmp_path, fabrica_falsa, voz, texto, mensaje):
    s, _, _ = sint_piper(tmp_path, fabrica_falsa)
    with pytest.raises((ErrorModelos, ValueError), match=mensaje):
        s.sintetizar("x", voz, "es", tmp_path / "a.wav", texto=texto)


def test_voces_lista_alias_y_piper(tmp_path, fabrica_falsa):
    s, _, _ = sint_piper(tmp_path, fabrica_falsa, {"alex_santa": "em_alex+em_santa"})
    s.sintetizar("x", "em_santa", "es", tmp_path / "a.wav")     # carga Kokoro para que voces() no lea el archivo
    assert s.voces() == ["alex_santa", "am_michael", "em_alex", "em_santa",
                         "piper:es_AR-daniela-high", "piper:es_MX-claude-high"]


def test_piper_se_descarga_por_ocio(tmp_path, fabrica_falsa):
    reloj = Reloj()
    s, _, cargas = sint_piper(tmp_path, fabrica_falsa)
    s._reloj = reloj
    s.sintetizar("x", "piper:es_AR-daniela-high", "es", tmp_path / "a.wav", texto="Hola.")
    assert s.cargado
    reloj.t += 10_000
    assert s.descargar_si_ocioso() is True and not s.cargado


def test_integracion_con_piper_real(tmp_path, modelos_reales):
    pytest.importorskip("piper")
    if not (modelos_reales / "piper" / "es_AR-daniela-high.onnx").is_file():
        pytest.skip("falta el modelo de Piper es_AR-daniela-high")
    s = Sintetizador(ConfigServicioDJ(modelos_dir=modelos_reales))
    normal = s.sintetizar("", "piper:es_AR-daniela-high", "es", tmp_path / "n.wav", texto="Estamos en Reguetón dos mil.")
    lento = s.sintetizar("", "piper:es_AR-daniela-high", "es", tmp_path / "l.wav", velocidad=0.6,
                         texto="Estamos en Reguetón dos mil.")
    # la duración de Piper tiene algo de azar: solo se comprueba que ir más lento alarga claramente
    assert 1.0 < normal < 8.0 and lento > normal * 1.25


def test_piper_mete_silencios_en_las_comas_y_entre_oraciones(tmp_path, fabrica_falsa):
    s, registro, _ = sint_piper(tmp_path, fabrica_falsa)
    s._config = ConfigServicioDJ(modelos_dir=tmp_path, piper_pausa_coma_segundos=0.5, piper_pausa_oracion_segundos=1.0)
    dur = s.sintetizar("x", "piper:es_AR-daniela-high", "es", tmp_path / "a.wav",
                       texto="Uno dos, tres cuatro. Cinco seis.")
    assert [r[1] for r in registro] == ["Uno dos", "tres cuatro", "Cinco seis"]
    assert dur == pytest.approx(3 * 1.0 + 0.5 + 1.0, abs=0.01)         # tres trozos + una coma + un punto


def test_piper_sin_puntuacion_es_un_solo_trozo_sin_silencios(tmp_path, fabrica_falsa):
    s, registro, _ = sint_piper(tmp_path, fabrica_falsa)
    assert s.sintetizar("x", "piper:es_AR-daniela-high", "es", tmp_path / "a.wav", texto="Hola gente") == pytest.approx(1.0, abs=0.01)


def test_decir_le_pasa_fonemas_y_texto_al_sintetizador(tmp_path):
    class Anota:
        def sintetizar(self, fonemas, voz, lang, salida, velocidad=None, texto=None):
            self.args = (fonemas, voz, lang, salida, velocidad, texto)
            return 1.5
    s = Anota()
    fon = lambda t, l: f"<{l}:{t}>"
    prep, duracion = mod.decir(s, fon, "Hola, soy {es:dora} y nada más.", "dora", "es", tmp_path / "x.wav",
                               velocidad=1.1)
    assert duracion == 1.5 and prep == preparar("Hola, soy {es:dora} y nada más.", "es", fon)
    assert s.args == (prep.fonemas, "dora", "es", tmp_path / "x.wav", 1.1, texto_para_piper(prep.marcado))
